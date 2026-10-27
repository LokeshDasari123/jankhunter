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
