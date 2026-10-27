"""
jankhunter/capture.py
---------------------
Records a Playwright scenario into a sequence of timestamped JPEG frames.

Primary method: CDP Page.startScreencast
  - Gives accurate per-frame timestamps from the browser's internal clock.
  - Typical throughput: 10–24 fps depending on system load and browser throttling.
  - Sub-15 fps recording reduces jitter/stutter detection sensitivity (documented
    in README under "Honest limitations").

Fallback method: Playwright record_video + ffmpeg frame extraction
  - Used automatically if CDP startScreencast fails (e.g. some CI headless builds).
  - Timestamps are reconstructed from the video frame index × (1/fps).
  - Requires ffmpeg on PATH.

Output layout
  out_dir/
    frame_00001.jpg   ...
    frames.json       [{"t": 0.123, "path": "frame_00001.jpg"}, ...]
    gt.json           ground-truth sidecar written by the demo app via window.__jh_gt
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

from playwright.async_api import async_playwright

from jankhunter.models import Frame, Scenario

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def capture(scenario: Scenario, out_dir: Path) -> list[Frame]:
    """
    Synchronous wrapper — drives a Playwright scenario and returns captured frames.

    Args:
        scenario: Parsed Scenario describing URL, viewport, actions, and duration.
        out_dir:  Directory where frames and frames.json will be saved.

    Returns:
        List of Frame objects in ascending timestamp order.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    return asyncio.run(_capture_async(scenario, out_dir))


# ---------------------------------------------------------------------------
# Async implementation
# ---------------------------------------------------------------------------


async def _capture_async(scenario: Scenario, out_dir: Path) -> list[Frame]:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": scenario.viewport["width"], "height": scenario.viewport["height"]},
        )
        page = await context.new_page()

        frames: list[Frame] = []
        frame_index = [0]
        t0: list[float] = []

        # ── Try CDP screencast ──────────────────────────────────────────────
        cdp_ok = False
        try:
            client = await context.new_cdp_session(page)

            async def _on_screencast_frame(event: dict) -> None:
                """Callback for each CDP screencast frame."""
                idx = frame_index[0]
                frame_index[0] += 1

                metadata = event.get("metadata", {})
                # CDP timestamp is wallclock seconds; we subtract the first to get relative t
                ts_raw = metadata.get("timestamp", time.time())
                if not t0:
                    t0.append(ts_raw)
                t = ts_raw - t0[0]

                img_data = base64.b64decode(event["data"])
                fname = f"frame_{idx:05d}.jpg"
                fpath = out_dir / fname
                fpath.write_bytes(img_data)
                frames.append(Frame(t=t, path=fpath))
                log.debug("screencast frame %d  t=%.3f", idx, t)

            client.on("Page.screencastFrame", _on_screencast_frame)
            await client.send(
                "Page.startScreencast",
                {"format": "jpeg", "quality": 85, "everyNthFrame": 1},
            )
            cdp_ok = True
            log.info("CDP screencast started")
        except Exception as exc:
            log.warning("CDP screencast unavailable (%s); will use record_video fallback", exc)

        # ── Navigate & execute actions ─────────────────────────────────────
        await page.goto(scenario.url, wait_until="networkidle", timeout=30_000)

        for action in scenario.actions:
            match action.type:
                case "wait":
                    await page.wait_for_timeout(int(action.duration * 1000))
                case "click":
                    await page.mouse.click(action.x, action.y)
                case "key":
                    await page.keyboard.press(action.key)
                case "mouse_move":
                    await page.mouse.move(action.x, action.y, steps=action.steps)

        # Wait for remaining duration
        elapsed = sum(
            a.duration for a in scenario.actions if a.type == "wait"
        )
        remaining = max(0.0, scenario.duration - elapsed - 1.0)
        if remaining > 0:
            await page.wait_for_timeout(int(remaining * 1000))

        # ── Collect ground-truth sidecar from the demo app ─────────────────
        try:
            gt_data = await page.evaluate("() => window.__jh_gt_history || window.__jh_gt")
            gt_path = out_dir / "gt.json"
            gt_path.write_text(json.dumps(gt_data, indent=2), encoding="utf-8")
            log.info("Ground-truth sidecar written to %s", gt_path)
        except Exception as exc:
            log.warning("Could not collect ground-truth sidecar: %s", exc)

        # ── Stop CDP screencast ────────────────────────────────────────────
        if cdp_ok:
            try:
                await client.send("Page.stopScreencast")
            except Exception:
                pass

        await browser.close()

    # ── Fallback: ffmpeg frame extraction ─────────────────────────────────
    if not frames:
        log.info("No CDP frames captured; attempting record_video fallback")
        frames = _ffmpeg_fallback(out_dir)

    if not frames:
        raise RuntimeError(
            f"Capture produced zero frames in {out_dir}. "
            "Check that the URL is reachable and ffmpeg is on PATH (fallback)."
        )

    frames.sort(key=lambda f: f.t)

    # ── Save frames.json ──────────────────────────────────────────────────
    frames_json = [{"t": f.t, "path": str(f.path.name)} for f in frames]
    (out_dir / "frames.json").write_text(
        json.dumps(frames_json, indent=2), encoding="utf-8"
    )
    log.info("Captured %d frames to %s", len(frames), out_dir)
    return frames


# ---------------------------------------------------------------------------
# ffmpeg fallback
# ---------------------------------------------------------------------------


def _ffmpeg_fallback(out_dir: Path) -> list[Frame]:
    """
    Extract frames from a video file left by Playwright record_video.
    Expects a single *.webm file in out_dir.
    """
    videos = list(out_dir.glob("*.webm"))
    if not videos:
        return []

    video_path = videos[0]
    log.info("ffmpeg fallback: extracting frames from %s", video_path)

    # Get fps from ffprobe
    fps = _probe_fps(video_path) or 24.0

    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", "fps=fps",
            str(out_dir / "frame_%05d.jpg"),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log.error("ffmpeg failed: %s", result.stderr)
        return []

    frames = []
    for i, jpg in enumerate(sorted(out_dir.glob("frame_*.jpg"))):
        t = i / fps
        frames.append(Frame(t=t, path=jpg))
    return frames


def _probe_fps(video_path: Path) -> float | None:
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=r_frame_rate",
                "-of", "json",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        data = json.loads(result.stdout)
        rate_str: str = data["streams"][0]["r_frame_rate"]
        num, den = rate_str.split("/")
        return float(num) / float(den)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Frame loading helper (used by CLI / detect pipeline)
# ---------------------------------------------------------------------------


def load_frames(frames_dir: Path) -> list[Frame]:
    """Load previously-captured frames from a frames.json manifest."""
    manifest = frames_dir / "frames.json"
    if not manifest.exists():
        raise FileNotFoundError(f"No frames.json found in {frames_dir}")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    return [Frame(t=entry["t"], path=frames_dir / entry["path"]) for entry in data]
