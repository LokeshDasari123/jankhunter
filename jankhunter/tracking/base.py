"""
jankhunter/tracking/base.py
---------------------------
Abstract base class for visual element trackers.

All trackers take a list of captured frames and a list of human-readable
element labels ("prompts") and return a list of Track objects — one per
tracked element.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from jankhunter.models import Frame, Track


class Tracker(ABC):
    """
    Abstract tracker interface.

    Implementations:
      - MockTracker  (tracking/mock.py)   — reads a ground-truth sidecar JSON.
                                            DEV/TEST only; requires sidecar from demo app.
      - MetaSAMTracker (tracking/meta_sam.py) — Phase 2; raises NotImplementedError.
    """

    @abstractmethod
    def track(self, frames: list[Frame], prompts: list[str]) -> list[Track]:
        """
        Track visual elements across all frames.

        Args:
            frames:  Ordered list of captured Frame objects.
            prompts: Human-readable element labels to track (e.g. ["sprite", "hud_bar"]).

        Returns:
            One Track per prompt label (or fewer if an element is never visible).
        """
        ...
