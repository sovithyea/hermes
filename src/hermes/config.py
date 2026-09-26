"""Settings from environment variables or a .env file in the project root (git-ignored).

    ELEVENLABS_API_KEY=...        enables ElevenLabs voices
    ELEVENLABS_MODEL=eleven_v3    optional; v3 understands [whispers]-style performance tags
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for row in env.read_text().splitlines():
        row = row.strip()
        if row and not row.startswith("#") and "=" in row:
            key, value = row.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv()


def elevenlabs_key() -> str | None:
    return os.environ.get("ELEVENLABS_API_KEY") or None


def elevenlabs_model() -> str:
    return os.environ.get("ELEVENLABS_MODEL", "eleven_v3")
