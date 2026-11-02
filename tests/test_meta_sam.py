from pathlib import Path

import cv2
import numpy as np
import pytest
from meta_sam_parser import CompletedOutcome, video_segmentation_format

from jankhunter.models import Frame, SAMSeed
from jankhunter.tracking.meta_sam import (
    MAX_VIDEO_FRAMES,
    MIN_VIDEO_FRAMES,
    _build_seed_prompt,
    _sample_frames,
    _tracks_from_result,
    _write_video,
)


def _frames(tmp_path: Path, count: int) -> list[Frame]:
    frames = []
    for index in range(count):
        path = tmp_path / f"{index:04}.png"
        image = np.full((24, 32, 3), index, dtype=np.uint8)
        assert cv2.imwrite(str(path), image)
        frames.append(Frame(t=index / 12, path=path))
    return frames


def test_sam_sampling_enforces_minimum_and_caps_video_size(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least 50 frames"):
        _sample_frames(_frames(tmp_path, MIN_VIDEO_FRAMES - 1))

    sampled = _sample_frames(_frames(tmp_path, MAX_VIDEO_FRAMES + 20))
    assert len(sampled) == MAX_VIDEO_FRAMES
    assert sampled[0].t == 0
    assert sampled[-1].t == pytest.approx((MAX_VIDEO_FRAMES + 19) / 12)


def test_sam_video_writer_creates_readable_mp4(tmp_path: Path) -> None:
    frames = _frames(tmp_path, MIN_VIDEO_FRAMES)
    output = tmp_path / "capture.mp4"
    width, height = _write_video(frames, output)

    reader = cv2.VideoCapture(str(output))
    ok, frame = reader.read()
    fps = reader.get(cv2.CAP_PROP_FPS)
    reader.release()
    assert (width, height) == (32, 24)
    assert ok and frame.shape[:2] == (24, 32)
    assert fps == pytest.approx(12.0, abs=0.1)


def test_parser_boxes_become_tracks_on_original_timestamps(tmp_path: Path) -> None:
    frames = _frames(tmp_path, MIN_VIDEO_FRAMES)
    parser = video_segmentation_format().create_parser()
    parser.push(
        "<0f>1<|box;x1=3;y1=4;x2=12;y2=15;w=32;h=24|>"
        "<|mask;x=0;y=0;data=1,1,!x|>",
        emit=False,
    )
    parsed = parser.finish(CompletedOutcome()).result
    tracks = _tracks_from_result(parsed.records, "cyan game sprite", frames, 32, 24)

    assert len(tracks) == 1
    assert tracks[0].id == "sam-1"
    assert tracks[0].label == "cyan game sprite"
    assert tracks[0].points[0].bbox == (3, 4, 10, 12)
    assert tracks[0].points[0].visible
    assert tracks[0].points[1].visible is False


def test_multiple_seed_boxes_share_one_sam_prompt() -> None:
    prompt, labels = _build_seed_prompt(
        [
            SAMSeed(id=1, label="sprite", bbox=(10, 20, 30, 40), frame=0),
            SAMSeed(id=2, label="HUD", bbox=(50, 5, 100, 25), frame=4),
        ],
        width=320,
        height=240,
        frame_count=20,
    )

    assert "<0f>1<|box;x1=10;y1=20;x2=39;y2=59;w=320;h=240|>" in prompt
    assert "<4f>2<|box;x1=50;y1=5;x2=149;y2=29;w=320;h=240|>" in prompt
    assert labels == {"1": "sprite", "2": "HUD"}


def test_seed_box_outside_frame_is_rejected() -> None:
    with pytest.raises(ValueError, match="outside the captured viewport"):
        _build_seed_prompt(
            [SAMSeed(id=1, label="sprite", bbox=(90, 10, 20, 20))],
            width=100,
            height=100,
            frame_count=60,
        )
