from __future__ import annotations

import json
import subprocess
from io import BytesIO
from pathlib import Path

from jankhunter.fix.loop import EditBlock, FakeDiagnoser, MuseSparkDiagnoser, run_fix_loop
from jankhunter.models import Defect, Frame


def _repo(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    (tmp_path / "demo/buggy").mkdir(parents=True)
    (tmp_path / "demo/buggy/app.js").write_text("const speed = 3;\n", encoding="utf-8")
    return tmp_path


def _fake_git(monkeypatch):
    from jankhunter.fix import loop

    def run(root, *args):
        output = "mock diff" if args[:2] == ("diff", "--") else ""
        if args[:1] == ("restore",):
            (root / "demo/buggy/app.js").write_text("const speed = 3;\n", encoding="utf-8")
        return subprocess.CompletedProcess(["git", *args], 0, output, "")

    monkeypatch.setattr(loop, "_run", run)


def _defect() -> Defect:
    return Defect(type="jitter", track_id="sprite", label="sprite", t_start=0, t_end=1,
                  severity=0.5, metric=3.0)


def test_loop_accepts_fake_diagnoser_patch(tmp_path: Path, monkeypatch):
    root = _repo(tmp_path)
    _fake_git(monkeypatch)

    def evaluate():
        assert "speed = 60" in (root / "demo/buggy/app.js").read_text(encoding="utf-8")
        return [], 0.0

    result = run_fix_loop(root, [_defect()], 0.5, FakeDiagnoser((
        EditBlock("demo/buggy/app.js", "speed = 3", "speed = 60"),
    )), evaluate)
    assert result.accepted
    assert result.branch.startswith("jankhunter/fix-")
    assert "speed = 60" in (root / "demo/buggy/app.js").read_text(encoding="utf-8")


def test_loop_reverts_patch_when_score_does_not_improve(tmp_path: Path, monkeypatch):
    root = _repo(tmp_path)
    _fake_git(monkeypatch)

    def evaluate():
        return [_defect()], 0.5

    result = run_fix_loop(root, [_defect()], 0.5, FakeDiagnoser((
        EditBlock("demo/buggy/app.js", "speed = 3", "speed = 60"),
    )), evaluate, max_iterations=1)
    assert not result.accepted
    assert "speed = 3" in (root / "demo/buggy/app.js").read_text(encoding="utf-8")
    assert not result.branch


def test_edit_cannot_escape_repo(tmp_path: Path, monkeypatch):
    from jankhunter.fix.loop import apply_edits

    root = _repo(tmp_path)
    _fake_git(monkeypatch)
    try:
        apply_edits(root, (EditBlock("../outside.txt", "x", "y"),))
    except ValueError as exc:
        assert "escapes repository" in str(exc)
    else:
        raise AssertionError("path traversal edit was accepted")


def test_muse_request_includes_defect_evidence_images(tmp_path: Path, monkeypatch):
    from jankhunter.fix import loop

    frame_path = tmp_path / "evidence.jpg"
    frame_path.write_bytes(b"tiny-test-image")
    defect = _defect().model_copy(update={"evidence": [0]})
    response_body = json.dumps({
        "content": [{"type": "text", "text": json.dumps({"summary": "Observed", "edits": []})}],
    }).encode()
    observed = {}

    def fake_urlopen(request, timeout):
        observed["request"] = json.loads(request.data)
        return BytesIO(response_body)

    monkeypatch.setattr(loop.urllib.request, "urlopen", fake_urlopen)
    result = MuseSparkDiagnoser(api_key="unit-test").diagnose(
        [defect], tmp_path, 1, [Frame(t=0.0, path=frame_path)],
    )
    blocks = observed["request"]["messages"][0]["content"]
    assert result.summary == "Observed"
    assert blocks[1]["type"] == "image"
    assert blocks[1]["source"]["media_type"] == "image/jpeg"
