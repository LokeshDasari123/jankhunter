"""
jankhunter/tracking/meta_sam.py
--------------------------------
MetaSAMTracker — Phase 2 stub.

⚠️  NOT IMPLEMENTED — this is a placeholder for the SAM 3.1 video tracker
    integration that will be completed in Phase 2.

TODO (Phase 2):
  - Obtain SAM 3.1 API access and confirm the correct endpoint/schema.
  - The API key must be read from the environment variable MODEL_API_KEY
    (never hard-coded or committed).
  - Implement the track() method:
      1. Upload frames (or a video) to the SAM 3.1 endpoint.
      2. Pass prompt labels as text or point prompts depending on the API.
      3. Poll or stream results.
      4. Convert the returned masks / bboxes to TrackPoint objects.
  - Handle pagination if the session has more frames than the API can process.
  - Add retry + exponential back-off for transient API errors.

References:
  - SAM 3.1 documentation: (link to be added in Phase 2)
  - Prompt format: unknown until API access is granted — DO NOT GUESS.
"""

from __future__ import annotations

from jankhunter.config import model_api_key
from jankhunter.models import Frame, Track
from jankhunter.tracking.base import Tracker


class MetaSAMTracker(Tracker):
    """
    Tracker backed by Meta SAM 3.1 video segmentation API.

    Phase 2 only — raises NotImplementedError until implemented.
    API key is read from the MODEL_API_KEY environment variable.
    """

    def __init__(self) -> None:
        self._api_key: str | None = model_api_key()

    def track(self, frames: list[Frame], prompts: list[str]) -> list[Track]:
        """
        Track elements using SAM 3.1.

        Raises:
            NotImplementedError: Always — Phase 2 not yet implemented.
        """
        raise NotImplementedError(
            "MetaSAMTracker is a Phase 2 feature and has not been implemented yet. "
            "See the TODO block in jankhunter/tracking/meta_sam.py for details. "
            "Use MockTracker for development and testing."
        )
