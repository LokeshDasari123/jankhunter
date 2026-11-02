"""Command line entry points for capturing, detecting, repairing, and reporting."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import typer

from jankhunter.capture import capture, load_frames
from jankhunter.detect.run import detect_all
from jankhunter.fix.loop import FakeDiagnoser, Iteration, MuseSparkDiagnoser, run_fix_loop
from jankhunter.models import Defect, Frame, Scenario, Track
from jankhunter.report import write_report
from jankhunter.tracking.meta_sam import MetaSAMTracker
from jankhunter.tracking.mock import MockTracker

app = typer.Typer(help="Find temporal visual bugs in canvas and game-style web UIs.")


def _load_scenario(path: Path) -> Scenario:
    return Scenario.model_validate_json(path.read_text(encoding="utf-8"))


def _track(frames: list[Frame], scenario: Scenario, tracker: str) -> list[Track]:
    if tracker == "meta-sam":
        if not scenario.sam_prompts:
            raise typer.BadParameter("Scenario must include sam_prompts for Meta SAM 3.1.")
        return MetaSAMTracker().track(frames, scenario.sam_prompts)
    if not scenario.prompt_labels:
        raise typer.BadParameter("Scenario must include prompt_labels for MockTracker.")
    return MockTracker().track(frames, scenario.prompt_labels)


def _write_detection(out: Path, tracks: list[Track], defects: list[Defect], score: float) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "tracks.json").write_text(json.dumps([t.model_dump(mode="json") for t in tracks], indent=2), encoding="utf-8")
    (out / "defects.json").write_text(json.dumps({"score": score, "defects": [d.model_dump(mode="json") for d in defects]}, indent=2), encoding="utf-8")


@app.command("capture")
def capture_run(
    scenario: Path = typer.Argument(..., exists=True, readable=True),
    out: Path = typer.Option(Path("runs/capture"), "--out", help="Directory for frames and metadata."),
) -> None:
    """Record a browser scenario to timestamped frames."""
    frames = capture(_load_scenario(scenario), out)
    typer.echo(f"Captured {len(frames)} frames in {out}")


@app.command("detect")
def detect_run(
    scenario: Path = typer.Argument(..., exists=True, readable=True),
    frames_dir: Path = typer.Option(..., "--frames", exists=True, file_okay=False),
    out: Path = typer.Option(Path("runs/detect"), "--out"),
    tracker: str = typer.Option("mock", "--tracker", help="mock (fixture) or meta-sam (real visual tracking)."),
) -> None:
    """Run deterministic temporal defect detectors on a capture."""
    frames = load_frames(frames_dir)
    if tracker not in {"mock", "meta-sam"}:
        raise typer.BadParameter("--tracker must be 'mock' or 'meta-sam'.")
    tracks = _track(frames, _load_scenario(scenario), tracker)
    defects, score = detect_all(tracks, frames)
    _write_detection(out, tracks, defects, score)
    typer.echo(f"Found {len(defects)} defects (score {score:.3f}); details: {out / 'defects.json'}")


@app.command()
def fix(
    scenario: Path = typer.Argument(..., exists=True, readable=True),
    out: Path = typer.Option(Path("runs/fix"), "--out"),
    offline: bool = typer.Option(False, "--offline", help="Use the deterministic demo fixture patch."),
    max_iterations: int = typer.Option(1, min=1, max=3, help="Maximum model repair attempts (1–3)."),
) -> None:
    """Run the bounded patch, rebuild, re-record, and verify workflow."""
    root = Path.cwd().resolve()
    if __import__("subprocess").run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True).stdout.strip():
        raise typer.BadParameter("Fix loop requires a clean git worktree so rejected edits can be reverted safely. Commit or stash current changes first.")
    spec = _load_scenario(scenario)
    before_dir, after_dir = out / "before", out / "before"
    before_frames = capture(spec, before_dir)
    tracker = "mock" if offline else "meta-sam"
    before_tracks = _track(before_frames, spec, tracker)
    before_defects, before_score = detect_all(before_tracks, before_frames)
    _write_detection(out / "before", before_tracks, before_defects, before_score)

    latest: dict[str, object] = {}

    def evaluate():
        nonlocal after_dir
        serial = sum(1 for p in out.glob("after-try-*")) + 1
        after_dir = out / f"after-try-{serial}"
        frames = capture(spec, after_dir)
        tracks = _track(frames, spec, tracker)
        defects, score = detect_all(tracks, frames)
        latest.update(frames=frames, tracks=tracks, defects=defects, score=score)
        return defects, score

    diagnoser = FakeDiagnoser() if offline else MuseSparkDiagnoser()
    result = run_fix_loop(root, before_defects, before_score, diagnoser, evaluate,
                          max_iterations, evidence_frames=before_frames)
    after_frames = latest.get("frames", before_frames)
    after_tracks = latest.get("tracks", before_tracks)
    after_defects = latest.get("defects", before_defects)
    _write_detection(after_dir, after_tracks, after_defects, float(latest.get("score", before_score)))
    report = write_report(out / "report.html", before_defects, after_defects, before_frames,
                          after_frames, before_tracks, after_tracks, result.history)
    (out / "iterations.json").write_text(json.dumps([vars(item) for item in result.history], indent=2), encoding="utf-8")
    typer.echo(f"Fix {'accepted' if result.accepted else 'not accepted'}; report: {report}")
    if result.accepted:
        typer.echo(f"Review the proposed change on branch {result.branch}; commit it after review.")


@app.command()
def report(
    before: Path = typer.Option(..., "--before", exists=True, file_okay=False),
    after: Path = typer.Option(..., "--after", exists=True, file_okay=False),
    out: Path = typer.Option(Path("runs/report.html"), "--out"),
    history_file: Path | None = typer.Option(None, "--history", exists=True, readable=True),
) -> None:
    """Build a standalone HTML report from saved before and after runs."""
    before_frames, after_frames = load_frames(before), load_frames(after)
    before_defects = json.loads((before / "defects.json").read_text(encoding="utf-8"))["defects"]
    after_defects = json.loads((after / "defects.json").read_text(encoding="utf-8"))["defects"]
    before_tracks = json.loads((before / "tracks.json").read_text(encoding="utf-8"))
    after_tracks = json.loads((after / "tracks.json").read_text(encoding="utf-8"))
    history = (
        [Iteration(**item) for item in json.loads(history_file.read_text(encoding="utf-8"))]
        if history_file else None
    )
    write_report(out, [Defect.model_validate(d) for d in before_defects],
                 [Defect.model_validate(d) for d in after_defects], before_frames, after_frames,
                 [Track.model_validate(t) for t in before_tracks], [Track.model_validate(t) for t in after_tracks], history)
    typer.echo(f"Report written to {out}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app()
