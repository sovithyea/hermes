"""TTS engine interface. Engines turn (text, voice, prosody) into mono float32 audio."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

SAMPLE_RATE = 24_000


@dataclass(frozen=True)
class Prosody:
    speed: float = 1.0
    gain_db: float = 0.0


# Engines without native emotion control approximate it with pace and loudness.
EMOTION_PROSODY: dict[str, Prosody] = {
    "neutral": Prosody(),
    "happy": Prosody(1.04, 0.5),
    "excited": Prosody(1.10, 1.5),
    "amused": Prosody(1.03),
    "teasing": Prosody(1.02),
    "sad": Prosody(0.90, -1.5),
    "pained": Prosody(0.92, -1.0),
    "tender": Prosody(0.93, -2.0),
    "whisper": Prosody(0.92, -7.0),
    "angry": Prosody(1.06, 2.5),
    "shouting": Prosody(1.08, 4.0),
    "fearful": Prosody(1.07, -1.0),
    "anxious": Prosody(1.06),
    "tense": Prosody(1.02),
    "surprised": Prosody(1.05, 1.0),
    "pleading": Prosody(0.97),
    "sarcastic": Prosody(0.97),
    "dry": Prosody(0.96),
    "cold": Prosody(0.94, -0.5),
}


class TTSEngine(Protocol):
    name: str

    def voices(self) -> list[str]: ...

    def synth(self, text: str, voice: str, speed: float = 1.0) -> np.ndarray: ...
