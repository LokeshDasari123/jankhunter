"""
jankhunter/tracking/mock.py
----------------------------
MockTracker — DEV / TEST USE ONLY.

⚠️  This tracker reads a ground-truth sidecar JSON written by the demo app
    (window.__jh_gt collected by capture.py into gt.json). It is NOT a real
    visual tracker and MUST NOT be used in production or with real apps.

    The final hackathon demo MUST use the real tracker (Phase 2: MetaSAMTracker).
    This class exists solely to let us develop and test the detection pipeline
    without requiring a running SAM 3.1 instance.

Ground-truth sidecar format (gt.json)
--------------------------------------
The demo app exposes window.__jh_gt each frame:

    {
      "frame": 42,
      "t": 1.234,
      "tracks": {
        "sprite":     { "t": 1.234, "bbox": [x,y,w,h], "centroid": [cx,cy], "area": A, "visible": true },
        "hud_bar":    { ... },
        "menu_panel": { ... },
        "line_chart": { ... }
      }
    }

capture.py saves these snapshots in two ways:
  1. A single last-frame snapshot (window.__jh_gt) → gt.json
  2. A full history array (window.__jh_gt_history) → gt.json  ← preferred

MockTracker reconstructs Track objects from gt.json using either format.
When only the last-frame snapshot is available, it creates single-point tracks.

For robust testing, use the generate_mock_gt() helper to build synthetic gt.json
files, or use the TrackBuilder in tests/.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from jankhunter.models import Frame, Track, TrackPoint
from jankhunter.tracking.base import Tracker

log = logging.getLogger(__name__)


class MockTracker(Tracker):
    """
    DEV/TEST ONLY — reconstructs Track objects from a ground-truth sidecar JSON.

    Args:
        gt_path: Path to the gt.json sidecar produced by the demo app.
                 If None, looks for ``gt.json`` in the same directory as frames[0].
    """

    def __init__(self, gt_path: Path | None = None) -> None:
        self._gt_path = gt_path

    def track(self, frames: list[Frame], prompts: list[str]) -> list[Track]:
        """Build Track objects from the ground-truth sidecar."""
        gt_path = self._resolve_gt_path(frames)
        raw = json.loads(gt_path.read_text(encoding="utf-8"))

        # Support both: full history array, or single-frame snapshot
        if isinstance(raw, list):
            history = raw
        elif "tracks" in raw:
            # Single snapshot: replicate across all frame timestamps
            history = [raw]
        else:
            raise ValueError(f"Unrecognised gt.json format in {gt_path}")

        # Build label → list[TrackPoint]
        label_points: dict[str, list[TrackPoint]] = {label: [] for label in prompts}

        for entry in history:
            tracks_data = entry.get("tracks", {})
            for label in prompts:
                if label not in tracks_data:
                    continue
                p = tracks_data[label]
                try:
                    tp = TrackPoint(
                        t=float(p["t"]),
                        bbox=tuple(int(v) for v in p["bbox"]),  # type: ignore[arg-type]
                        centroid=tuple(float(v) for v in p["centroid"]),  # type: ignore[arg-type]
                        area=float(p["area"]),
                        visible=bool(p.get("visible", True)),
                    )
                    label_points[label].append(tp)
                except (KeyError, TypeError, ValueError) as exc:
                    log.warning("Skipping malformed GT entry for %s: %s", label, exc)

        # If single-snapshot, replicate across all frame timestamps
        if len(history) == 1:
            label_points = self._replicate_across_frames(label_points, frames)

        tracks = []
        for i, label in enumerate(prompts):
            points = label_points.get(label, [])
            if not points:
                log.warning("No GT points found for label '%s' — skipping track", label)
                continue
            tracks.append(Track(id=f"{label}_{i}", label=label, points=points))

        log.info("MockTracker produced %d tracks from %s", len(tracks), gt_path)
        return tracks

    # ──────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _resolve_gt_path(self, frames: list[Frame]) -> Path:
        if self._gt_path is not None:
            return self._gt_path
        if not frames:
            raise ValueError("Cannot resolve gt.json path: no frames provided and no explicit path")
        candidate = frames[0].path.parent / "gt.json"
        if not candidate.exists():
            raise FileNotFoundError(
                f"Ground-truth sidecar not found at {candidate}. "
                "Run 'jankhunter capture' first, or pass gt_path explicitly."
            )
        return candidate

    @staticmethod
    def _replicate_across_frames(
        label_points: dict[str, list[TrackPoint]],
        frames: list[Frame],
    ) -> dict[str, list[TrackPoint]]:
        """
        When only a single GT snapshot exists, replicate its track points
        across all frame timestamps (with constant bbox/centroid/area/visible).
        Useful for tests where position is not important.
        """
        result: dict[str, list[TrackPoint]] = {}
        for label, points in label_points.items():
            if not points:
                result[label] = []
                continue
            proto = points[0]
            result[label] = [
                TrackPoint(
                    t=f.t,
                    bbox=proto.bbox,
                    centroid=proto.centroid,
                    area=proto.area,
                    visible=proto.visible,
                )
                for f in frames
            ]
        return result


# ---------------------------------------------------------------------------
# Helper: build a synthetic gt.json for testing
# ---------------------------------------------------------------------------


def generate_mock_gt(
    label_sequences: dict[str, list[dict]],
) -> list[dict]:
    """
    Build a gt.json history list from simple per-label point sequences.

    Args:
        label_sequences: { label: [ { t, bbox, centroid, area, visible }, ... ] }

    Returns:
        A list of history entries ready to be serialised as gt.json.
    """
    # Gather all unique timestamps
    all_ts: list[float] = []
    for pts in label_sequences.values():
        all_ts.extend(p["t"] for p in pts)
    all_ts = sorted(set(all_ts))

    # Build a lookup: label → { t: point }
    lookup: dict[str, dict[float, dict]] = {}
    for label, pts in label_sequences.items():
        lookup[label] = {p["t"]: p for p in pts}

    history = []
    for t in all_ts:
        entry: dict = {"t": t, "frame": 0, "tracks": {}}
        for label in label_sequences:
            if t in lookup[label]:
                entry["tracks"][label] = lookup[label][t]
        history.append(entry)
    return history
