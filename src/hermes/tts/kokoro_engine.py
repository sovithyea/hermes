"""Kokoro-82M: free, local, Apache-licensed. ~19x realtime on Apple Silicon GPU."""

from __future__ import annotations

import os
import warnings

import numpy as np

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
warnings.filterwarnings("ignore", module="torch")

REPO = "hexgrad/Kokoro-82M"

# Ordered best-first (per the model card's quality grades) so major characters get the best voices.
FEMALE_VOICES = [
    "af_heart", "af_bella", "af_nicole", "bf_emma", "af_aoede", "af_kore", "af_sarah",
    "bf_isabella", "af_nova", "af_sky", "bf_alice", "bf_lily", "af_alloy", "af_jessica", "af_river",
]
MALE_VOICES = [
    "am_fenrir", "am_michael", "am_puck", "bm_george", "bm_fable", "am_echo", "am_eric",
    "am_liam", "am_onyx", "bm_lewis", "bm_daniel", "am_adam",
]


class KokoroEngine:
    name = "kokoro"

    def __init__(self, device: str | None = None):
        import torch

        self.device = device or ("mps" if torch.backends.mps.is_available() else "cpu")
        self._pipelines: dict[str, object] = {}

    def voices(self) -> list[str]:
        return FEMALE_VOICES + MALE_VOICES

    def _pipeline(self, voice: str):
        lang = voice[0]  # 'a' = American English, 'b' = British English
        if lang not in self._pipelines:
            from kokoro import KPipeline

            self._pipelines[lang] = KPipeline(lang_code=lang, repo_id=REPO, device=self.device)
        return self._pipelines[lang]

    def synth(self, text: str, voice: str, speed: float = 1.0) -> np.ndarray:
        chunks = [audio.numpy() for _, _, audio in self._pipeline(voice)(text, voice=voice, speed=speed)
                  if audio is not None]
        return np.concatenate(chunks).astype(np.float32) if chunks else np.zeros(0, np.float32)
