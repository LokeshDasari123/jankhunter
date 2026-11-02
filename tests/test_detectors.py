"""
tests/test_detectors.py
------------------------
Pytest test suite for all five JankHunter detectors.

Strategy
--------
Each detector has TWO test cases:

  1. POSITIVE test: inject the specific defect into an otherwise clean trajectory
     and assert that the detector emits at least one Defect of the correct type.

  2. NEGATIVE test: use a clean (smooth, stable, always-visible) trajectory and
     assert that the detector emits zero false positives.

All tests work on SYNTHETIC Track data — no real video files are needed.
"""

from __future__ import annotations

from pathlib import Path

from jankhunter.detect.config import DetectorConfig
from jankhunter.detect.flicker import detect_flicker
from jankhunter.detect.jitter import detect_jitter
from jankhunter.detect.layout_jump import detect_layout_jump
from jankhunter.detect.run import detect_all
from jankhunter.detect.stutter import detect_stutter
from jankhunter.detect.vanish import detect_vanish
from jankhunter.models import Frame, Track, TrackPoint

# ─── Synthetic trajectory helpers ─────────────────────────────────────────────


def _make_frames(n: int, fps: float = 20.0) -> list[Frame]:
    """Create n synthetic Frame objects with evenly-spaced timestamps."""
    return [Frame(t=i / fps, path=Path(f"/tmp/frame_{i:05d}.jpg")) for i in range(n)]


def _make_clean_track(
    n: int = 60,
    fps: float = 20.0,
    vx: float = 5.0,
    vy: float = 3.0,
    start_x: float = 100.0,
    start_y: float = 100.0,
    label: str = "sprite",
    track_id: str = "sprite_0",
) -> Track:
    """
    Build a perfectly smooth, always-visible Track.
    Centroid moves linearly at (vx, vy) px/frame.
    """
    pts = []
    for i in range(n):
        t = i / fps
        cx = start_x + vx * i
        cy = start_y + vy * i
        pts.append(
            TrackPoint(
                t=t,
                bbox=(int(cx - 12), int(cy - 12), 24, 24),
                centroid=(cx, cy),
                area=576.0,
                visible=True,
            )
        )
    return Track(id=track_id, label=label, points=pts)


def _inject_jitter(track: Track, amplitude: float = 5.0) -> Track:
    """Add high-frequency noise to centroid of each TrackPoint."""
    import random

    rng = random.Random(42)
    new_pts = []
    for p in track.points:
        noise_x = rng.uniform(-amplitude, amplitude)
        noise_y = rng.uniform(-amplitude, amplitude)
        cx = p.centroid[0] + noise_x
        cy = p.centroid[1] + noise_y
        new_pts.append(
            TrackPoint(
                t=p.t,
                bbox=p.bbox,
                centroid=(cx, cy),
                area=p.area,
                visible=p.visible,
            )
        )
    return Track(id=track.id, label=track.label, points=new_pts)


def _inject_layout_jump(track: Track, jump_frame: int = 20, jump_px: float = 80.0) -> Track:
    """At jump_frame, teleport the centroid by jump_px, preceded by a static frame."""
    pts = list(track.points)
    # Freeze movement for 2 frames before the jump
    for k in (jump_frame - 2, jump_frame - 1):
        if 0 <= k < len(pts):
            p = pts[k]
            ref = pts[max(0, k - 1)]
            pts[k] = TrackPoint(
                t=p.t, bbox=ref.bbox, centroid=ref.centroid, area=ref.area, visible=True
            )
    # Apply jump
    if jump_frame < len(pts):
        p = pts[jump_frame]
        cx = p.centroid[0] + jump_px
        cy = p.centroid[1]
        pts[jump_frame] = TrackPoint(
            t=p.t,
            bbox=(int(cx - 12), int(cy - 12), 24, 24),
            centroid=(cx, cy),
            area=p.area,
            visible=True,
        )
    return Track(id=track.id, label=track.label, points=pts)


def _inject_flicker(track: Track, toggle_frames: list[int] | None = None) -> Track:
    """Toggle visibility at the given frame indices."""
    if toggle_frames is None:
        toggle_frames = [20, 21, 22, 23, 24]
    pts = list(track.points)
    for k in toggle_frames:
        if 0 <= k < len(pts):
            p = pts[k]
            pts[k] = TrackPoint(
                t=p.t, bbox=p.bbox, centroid=p.centroid, area=p.area,
                visible=not p.visible,
            )
    return Track(id=track.id, label=track.label, points=pts)


