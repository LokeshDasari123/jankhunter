"""A bounded, reversible patch-and-verify loop."""

from __future__ import annotations

import base64
import json
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from PIL import Image

from jankhunter.config import model_api_key
from jankhunter.models import Defect, Frame


@dataclass(frozen=True)
class EditBlock:
    file: str
    search: str
    replace: str


@dataclass(frozen=True)
class Diagnosis:
    summary: str
    edits: tuple[EditBlock, ...]


class Diagnoser(Protocol):
    def diagnose(
        self, defects: list[Defect], repo_root: Path, iteration: int,
        evidence_frames: list[Frame] | None = None,
    ) -> Diagnosis: ...


class MuseSparkDiagnoser:
    """Muse Spark Diagnoser using Meta Model API's documented Messages endpoint."""

    def __init__(self, model: str = "muse-spark-1.3", api_key: str | None = None) -> None:
        self.model = model
        self.api_key = api_key or model_api_key()

    def diagnose(
        self, defects: list[Defect], repo_root: Path, iteration: int,
        evidence_frames: list[Frame] | None = None,
    ) -> Diagnosis:
        if not self.api_key:
            raise RuntimeError(
                "Set MODEL_API_KEY in the environment or the repository's ignored .env file."
            )
        app_source = repo_root / "demo" / "buggy" / "app.js"
        context = {
            "defects": [defect.model_dump(mode="json") for defect in defects],
            "source": {str(app_source.relative_to(repo_root)): app_source.read_text(encoding="utf-8")},
            "iteration": iteration,
        }
        schema = {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "edits": {"type": "array", "items": {
                    "type": "object", "properties": {
                        "file": {"type": "string"}, "search": {"type": "string"},
                        "replace": {"type": "string"},
                    }, "required": ["file", "search", "replace"], "additionalProperties": False,
                }},
            }, "required": ["summary", "edits"], "additionalProperties": False,
        }
        candidates = sorted({index for defect in defects for index in defect.evidence})
        selected_indices = candidates if len(candidates) <= 2 else [candidates[0], candidates[-1]]
        frames_by_index = evidence_frames or []
        content: list[dict[str, object]] = [{"type": "text", "text": json.dumps(context)}]
        for index in selected_indices:
            if 0 <= index < len(frames_by_index):
                frame = frames_by_index[index]
                if frame.path.is_file():
                    with Image.open(frame.path) as image:
                        image.thumbnail((768, 768), Image.Resampling.LANCZOS)
                        buffer = BytesIO()
                        image.convert("RGB").save(buffer, format="JPEG", quality=65, optimize=True)
                    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
                    content.append({"type": "image", "source": {
                        "type": "base64", "media_type": "image/jpeg", "data": encoded,
                    }})
        body = json.dumps({
            "model": self.model,
            "max_tokens": 1200,
            "system": (
                "Diagnose temporal visual bugs from deterministic detector evidence and source. "
                "Return the smallest safe exact-text edits as JSON matching the requested schema. "
                "Only edit demo/buggy/app.js. Do not invent evidence."
            ),
            "messages": [{"role": "user", "content": content}],
            "output_config": {"format": {"type": "json_schema", "schema": schema}},
        }).encode()
        request = urllib.request.Request(
            "https://api.meta.ai/v1/messages", data=body,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Meta Model API request failed (HTTP {exc.code}).") from exc
        answer = "".join(block.get("text", "") for block in payload.get("content", []) if block.get("type") == "text")
        try:
            data = json.loads(answer)
            return Diagnosis(data["summary"], tuple(EditBlock(**edit) for edit in data["edits"]))
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Muse Spark response did not match the expected edit format.") from exc


class FakeDiagnoser:
    """Deterministic offline diagnoser used by tests and the local demo."""

    def __init__(self, edits: tuple[EditBlock, ...] | None = None) -> None:
        self.edits = edits or (
            EditBlock(
                "demo/buggy/app.js",
                "sprite.x = Math.floor(sprite.x + 3);   // WRONG: ignores dt and vx\n  sprite.y = Math.floor(sprite.y + 2);   // WRONG: ignores dt and vy",
                "sprite.x += sprite.vx * dt;\n  sprite.y += sprite.vy * dt;",
            ),
            EditBlock(
                "demo/buggy/app.js",
                "  // BUG 1 — synchronous work stalls the main thread every 45 frames.\n"
                "  if (frameCount % 45 === 0) {\n"
                "    const started = performance.now();\n"
                "    while (performance.now() - started < 45) { /* simulate an expensive update */ }\n"
                "  }\n\n",
                "",
            ),
        )

    def diagnose(
        self, defects: list[Defect], repo_root: Path, iteration: int,
        evidence_frames: list[Frame] | None = None,
    ) -> Diagnosis:
        return Diagnosis("Offline fixture patch for the demo's uneven motion and main-thread stalls.", self.edits)


@dataclass
class Iteration:
    number: int
    summary: str
    before_score: float
    after_score: float | None
    defect_types_before: list[str]
    defect_types_after: list[str]
    accepted: bool
    patch: str
    error: str | None = None


@dataclass
class LoopResult:
    accepted: bool
    branch: str
    history: list[Iteration]


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, text=True, capture_output=True)


