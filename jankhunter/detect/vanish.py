"""
jankhunter/detect/vanish.py
----------------------------
Vanish detector.

Algorithm
---------
Scan the track for sequences:
  visible=True (≥1 frame) → visible=False (≥ vanish_min_gap_frames) → visible=True (≥1 frame)

After the element reappears, check that its centroid is within `vanish_drift_px`
of where it was before it disappeared.  (This distinguishes intentional off-screen
navigation from unexpected vanishing-in-place.)

Rationale: Elements that vanish briefly and reappear at approximately the same
position are experiencing a rendering bug, not an intentional state change.
"""

from __future__ import annotations

import math

from jankhunter.detect.config import DetectorConfig
from jankhunter.models import Defect, Frame, Track


def detect_vanish(
    track: Track,
    frames: list[Frame],
    config: DetectorConfig | None = None,
) -> list[Defect]:
    """
    Detect disappear-then-reappear events at approximately the same position.

    Returns:
        A list of Defect objects, one per vanish event.
    """
    cfg = config or DetectorConfig()
    pts = track.points

    if len(pts) < cfg.vanish_min_points:
        return []

    defects: list[Defect] = []
    i = 0

    while i < len(pts):
        # Find start of a visible run
        if not pts[i].visible:
            i += 1
            continue

        last_visible_before = pts[i]

        # Advance to invisible run
        j = i + 1
        while j < len(pts) and pts[j].visible:
            last_visible_before = pts[j]
            j += 1

        if j >= len(pts):
            break

        invis_start = j

        # Advance through invisible run
        while j < len(pts) and not pts[j].visible:
            j += 1

        invis_end = j - 1
        gap_frames = invis_end - invis_start + 1

        if gap_frames < cfg.vanish_min_gap_frames:
            i = j
            continue

        if j >= len(pts):
            break

        # The element reappeared
        first_visible_after = pts[j]
        drift = _dist(last_visible_before.centroid, first_visible_after.centroid)

        if drift <= cfg.vanish_drift_px:
            severity = min(1.0, gap_frames / cfg.vanish_severity_cap_frames)
            t_start = pts[invis_start].t
            t_end = pts[invis_end].t
            frame_indices = [
                k for k, f in enumerate(frames) if t_start <= f.t <= t_end
            ][:4]

            defects.append(
                Defect(
                    type="vanish",
                    track_id=track.id,
                    label=track.label,
                    t_start=t_start,
                    t_end=t_end,
                    severity=round(severity, 4),
                    metric=float(gap_frames),
                    evidence=frame_indices,
                )
            )

        i = j

    return defects


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)
