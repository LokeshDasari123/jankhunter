"""SAM 3.1 video tracking through Meta's documented Responses API."""

from __future__ import annotations

import tempfile
from contextlib import suppress
from pathlib import Path

import cv2
import numpy as np
from meta_sam_parser import (
    CompletedOutcome,
    FramePrompt,
    PromptBox,
    PromptObject,
    SegmentationBoxRecord,
    build_object_prompt,
    video_segmentation_format,
)
from openai import APIStatusError, OpenAI

from jankhunter.config import model_api_key
from jankhunter.models import Frame, SAMSeed, Track, TrackPoint
from jankhunter.tracking.base import Tracker

SAM_BASE_URL = "https://api.meta.ai/v1"
SAM_MODEL = "sam-3.1"
MIN_VIDEO_FRAMES = 50
MAX_VIDEO_FRAMES = 180


def _sample_frames(frames: list[Frame], limit: int = MAX_VIDEO_FRAMES) -> list[Frame]:
    if len(frames) < MIN_VIDEO_FRAMES:
        raise ValueError(f"SAM video tracking requires at least {MIN_VIDEO_FRAMES} frames.")
    if len(frames) <= limit:
        return frames
    indices = np.linspace(0, len(frames) - 1, limit, dtype=int)
    return [frames[i] for i in indices]


def _write_video(frames: list[Frame], path: Path) -> tuple[int, int]:
    first = cv2.imread(str(frames[0].path))
    if first is None:
        raise ValueError(f"Could not read captured frame: {frames[0].path}")
    height, width = first.shape[:2]
    elapsed = frames[-1].t - frames[0].t
    fps = (len(frames) - 1) / elapsed if elapsed > 0 else 10.0
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError("OpenCV could not create the temporary MPEG-4 video for SAM.")
    try:
        for frame in frames:
            image = cv2.imread(str(frame.path))
            if image is None:
                raise ValueError(f"Could not read captured frame: {frame.path}")
            if image.shape[:2] != (height, width):
                image = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
            writer.write(image)
    finally:
        writer.release()
    return width, height


def _tracks_from_result(
    records: tuple[object, ...],
    labels: str | dict[str, str],
    sampled: list[Frame],
    width: int,
    height: int,
) -> list[Track]:
    by_id: dict[str, dict[int, TrackPoint]] = {}
    for record in records:
        if not isinstance(record, SegmentationBoxRecord) or record.frame is None:
            continue
        frame_index = record.frame.frame_index
        if frame_index < 0 or frame_index >= len(sampled):
            continue
        left, top = max(0, int(record.left)), max(0, int(record.top))
        right, bottom = min(width, int(record.right)), min(height, int(record.bottom))
        if right <= left or bottom <= top:
            continue
        by_id.setdefault(str(record.object_id), {})[frame_index] = TrackPoint(
            t=sampled[frame_index].t,
            bbox=(left, top, right - left, bottom - top),
            centroid=((left + right) / 2, (top + bottom) / 2),
            area=float((right - left) * (bottom - top)),
            visible=True,
        )
    tracks: list[Track] = []
    for object_id, points in by_id.items():
        full_points = [
            points.get(i)
            or TrackPoint(t=frame.t, bbox=(0, 0, 0, 0), centroid=(0.0, 0.0), area=0, visible=False)
            for i, frame in enumerate(sampled)
        ]
        label = labels if isinstance(labels, str) else labels.get(object_id, f"object {object_id}")
        tracks.append(Track(id=f"sam-{object_id}", label=label, points=full_points))
    return tracks


def _build_seed_prompt(
    seeds: list[SAMSeed], width: int, height: int, frame_count: int
) -> tuple[str, dict[str, str]]:
    if not seeds:
        raise ValueError("SAM seeded tracking requires at least one seed box.")
    if len({seed.id for seed in seeds}) != len(seeds):
        raise ValueError("SAM seed ids must be unique.")
    objects: list[PromptObject] = []
    labels: dict[str, str] = {}
    for seed in seeds:
        x, y, box_width, box_height = seed.bbox
        if x + box_width > width or y + box_height > height:
            raise ValueError(f"SAM seed box {seed.id} falls outside the captured viewport.")
        if seed.frame >= frame_count:
            raise ValueError(f"SAM seed frame {seed.frame} is outside the sampled video.")
        objects.append(PromptObject(
            id=seed.id,
            prompts=[FramePrompt(
                frame=seed.frame,
                box=PromptBox(x, y, x + box_width, y + box_height),
            )],
        ))
        labels[str(seed.id)] = seed.label
    return build_object_prompt(size=(width, height), objects=objects), labels


