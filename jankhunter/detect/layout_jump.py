"""
jankhunter/detect/layout_jump.py
----------------------------------
Layout Jump detector.

Algorithm
---------
1. Compute frame-to-frame centroid displacement for all visible frames.
2. Compute the median displacement (expected "background" motion level).
3. A "jump" frame is one where:
   - displacement > median * jump_multiplier  (sudden large movement)
   - previous frame displacement < median * low_velocity_fraction  (no velocity ramp-up)
4. Each qualifying jump frame becomes a Defect.

Rationale: Legitimate smooth animations have a velocity ramp; sudden jumps
from near-zero velocity are layout instability.
"""

from __future__ import annotations

import numpy as np

from jankhunter.detect.config import DetectorConfig
from jankhunter.models import Defect, Frame, Track


def detect_layout_jump(
    track: Track,
    frames: list[Frame],
    config: DetectorConfig | None = None,
) -> list[Defect]:
    """
    Detect sudden large centroid displacements with no velocity ramp.

    Returns:
        A list of Defect objects, one per jump event.
    """
    cfg = config or DetectorConfig()

    visible_pts = [p for p in track.points if p.visible]
    if len(visible_pts) < cfg.jump_min_points:
        return []

    cx = np.array([p.centroid[0] for p in visible_pts], dtype=float)
    cy = np.array([p.centroid[1] for p in visible_pts], dtype=float)
    ts = np.array([p.t for p in visible_pts], dtype=float)

    # Frame-to-frame displacement
    disp = np.sqrt(np.diff(cx) ** 2 + np.diff(cy) ** 2)
    if len(disp) == 0:
        return []

    median_disp = float(np.median(disp))
    if median_disp == 0:
        median_disp = 1e-6  # avoid division by zero for static elements

    jump_threshold = median_disp * cfg.jump_multiplier
    low_vel_threshold = median_disp * cfg.jump_low_velocity_fraction

    defects: list[Defect] = []

    for i in range(1, len(disp)):
        if disp[i] > jump_threshold and disp[i - 1] < low_vel_threshold:
            severity = min(1.0, disp[i] / cfg.jump_severity_cap_px)
            # Frame index in global frames list
            jump_t = ts[i + 1]  # the frame AFTER the jump
            frame_indices = [j for j, f in enumerate(frames) if abs(f.t - jump_t) < 0.05]

            defects.append(
                Defect(
                    type="layout_jump",
                    track_id=track.id,
                    label=track.label,
                    t_start=float(ts[i]),
                    t_end=float(ts[i + 1]),
                    severity=round(severity, 4),
                    metric=round(float(disp[i]), 4),
                    evidence=frame_indices[:3],
                )
            )

    return defects
