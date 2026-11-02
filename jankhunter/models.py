"""
jankhunter/models.py
--------------------
All shared Pydantic v2 data models for JankHunter.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Frame
# ---------------------------------------------------------------------------


class Frame(BaseModel):
    """A single captured frame from a scenario recording."""

    t: float = Field(..., description="Timestamp in seconds from start of recording")
    path: Path = Field(..., description="Absolute path to the saved JPEG/PNG frame file")

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# Track primitives
# ---------------------------------------------------------------------------


class TrackPoint(BaseModel):
    """The state of a tracked element at one frame."""

    t: float = Field(..., description="Timestamp in seconds")
    bbox: tuple[int, int, int, int] = Field(
        ..., description="Bounding box (x, y, w, h) in pixels"
    )
    centroid: tuple[float, float] = Field(..., description="(cx, cy) centre in pixels")
    area: float = Field(..., ge=0.0, description="Area of bounding box in pixels²")
    visible: bool = Field(..., description="Whether the element was visible in this frame")

    model_config = {"frozen": True}


class Track(BaseModel):
    """A persistent visual element tracked across frames."""

    id: str = Field(..., description="Unique track identifier (e.g. 'sprite_0')")
    label: str = Field(..., description="Human-readable label (e.g. 'Player Sprite')")
    points: list[TrackPoint] = Field(default_factory=list)

    @field_validator("points")
    @classmethod
    def _points_sorted(cls, v: list[TrackPoint]) -> list[TrackPoint]:
        """Ensure track points are in ascending timestamp order."""
        return sorted(v, key=lambda p: p.t)


# ---------------------------------------------------------------------------
# Defect
# ---------------------------------------------------------------------------

DefectType = Literal["jitter", "layout_jump", "flicker", "vanish", "stutter"]


class Defect(BaseModel):
    """A detected visual defect in a track."""

    type: DefectType
    track_id: str = Field(..., description="ID of the affected Track")
    label: str = Field(..., description="Human-readable label copied from the Track")
    t_start: float = Field(..., description="Start timestamp of the defect window (seconds)")
    t_end: float = Field(..., description="End timestamp of the defect window (seconds)")
    severity: float = Field(
        ..., ge=0.0, le=1.0, description="Normalised severity score in [0, 1]"
    )
    metric: float = Field(
        ..., description="Raw detector metric (units depend on defect type)"
    )
    evidence: list[int] = Field(
        default_factory=list,
        description="Frame indices (into the captured frames list) most relevant to this defect",
    )


# ---------------------------------------------------------------------------
# Scenario / Actions
# ---------------------------------------------------------------------------


class WaitAction(BaseModel):
    type: Literal["wait"] = "wait"
    duration: float = Field(..., gt=0.0, description="Duration in seconds")


class ClickAction(BaseModel):
    type: Literal["click"] = "click"
    x: float
    y: float


class KeyAction(BaseModel):
    type: Literal["key"] = "key"
    key: str = Field(..., description="Key name as understood by Playwright, e.g. 'Escape'")


class MouseMoveAction(BaseModel):
    type: Literal["mouse_move"] = "mouse_move"
    x: float
    y: float
    steps: int = Field(default=10, description="Number of intermediate mouse-move steps")


# Discriminated union of all action types
Action = WaitAction | ClickAction | KeyAction | MouseMoveAction


class Scenario(BaseModel):
    """Describes a browser scenario for JankHunter to record and analyse."""

    url: str = Field(..., description="URL to navigate to")
    viewport: dict[str, int] = Field(
        default_factory=lambda: {"width": 1280, "height": 720}
    )
    actions: list[Action] = Field(
        default_factory=list,
        description="Ordered list of actions to perform after page load",
    )
    duration: float = Field(
        ..., gt=0.0, description="Total recording duration in seconds"
    )
    prompt_labels: list[str] = Field(
        default_factory=list,
        description="Human-readable element labels to pass to the tracker as prompts",
    )
    sam_prompts: list[str] = Field(
        default_factory=list,
        description="Short SAM noun phrases; each phrase triggers one video request",
    )