class MetaSAMTracker(Tracker):
    """Track prompted concepts or manually seeded objects using Meta SAM 3.1."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or model_api_key()
        if not self._api_key:
            raise RuntimeError("Set MODEL_API_KEY in .env or the process environment to use SAM.")

    def track(self, frames: list[Frame], prompts: list[str]) -> list[Track]:
        if not prompts or any(not prompt.strip() for prompt in prompts):
            raise ValueError("SAM requires at least one short, non-empty noun phrase.")
        sampled = _sample_frames(frames)
        tracks: list[Track] = []
        for prompt in prompts:
            tracks.extend(self._track_video(sampled, prompt, prompt))
        return tracks

    def track_seeded(self, frames: list[Frame], seeds: list[SAMSeed]) -> list[Track]:
        """Track manually marked objects together in one SAM request."""
        if not seeds:
            raise ValueError("SAM seeded tracking requires at least one seed box.")
        if len({seed.id for seed in seeds}) != len(seeds):
            raise ValueError("SAM seed ids must be unique.")
        sampled = _sample_frames(frames)
        with tempfile.TemporaryDirectory(prefix="jankhunter-sam-") as temp_dir:
            video_path = Path(temp_dir) / "capture.mp4"
            width, height = _write_video(sampled, video_path)
            prompt, labels = _build_seed_prompt(seeds, width, height, len(sampled))
            return self._send_video(sampled, prompt, labels, width, height, video_path, True)

    def _track_video(
        self,
        sampled: list[Frame],
        prompt: str,
        labels: str | dict[str, str],
        *,
        forward: bool = False,
    ) -> list[Track]:
        with tempfile.TemporaryDirectory(prefix="jankhunter-sam-") as temp_dir:
            video_path = Path(temp_dir) / "capture.mp4"
            width, height = _write_video(sampled, video_path)
            return self._send_video(sampled, prompt, labels, width, height, video_path, forward)

    def _send_video(
        self,
        sampled: list[Frame],
        prompt: str,
        labels: str | dict[str, str],
        width: int,
        height: int,
        video_path: Path,
        forward: bool,
    ) -> list[Track]:
        client = OpenAI(api_key=self._api_key, base_url=SAM_BASE_URL)
        uploaded = None
        try:
            with video_path.open("rb") as video_file:
                uploaded = client.files.create(
                    file=video_file,
                    purpose="user_data",
                    expires_after={"anchor": "created_at", "seconds": 3600},
                )
            metadata = {"include_confidence": "true"}
            if forward:
                metadata["propagation_direction"] = "forward"
            parsed_stream = video_segmentation_format().create_parser()
            with client.responses.stream(
                model=SAM_MODEL,
                input=[{
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_video", "file_id": uploaded.id},
                    ],
                }],
                metadata=metadata,
            ) as stream:
                completed = False
                for event in stream:
                    if event.type == "response.output_text.delta":
                        parsed_stream.push(event.delta, emit=False)
                    elif event.type == "response.completed":
                        completed = True
            if not completed:
                raise RuntimeError("SAM response ended before response.completed.")
            result = parsed_stream.finish(CompletedOutcome()).result
            return _tracks_from_result(result.records, labels, sampled, width, height)
        except APIStatusError as exc:
            if exc.status_code == 402:
                raise RuntimeError(
                    "Meta rejected the SAM request because billing is restricted (HTTP 402). "
                    "Check Meta Billing before retrying."
                ) from exc
            raise RuntimeError(f"Meta SAM request failed (HTTP {exc.status_code}).") from exc
        finally:
            if uploaded is not None:
                with suppress(Exception):
                    client.files.delete(uploaded.id)
            client.close()
