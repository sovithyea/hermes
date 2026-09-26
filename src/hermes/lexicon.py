"""Pronunciation overrides: {"Xaden": "Zayden"} rewrites the word before it is spoken.

Respelling is engine-agnostic. Kokoro also accepts inline phonemes, e.g.
{"Basgiath": "[Basgiath](/bˈæsɡiəθ/)"}.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


class Lexicon:
    def __init__(self, entries: dict[str, str] | None = None):
        self.entries = dict(entries or {})
        self._re = None
        if self.entries:
            words = sorted(self.entries, key=len, reverse=True)
            self._re = re.compile(r"\b(" + "|".join(map(re.escape, words)) + r")(?=\b|’s|'s)")

    @classmethod
    def load(cls, path: Path) -> "Lexicon":
        return cls(json.loads(path.read_text(encoding="utf-8")) if path.exists() else {})

    def apply(self, text: str) -> str:
        if not self._re:
            return text
        return self._re.sub(lambda m: self.entries[m.group(1)], text)