def apply_edits(root: Path, edits: tuple[EditBlock, ...]) -> str:
    """Apply exact search/replace edits after validating each file is repo-local."""
    changed: list[Path] = []
    for edit in edits:
        path = (root / edit.file).resolve()
        if root.resolve() not in path.parents:
            raise ValueError(f"Edit path escapes repository: {edit.file}")
        if not path.is_file() or not edit.search:
            raise ValueError(f"Edit must target a file and include non-empty search text: {edit.file}")
        source = path.read_text(encoding="utf-8")
        if source.count(edit.search) != 1:
            raise ValueError(f"Expected exactly one match in {edit.file}; found {source.count(edit.search)}")
        path.write_text(source.replace(edit.search, edit.replace, 1), encoding="utf-8")
        changed.append(path)
    diff = _run(root, "diff", "--", *(str(path.relative_to(root)) for path in changed))
    return diff.stdout


def run_fix_loop(
    repo_root: Path,
    defects: list[Defect],
    score: float,
    diagnoser: Diagnoser,
    evaluate,
    max_iterations: int = 3,
    rebuild_command: tuple[str, ...] | None = None,
    evidence_frames: list[Frame] | None = None,
) -> LoopResult:
    """Create a fix branch, evaluate proposed edits, and restore rejected changes."""
    root = repo_root.resolve()
    if not (root / ".git").exists():
        raise RuntimeError(f"Not a git repository: {root}")
    if not defects:
        return LoopResult(False, "", [])
    status = _run(root, "status", "--porcelain")
    if status.stdout.strip():
        raise RuntimeError("Fix loop requires a clean git worktree so rejected edits can be reverted safely.")
    branch = f"jankhunter/fix-{uuid4().hex[:10]}"
    created = _run(root, "switch", "-c", branch)
    if created.returncode:
        raise RuntimeError(created.stderr.strip())
    history: list[Iteration] = []
    current_score = score
    current_types = {defect.type for defect in defects}
    current_defects = defects
    for number in range(1, max_iterations + 1):
        try:
            diagnosis = diagnoser.diagnose(current_defects, root, number, evidence_frames)
            if not diagnosis.edits:
                history.append(Iteration(number, diagnosis.summary, current_score, None,
                                         sorted(current_types), [], False, "", "Diagnoser returned no edits"))
                break
            patch = apply_edits(root, diagnosis.edits)
            if rebuild_command:
                rebuilt = subprocess.run(rebuild_command, cwd=root, text=True, capture_output=True)
                if rebuilt.returncode:
                    raise RuntimeError(f"Rebuild failed: {rebuilt.stderr[-1000:]}")
            after_defects, after_score = evaluate()
            after_types = {defect.type for defect in after_defects}
            accepted = after_score < current_score and after_types.issubset(current_types)
            history.append(Iteration(number, diagnosis.summary, current_score, after_score,
                                     sorted(current_types), sorted(after_types), accepted, patch))
            if accepted:
                current_score, current_types, current_defects = after_score, after_types, after_defects
                break
            _run(root, "restore", "--worktree", "--staged", ".")
        except Exception as exc:
            _run(root, "restore", "--worktree", "--staged", ".")
            history.append(Iteration(number, "Patch attempt failed", current_score, None,
                                     sorted(current_types), [], False, "", str(exc)))
    accepted = bool(history and history[-1].accepted)
    if not accepted:
        _run(root, "switch", "-")
        _run(root, "branch", "-D", branch)
    return LoopResult(accepted, branch if accepted else "", history)
