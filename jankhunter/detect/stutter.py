"""
jankhunter/detect/stutter.py
------------------------------
Stutter detector.

Algorithm
---------
Two independent signals:

Signal A — Timestamp gap:
  Consecutive frames whose timestamp difference exceeds `stutter_gap_s` while
  the element's centroid velocity exceeds `stutter_motion_px_s` px/s are flagged.
  (A large gap while moving means dropped frames during motion.)

Signal B — Duplicate frames (pixel hash):
  If the capture module has recorded frames, consecutive identical-looking frames
  while centroid velocity > threshold indicate the renderer stalled.
  NOTE: Signal B is only active when frames are provided and frame files exist.
  It hashes the decoded grayscale frame so small moving elements are not lost
  to thumbnail downsampling.

Each qualifying event becomes a separate Defect. Events from both signals are
merged by proximity before returning.
"""

from __future__ import annotations

import hashlib
import logging

import cv2
import numpy as np

from jankhunter.detect.config import DetectorConfig
from jankhunter.models import Defect, Frame, Track

log = logging.getLogger(__name__)


def detect_stutter(
    track: Track,
    frames: list[Frame],
    config: DetectorConfig | None = None,
) -> list[Defect]:
    """
    Detect timestamp gaps and/or duplicate frames during motion.

    Returns:
        A list of Defect objects, one per stutter event.
    """
    cfg = config or DetectorConfig()
    pts = [p for p in track.points if p.visible]

    if len(pts) < cfg.stutter_min_points:
        return []

    ts = np.array([p.t for p in pts], dtype=float)
    cx = np.array([p.centroid[0] for p in pts], dtype=float)
    cy = np.array([p.centroid[1] for p in pts], dtype=float)

    dt = np.diff(ts)
    dist = np.sqrt(np.diff(cx) ** 2 + np.diff(cy) ** 2)
    # Velocity in px/s (guard against zero dt)
    vel = np.where(dt > 0, dist / dt, 0.0)

    defects: list[Defect] = []

    # Signal A: timestamp gap while moving
    for i in range(len(dt)):
        if dt[i] > cfg.stutter_gap_s and vel[i] > cfg.stutter_motion_px_s:
            severity = min(1.0, dt[i] / cfg.stutter_severity_cap_s)
            t_gap_start = float(ts[i])
            t_gap_end = float(ts[i + 1])
            frame_indices = [
                j for j, f in enumerate(frames) if t_gap_start <= f.t <= t_gap_end
            ][:3]
            defects.append(
                Defect(
                    type="stutter",
                    track_id=track.id,
                    label=track.label,
                    t_start=t_gap_start,
                    t_end=t_gap_end,
                    severity=round(severity, 4),
                    metric=round(float(dt[i]), 6),
                    evidence=frame_indices,
                )
            )

    # Signal B: duplicate frame hashes while moving (best-effort)
    if frames:
        defects.extend(_duplicate_frame_defects(track, ts, vel, frames, cfg))

    # Deduplicate: remove B-signal events that overlap with an A-signal event
    defects = _deduplicate(defects)
    return defects


def _duplicate_frame_defects(
    track: Track,
    ts: np.ndarray,
    vel: np.ndarray,
    frames: list[Frame],
    cfg: DetectorConfig,
) -> list[Defect]:
    """Detect duplicate frame content (Signal B)."""
    hashes: list[str | None] = []
    for f in frames:
        try:
            if not f.path.is_file():
                hashes.append(None)
                continue
            image = cv2.imread(str(f.path), cv2.IMREAD_GRAYSCALE)
            if image is None:
                hashes.append(None)
                continue
            h = hashlib.sha256(image.tobytes()).hexdigest()
            hashes.append(h)
        except OSError:
            hashes.append(None)

    defects: list[Defect] = []

    for i in range(1, len(frames)):
        if hashes[i] is None or hashes[i - 1] is None:
            continue
        if hashes[i] != hashes[i - 1]:
            continue  # not a duplicate

        f_t = frames[i].t
        # Only flag if this is during tracked motion
        close = [
            j for j in range(len(ts) - 1)
            if abs(ts[j + 1] - f_t) < 0.1 and vel[j] > cfg.stutter_motion_px_s
        ]
        if not close:
            continue

        severity = 0.3  # moderate default for duplicate frames
        defects.append(
            Defect(
                type="stutter",
                track_id=track.id,
                label=track.label,
                t_start=frames[i - 1].t,
                t_end=frames[i].t,
                severity=severity,
                metric=0.0,
                evidence=[i - 1, i],
            )
        )

    return defects


def _deduplicate(defects: list[Defect]) -> list[Defect]:
    """Remove defects whose time windows fully overlap with an earlier one."""
    kept: list[Defect] = []
    for d in defects:
        if not any(
            k.t_start <= d.t_start and k.t_end >= d.t_end and k is not d
            for k in kept
        ):
            kept.append(d)
    return kept
