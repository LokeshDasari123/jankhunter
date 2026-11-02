"""
jankhunter/detect/config.py
----------------------------
Detector configuration dataclass with documented thresholds.

All thresholds have default values that work well on 15–24 fps captures of
browser UIs with viewport 1280×720. Pass a custom DetectorConfig to override
any threshold.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DetectorConfig:
    # ── Jitter ────────────────────────────────────────────────────────────────
    # RMS of the residual after Savitzky-Golay smoothing, in pixels.
    # Tracks with residual RMS above this threshold are flagged as jittery.
    jitter_threshold_px: float = 1.5

    # Savitzky-Golay window length (must be odd, >= poly_order+2)
    jitter_sg_window: int = 7

    # Savitzky-Golay polynomial order
    jitter_sg_poly: int = 2

    # Minimum number of visible TrackPoints needed to run the jitter detector
    jitter_min_points: int = 10

    # ── Layout Jump ───────────────────────────────────────────────────────────
    # A frame-to-frame displacement is a "jump" if it exceeds
    #   median_displacement * jump_multiplier
    # AND the previous frame's displacement was below low_velocity_fraction * median.
    jump_multiplier: float = 5.0
    jump_low_velocity_fraction: float = 0.5
    jump_min_points: int = 4

    # ── Flicker ───────────────────────────────────────────────────────────────
    # In a sliding window of `flicker_window` frames, count how many times the
    # visibility boolean toggles (True→False or False→True).
    # Flag if toggle_count >= flicker_toggle_threshold.
    flicker_window: int = 10
    flicker_toggle_threshold: int = 2
    flicker_min_points: int = 8

    # ── Vanish ────────────────────────────────────────────────────────────────
    # Detect visible → invisible (≥ vanish_min_gap_frames) → visible sequences
    # where the centroid before and after are within vanish_drift_px of each other.
    vanish_min_gap_frames: int = 1
    vanish_drift_px: float = 20.0
    vanish_min_points: int = 4
    # Longer hides usually represent an intentional state transition, not a blink.
    vanish_max_gap_s: float = 0.75

    # ── Stutter ───────────────────────────────────────────────────────────────
    # A timestamp gap > stutter_gap_s while centroid is moving
    # (velocity > stutter_motion_px_s px/s) is a stutter event.
    stutter_gap_s: float = 0.1
    stutter_motion_px_s: float = 5.0
    stutter_min_points: int = 4

    # ── Severity normalisation caps ───────────────────────────────────────────
    # Metrics above these caps are clamped to severity = 1.0
    jitter_severity_cap_px: float = 10.0
    jump_severity_cap_px: float = 200.0
    flicker_severity_cap_toggles: float = 10.0
    vanish_severity_cap_frames: float = 30.0
    stutter_severity_cap_s: float = 1.0

    # ── Aggregation ───────────────────────────────────────────────────────────
    # Weight per defect type for total severity computation (must sum > 0)
    severity_weights: dict[str, float] = field(
        default_factory=lambda: {
            "jitter": 1.0,
            "layout_jump": 1.5,
            "flicker": 1.2,
            "vanish": 1.0,
            "stutter": 1.0,
        }
    )
