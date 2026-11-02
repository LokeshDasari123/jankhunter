"""
jankhunter/detect/jitter.py
----------------------------
Jitter detector.

Algorithm
---------
1. Extract the visible centroid time-series from a Track.
2. Smooth it with a Savitzky-Golay filter.
3. Compute the residual (original - smoothed).
4. If the RMS of the residual exceeds config.jitter_threshold_px, the track
   is flagged as jittery.

Rationale: Savitzky-Golay preserves the low-frequency motion signal while
attenuating high-frequency noise. A large residual RMS after smoothing means
the element is moving erratically at a scale not explained by intentional motion.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import savgol_filter

from jankhunter.detect.config import DetectorConfig
from jankhunter.models import Defect, Frame, Track


def detect_jitter(
    track: Track,
    frames: list[Frame],
    config: DetectorConfig | None = None,
) -> list[Defect]:
    """
    Detect high-frequency centroid jitter in a single Track.

    Args:
        track:  The track to analyse.
        frames: Full list of captured frames (used to resolve frame indices).
        config: Detector configuration (defaults to DetectorConfig()).

    Returns:
        A list containing at most one Defect of type "jitter".
    """
    cfg = config or DetectorConfig()

    visible_pts = [p for p in track.points if p.visible]
    if len(visible_pts) < cfg.jitter_min_points:
        return []

    cx = np.array([p.centroid[0] for p in visible_pts], dtype=float)
    cy = np.array([p.centroid[1] for p in visible_pts], dtype=float)
    ts = np.array([p.t for p in visible_pts], dtype=float)

    # Clamp SG window to available data
    window = min(cfg.jitter_sg_window, len(visible_pts))
    if window % 2 == 0:
        window -= 1
    if window <= cfg.jitter_sg_poly:
        return []

    smx = savgol_filter(cx, window_length=window, polyorder=cfg.jitter_sg_poly)
    smy = savgol_filter(cy, window_length=window, polyorder=cfg.jitter_sg_poly)

    residual = np.sqrt((cx - smx) ** 2 + (cy - smy) ** 2)
    rms = float(np.sqrt(np.mean(residual ** 2)))

    if rms < cfg.jitter_threshold_px:
        return []

    severity = min(1.0, rms / cfg.jitter_severity_cap_px)

    # Evidence: frames with largest residuals
    top_k = min(5, len(residual))
    top_indices_local = np.argsort(residual)[-top_k:][::-1]
    evidence_ts = set(ts[i] for i in top_indices_local)
    frame_indices = [i for i, f in enumerate(frames) if f.t in evidence_ts]

    return [
        Defect(
            type="jitter",
            track_id=track.id,
            label=track.label,
            t_start=float(ts[0]),
            t_end=float(ts[-1]),
            severity=round(severity, 4),
            metric=round(rms, 4),
            evidence=frame_indices[:5],
        )
    ]
