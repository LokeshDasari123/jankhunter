# JankHunter — Dev Log

## 2026-10-27

### Scaffold
- Initialized repo with `pyproject.toml` (hatchling build, all deps listed).
- Chose Typer for CLI (richer help than argparse, click-compatible).
- Chose Pydantic v2 for models (strict validation, fast serialization).
- Decided to use CDP `Page.startScreencast` as primary capture method with Playwright `record_video` as fallback. Reason: CDP gives accurate per-frame timestamps, which are essential for temporal detectors.
- **Honest fps note**: CDP screencast yields 10–24 fps depending on browser load and system. Anything below 15 fps reduces jitter/stutter detection accuracy. Documented in README.
- MockTracker is a dev/test convenience only. It reads a ground-truth sidecar JSON written by the demo app. Any real deployment MUST use a real tracker (Phase 2: SAM 3.1).
- SAM 3.1 integration left as a `NotImplementedError` stub — we do not guess API schemas.

### Ambiguity resolved
- `Defect.evidence`: chose `list[int]` (frame indices) rather than `list[Path]` to keep models serialization-friendly; frames are looked up by index into the `list[Frame]` returned by capture.
- `EditBlock` safety: patch apply rejects any `file` path that doesn't resolve inside the repo root (prevent path traversal).
- Rebuild command: configurable string; for the demo static app it is effectively empty (`""`).

## 2026-11-02

### Detection, repair, and reporting
- Completed five pure detection passes and synthetic clean/defect coverage. Duplicate-frame checks compare resized grayscale image content and preserve the affected track identity.
- Added a patch-and-verify loop with exact unique search/replace edits, repo-local path checks, per-try scores, and revert on rejection. The CLI requires a clean worktree before creating a fix branch so rejected edits cannot erase unrelated user changes.
- The loop accepts an optional rebuild command; this vanilla-JS demo has no build step, so the default is intentionally empty.
- Added a deterministic offline diagnoser to exercise the loop without credentials and a Muse Spark Diagnoser using Meta's current Messages API contract (`muse-spark-1.3`, `MODEL_API_KEY`). API schema was verified against official docs rather than guessed.
- Added a self-contained HTML report with an embedded trajectory plot, evidence frames, defects, patch diff, and iteration history.
- Demo app now retains per-frame sidecar samples; Playwright context records video for the documented ffmpeg fallback.
- **Honest limitation:** SAM video tracking remains unimplemented pending a verified API schema. This release's complete demo uses the sidecar mock and should be presented as a prototype, not production-ready perception.
- **Ambiguity resolved:** `fix` compares the weighted detector severity and defect-type set across recordings of the same scenario. This is a regression gate, not proof that the patch is correct for all interactions.
- Added local `.env` loading for `MODEL_API_KEY`; the ignored file is never logged. To limit request cost, the Muse call has a 1,200-token output cap and sends at most two resized evidence frames plus only the source file it may edit.

### Meta tracker and packaging
- Implemented the documented SAM 3.1 Responses API video path with `meta-sam-parser`; a local video writer samples 50–120 captured frames, maps returned boxes back to capture timestamps, and requests server-side deletion of the uploaded clip after processing.
- Added `detect --tracker meta-sam`; ordinary capture/detect and no-key tests continue to use `MockTracker` unless selected explicitly. The online fix loop uses SAM; `--offline` stays local.
- Added `.env.example` and a plain `requirements.txt` for Python 3.11 virtual environments. Rewrote README to distinguish measured behavior from unverified claims and to document capture-rate and model limits.
- Added offline tests for SAM frame limits, MP4 creation, and parsed box-to-track conversion. No model API request was made while implementing these changes.
- **Remaining limitation:** SAM returns sampled observations; temporal events between samples can be missed. The live account/API path still needs one deliberate end-to-end validation before submission.
- **Correction:** SAM API schema is now implemented against Meta's published documentation. The earlier entry above accurately records the prior state, not the current repository state.
