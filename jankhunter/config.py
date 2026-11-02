"""Local configuration helpers."""

from __future__ import annotations

import os
from pathlib import Path


def model_api_key(env_file: Path | None = None) -> str | None:
    """Read MODEL_API_KEY from the environment or a local, ignored .env file.

    Existing process environment values take precedence. This deliberately reads
    only the one expected secret and never logs or writes it back to disk.
    """
    value = os.environ.get("MODEL_API_KEY", "").strip()
    if value:
        return value

    path = env_file or Path.cwd() / ".env"
    if not path.is_file():
        return None

    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, value = line.partition("=")
        if not separator or name.strip() != "MODEL_API_KEY":
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        return value or None
    return None
