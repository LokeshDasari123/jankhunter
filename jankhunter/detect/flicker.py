"""
jankhunter/detect/flicker.py
-----------------------------
Flicker detector.

Algorithm
---------
Slide a window of `flicker_window` consecutive TrackPoints across the track.
Count the number of times the `visible` boolean toggles within each window
(True→False or False→True).  If the toggle count ≥ flicker_toggle_threshold,
that window is flagged as flicker.

Adjacent flagged windows are merged into a single Defect.

Rationale: Legitimate hide/show transitions typically produce one toggle
(visible→invisible or invisible→visible).  Multiple rapid toggles indicate
element instability.
"""

from __future__ import annotations

from jankhunter.detect.config import DetectorConfig
from jankhunter.models import Defect, Frame, Track


def detect_flicker(
    track: Track,
    frames: list[Frame],
    config: DetectorConfig | None = None,
) -> list[Defect]:
    """
    Detect rapid visibility toggling in a Track.

    Returns:
        A list of Defect objects, one per contiguous flicker window.
    """
    cfg = config or DetectorConfig()
    pts = track.points  # already sorted by t

    if len(pts) < cfg.flicker_min_points:
        return []

    # Count toggles in each window
    flagged: list[bool] = [False] * len(pts)
    window = cfg.flicker_window
    threshold = cfg.flicker_toggle_threshold

    for i in range(len(pts) - window + 1):
        w = pts[i : i + window]
        toggles = sum(
            1 for j in range(1, len(w)) if w[j].visible != w[j - 1].visible
        )
        if toggles >= threshold:
            for k in range(i, i + window):
                flagged[k] = True

    if not any(flagged):
        return []

    # Merge contiguous flagged regions into defects
    defects: list[Defect] = []
    in_region = False
    region_start = 0

    for i, is_flagged in enumerate(flagged):
        if is_flagged and not in_region:
            in_region = True
            region_start = i
        elif not is_flagged and in_region:
            in_region = False
            defects.append(_make_defect(track, pts, frames, region_start, i - 1, cfg))

    if in_region:
        defects.append(_make_defect(track, pts, frames, region_start, len(pts) - 1, cfg))

    return defects


def _make_defect(track: Track, pts, frames: list[Frame], start: int, end: int, cfg: DetectorConfig) -> Defect:
    region = pts[start : end + 1]
    toggles = sum(1 for j in range(1, len(region)) if region[j].visible != region[j - 1].visible)
    severity = min(1.0, toggles / cfg.flicker_severity_cap_toggles)

    t_start = region[0].t
    t_end = region[-1].t
    frame_indices = [
        i for i, f in enumerate(frames) if t_start <= f.t <= t_end
    ][:6]

    return Defect(
        type="flicker",
        track_id=track.id,
        label=track.label,
        t_start=t_start,
        t_end=t_end,
        severity=round(severity, 4),
        metric=float(toggles),
        evidence=frame_indices,
    )
