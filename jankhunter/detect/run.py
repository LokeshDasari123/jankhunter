"""
jankhunter/detect/run.py
-------------------------
Aggregator: runs all detectors over a list of Tracks and returns all Defects,
together with a total severity score.
"""

from __future__ import annotations

import logging

from jankhunter.detect.config import DetectorConfig
from jankhunter.detect.flicker import detect_flicker
from jankhunter.detect.jitter import detect_jitter
from jankhunter.detect.layout_jump import detect_layout_jump
from jankhunter.detect.stutter import detect_stutter
from jankhunter.detect.vanish import detect_vanish
from jankhunter.models import Defect, Frame, Track

log = logging.getLogger(__name__)


def detect_all(
    tracks: list[Track],
    frames: list[Frame],
    config: DetectorConfig | None = None,
) -> tuple[list[Defect], float]:
    """
    Run all detectors on every track.

    Args:
        tracks:  List of Track objects from the tracker.
        frames:  Captured frames (used for evidence index resolution).
        config:  Detector configuration.

    Returns:
        (defects, total_severity) where total_severity is a weighted aggregate
        in [0, 1] of all individual defect severities.
    """
    cfg = config or DetectorConfig()
    defects: list[Defect] = []

    for track in tracks:
        log.debug("Running detectors on track '%s' (%d points)", track.label, len(track.points))
        defects.extend(detect_jitter(track, frames, cfg))
        defects.extend(detect_layout_jump(track, frames, cfg))
        defects.extend(detect_flicker(track, frames, cfg))
        defects.extend(detect_vanish(track, frames, cfg))
        defects.extend(detect_stutter(track, frames, cfg))

    log.info("Detected %d defects across %d tracks", len(defects), len(tracks))
    total_severity = _aggregate_severity(defects, cfg)
    return defects, total_severity


def _aggregate_severity(defects: list[Defect], cfg: DetectorConfig) -> float:
    """
    Weighted aggregate severity.

    For each defect type, take the max severity across all defects of that type,
    multiply by the configured weight, then normalise by the total weight.
    """
    if not defects:
        return 0.0

    weights = cfg.severity_weights
    total_weight = sum(weights.values())
    if total_weight == 0:
        return 0.0

    by_type: dict[str, float] = {}
    for d in defects:
        by_type[d.type] = max(by_type.get(d.type, 0.0), d.severity)

    weighted_sum = sum(by_type.get(t, 0.0) * w for t, w in weights.items())
    return round(min(1.0, weighted_sum / total_weight), 4)
