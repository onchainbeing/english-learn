from __future__ import annotations

import subprocess
from pathlib import Path


def get_audio_duration_seconds(path: Path) -> float | None:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

    text = result.stdout.strip()
    if not text:
        return None

    try:
        return float(text)
    except ValueError:
        return None
