"""SAM 3.1 video tracking through Meta's documented Responses API."""

from __future__ import annotations

import tempfile
from contextlib import suppress
from pathlib import Path

import cv2
import numpy as np
from meta_sam_parser import CompletedOutcome, SegmentationBoxRecord, video_segmentation_format
from openai import OpenAI

from jankhunter.config import model_api_key
from jankhunter.models import Frame, Track, TrackPoint
from jankhunter.tracking.base import Tracker

SAM_BASE_URL = "https://api.meta.ai/v1"
SAM_MODEL = "sam-3.1"
MIN_VIDEO_FRAMES = 50
MAX_VIDEO_FRAMES = 120


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
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (width, height))
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
    records: tuple[object, ...], prompt: str, sampled: list[Frame], width: int, height: int
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
        tracks.append(Track(id=f"sam-{object_id}", label=prompt, points=full_points))
    return tracks


class MetaSAMTracker(Tracker):
    """Track one or more visual concepts using Meta SAM 3.1.

    Each noun phrase is a separate SAM request. For predictable cost, pass only
    the element needed for the current analysis.
    """

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
            with tempfile.TemporaryDirectory(prefix="jankhunter-sam-") as temp_dir:
                video_path = Path(temp_dir) / "capture.mp4"
                width, height = _write_video(sampled, video_path)
                client = OpenAI(api_key=self._api_key, base_url=SAM_BASE_URL)
                uploaded = None
                try:
                    with video_path.open("rb") as video_file:
                        uploaded = client.files.create(
                            file=video_file,
                            purpose="user_data",
                            expires_after={"anchor": "created_at", "seconds": 3600},
                        )
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
                        metadata={"include_confidence": "true"},
                    ) as stream:
                        completed = False
                        for event in stream:
                            if event.type == "response.output_text.delta":
                                parsed_stream.push(event.delta, emit=False)
                            elif event.type == "response.completed":
                                completed = True
                        outcome = CompletedOutcome() if completed else None
                    if outcome is None:
                        raise RuntimeError("SAM response ended before response.completed.")
                    result = parsed_stream.finish(outcome).result
                    tracks.extend(_tracks_from_result(result.records, prompt, sampled, width, height))
                finally:
                    if uploaded is not None:
                        with suppress(Exception):
                            client.files.delete(uploaded.id)
                    client.close()
        return tracks