def _inject_vanish(track: Track, start: int = 15, gap: int = 5) -> Track:
    """Make the element invisible for `gap` frames starting at `start`."""
    pts = list(track.points)
    for k in range(start, min(start + gap, len(pts))):
        p = pts[k]
        pts[k] = TrackPoint(
            t=p.t, bbox=p.bbox, centroid=p.centroid, area=p.area, visible=False
        )
    return Track(id=track.id, label=track.label, points=pts)


def _inject_stutter(track: Track, gap_frame: int = 25, gap_s: float = 0.5) -> Track:
    """Add a large timestamp gap at gap_frame, simulating a dropped-frame stutter."""
    pts = list(track.points)
    if gap_frame >= len(pts):
        return track
    # Shift all timestamps from gap_frame onwards by gap_s
    new_pts = []
    for i, p in enumerate(pts):
        extra = gap_s if i >= gap_frame else 0.0
        new_pts.append(
            TrackPoint(t=p.t + extra, bbox=p.bbox, centroid=p.centroid, area=p.area, visible=p.visible)
        )
    return Track(id=track.id, label=track.label, points=new_pts)


# ─── Detector config with lower thresholds for synthetic tests ────────────────


def _tight_config() -> DetectorConfig:
    """Config with tightened thresholds so synthetic injections are always detected."""
    return DetectorConfig(
        jitter_threshold_px=0.5,
        jitter_sg_window=5,
        jitter_min_points=10,
        jump_multiplier=3.0,
        jump_min_points=4,
        flicker_window=8,
        flicker_toggle_threshold=2,
        flicker_min_points=6,
        vanish_min_gap_frames=1,
        vanish_drift_px=50.0,
        vanish_min_points=4,
        stutter_gap_s=0.2,
        stutter_motion_px_s=1.0,
        stutter_min_points=4,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Jitter tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestJitter:
    def test_detects_jittery_track(self):
        """Inject high-frequency noise → expect at least one jitter defect."""
        frames = _make_frames(60)
        clean = _make_clean_track(60)
        jittery = _inject_jitter(clean, amplitude=5.0)
        defects = detect_jitter(jittery, frames, _tight_config())
        assert len(defects) >= 1, "Expected jitter defect not emitted"
        assert defects[0].type == "jitter"
        assert 0.0 < defects[0].severity <= 1.0
        assert defects[0].track_id == "sprite_0"

    def test_no_false_positive_clean_track(self):
        """Clean linear track → zero jitter defects."""
        frames = _make_frames(60)
        clean = _make_clean_track(60)
        defects = detect_jitter(clean, frames, DetectorConfig(jitter_threshold_px=2.0))
        assert defects == [], f"False positive jitter on clean track: {defects}"

    def test_insufficient_points_returns_empty(self):
        """Track with too few points → no defect emitted (no crash)."""
        frames = _make_frames(5)
        track = _make_clean_track(5)
        defects = detect_jitter(track, frames, DetectorConfig(jitter_min_points=10))
        assert defects == []


# ═══════════════════════════════════════════════════════════════════════════════
# Layout Jump tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestLayoutJump:
    def test_detects_jump(self):
        """Inject a 80 px teleport with static frames before → layout_jump defect."""
        frames = _make_frames(60)
        track = _inject_layout_jump(_make_clean_track(60), jump_frame=20, jump_px=80.0)
        cfg = _tight_config()
        defects = detect_layout_jump(track, frames, cfg)
        assert len(defects) >= 1, f"Expected layout_jump defect, got: {defects}"
        assert defects[0].type == "layout_jump"
        assert defects[0].metric > 50.0  # should measure close to 80 px

    def test_no_false_positive_smooth_motion(self):
        """Smooth constant-velocity track → no layout_jump."""
        frames = _make_frames(60)
        clean = _make_clean_track(60, vx=3.0, vy=2.0)
        defects = detect_layout_jump(clean, frames, DetectorConfig())
        assert defects == [], f"False positive layout_jump: {defects}"

    def test_no_false_positive_for_smooth_motion_after_pause(self):
        """An animation easing into motion after a pause is not a layout jump."""
        frames = _make_frames(60)
        track = _make_clean_track(60, vx=0.0, vy=0.0)
        points = []
        x = 100.0
        for i, point in enumerate(track.points):
            if i >= 20:
                x += min((i - 19) * 0.5, 5.0)
            points.append(TrackPoint(t=point.t, bbox=point.bbox,
                                     centroid=(x, point.centroid[1]), area=point.area,
                                     visible=point.visible))
        eased = Track(id=track.id, label=track.label, points=points)
        assert detect_layout_jump(eased, frames, DetectorConfig()) == []

    def test_static_element_not_flagged(self):
        """A perfectly static element → no jump (median displacement = 0)."""
        frames = _make_frames(60)
        track = _make_clean_track(60, vx=0.0, vy=0.0)
        defects = detect_layout_jump(track, frames, DetectorConfig())
        assert defects == []


# ═══════════════════════════════════════════════════════════════════════════════
# Flicker tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestFlicker:
    def test_detects_rapid_toggles(self):
        """Multiple rapid visibility toggles → flicker defect."""
        frames = _make_frames(60)
        track = _inject_flicker(_make_clean_track(60), toggle_frames=[20, 21, 22, 23, 24])
        cfg = _tight_config()
        defects = detect_flicker(track, frames, cfg)
        assert len(defects) >= 1, f"Expected flicker defect, got: {defects}"
        assert defects[0].type == "flicker"

    def test_no_false_positive_always_visible(self):
        """Always-visible track → no flicker."""
        frames = _make_frames(60)
        clean = _make_clean_track(60)
        defects = detect_flicker(clean, frames, DetectorConfig())
        assert defects == []

    def test_single_toggle_below_threshold_not_flagged(self):
        """One visibility toggle (e.g. intentional hide) → no flicker if below threshold."""
        frames = _make_frames(60)
        track = _inject_flicker(_make_clean_track(60), toggle_frames=[30])  # single toggle
        cfg = DetectorConfig(flicker_toggle_threshold=3, flicker_window=10)
        defects = detect_flicker(track, frames, cfg)
        assert defects == [], f"False positive flicker on single toggle: {defects}"


# ═══════════════════════════════════════════════════════════════════════════════
# Vanish tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestVanish:
    def test_detects_vanish_in_place(self):
        """5-frame disappearance then reappear at same position → vanish defect."""
        frames = _make_frames(60)
        # Use a static track so drift is 0
        static_track = _make_clean_track(60, vx=0.0, vy=0.0)
        track = _inject_vanish(static_track, start=20, gap=5)
        cfg = _tight_config()
        defects = detect_vanish(track, frames, cfg)
        assert len(defects) >= 1, f"Expected vanish defect, got: {defects}"
        assert defects[0].type == "vanish"
        assert defects[0].metric >= 1.0  # at least 1 invisible frame

    def test_no_false_positive_always_visible(self):
        """Always-visible track → no vanish."""
        frames = _make_frames(60)
        clean = _make_clean_track(60)
        defects = detect_vanish(clean, frames, DetectorConfig())
        assert defects == []

    def test_off_screen_exit_not_flagged(self):
        """Element that disappears AND reappears far away → not flagged as vanish."""
        frames = _make_frames(60)
        track = _inject_vanish(_make_clean_track(60, vx=0.0, vy=0.0), start=20, gap=3)
        # Teleport on reappear: move centroid 500 px away
        pts = list(track.points)
        for k in range(23, 26):
            if k < len(pts):
                p = pts[k]
                pts[k] = TrackPoint(
                    t=p.t, bbox=p.bbox,
                    centroid=(p.centroid[0] + 500.0, p.centroid[1]),
                    area=p.area, visible=True,
                )
        track = Track(id=track.id, label=track.label, points=pts)
        cfg = DetectorConfig(vanish_drift_px=30.0)
        defects = detect_vanish(track, frames, cfg)
        assert defects == [], f"False positive vanish for off-screen exit: {defects}"

    def test_long_intentional_hide_not_flagged(self):
        """A panel hidden for several seconds and restored in place is intentional."""
        frames = _make_frames(60)
        track = _inject_vanish(_make_clean_track(60, vx=0.0, vy=0.0), start=10, gap=24)
        assert detect_vanish(track, frames, DetectorConfig(vanish_max_gap_s=0.75)) == []


# ═══════════════════════════════════════════════════════════════════════════════
# Stutter tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestStutter:
    def test_detects_duplicate_frames_during_motion(self, tmp_path):
        """Repeated image content during a moving track is flagged with its track ID."""
        import cv2
        import numpy as np

        images = [np.full((32, 32, 3), value, dtype=np.uint8) for value in (0, 80, 80, 200)]
        frames = []
        for i, image in enumerate(images):
            path = tmp_path / f"frame_{i}.jpg"
            assert cv2.imwrite(str(path), image)
            frames.append(Frame(t=i * 0.05, path=path))
        track = _make_clean_track(4, fps=20.0, vx=20.0, vy=0.0, track_id="moving", label="sprite")
        cfg = DetectorConfig(stutter_min_points=4, stutter_motion_px_s=10.0)
        defects = detect_stutter(track, frames, cfg)
        assert defects
        assert all(defect.track_id == "moving" for defect in defects)

    def test_small_motion_is_not_an_image_duplicate(self, tmp_path):
        """A one-pixel sprite move must survive the duplicate-frame comparison."""
        import cv2
        import numpy as np

        frames = []
        for i in range(4):
            image = np.zeros((64, 64, 3), dtype=np.uint8)
            image[24:28, 20 + i : 24 + i] = 255
            path = tmp_path / f"moving_{i}.jpg"
            assert cv2.imwrite(str(path), image)
            frames.append(Frame(t=i * 0.05, path=path))
        track = _make_clean_track(4, fps=20.0, vx=20.0, track_id="moving", label="sprite")

        assert detect_stutter(
            track,
            frames,
            DetectorConfig(stutter_min_points=4, stutter_motion_px_s=10.0),
        ) == []

    def test_detects_timestamp_gap_during_motion(self):
        """Large timestamp gap while element is moving → stutter defect."""
        frames = _make_frames(60)
        track = _inject_stutter(_make_clean_track(60, vx=5.0, vy=3.0), gap_frame=25, gap_s=0.5)
        cfg = _tight_config()
        defects = detect_stutter(track, frames, cfg)
        assert len(defects) >= 1, f"Expected stutter defect, got: {defects}"
        assert defects[0].type == "stutter"
        assert defects[0].metric >= 0.2  # should be close to 0.5 s gap

    def test_no_false_positive_smooth_timestamps(self):
        """Evenly-spaced timestamps → no stutter."""
        frames = _make_frames(60)
        clean = _make_clean_track(60, vx=5.0)
        defects = detect_stutter(clean, frames, DetectorConfig())
        assert defects == []

    def test_gap_on_static_element_not_flagged(self):
        """Large timestamp gap but element is not moving → no stutter."""
        frames = _make_frames(60)
        track = _inject_stutter(_make_clean_track(60, vx=0.0, vy=0.0), gap_frame=25, gap_s=0.5)
        cfg = DetectorConfig(stutter_motion_px_s=5.0)  # high threshold → static not flagged
        defects = detect_stutter(track, frames, cfg)
        assert defects == []


# ═══════════════════════════════════════════════════════════════════════════════
# detect_all aggregation test
# ═══════════════════════════════════════════════════════════════════════════════


class TestDetectAll:
    def test_aggregate_finds_multiple_defect_types(self):
        """Inject jitter and flicker into two separate tracks; detect_all finds both."""
        frames = _make_frames(60)
        jittery_track = _inject_jitter(_make_clean_track(60, track_id="t_jitter", label="jitter_elem"))
        flicker_track = _inject_flicker(
            _make_clean_track(60, track_id="t_flicker", label="flicker_elem"),
            toggle_frames=[20, 21, 22, 23, 24],
        )
        cfg = _tight_config()
        defects, total_severity = detect_all([jittery_track, flicker_track], frames, cfg)
        types_found = {d.type for d in defects}
        assert "jitter" in types_found, f"Jitter not found. Defects: {defects}"
        assert "flicker" in types_found, f"Flicker not found. Defects: {defects}"
        assert 0.0 < total_severity <= 1.0

    def test_clean_tracks_yield_zero_severity(self):
        """All clean tracks → total_severity == 0.0."""
        frames = _make_frames(60)
        tracks = [_make_clean_track(60, track_id=f"t{i}", label=f"elem{i}") for i in range(3)]
        defects, total_severity = detect_all(tracks, frames, DetectorConfig())
        assert total_severity == 0.0, f"Non-zero severity on clean tracks: {defects}"
