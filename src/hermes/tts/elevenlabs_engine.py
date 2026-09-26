"""ElevenLabs text-to-speech over its REST API.

Unlike Kokoro, ElevenLabs can act: with the v3 model, a leading tag such as [whispers] or
[angry] changes the delivery, so emotions are sent as tags instead of faked with speed/volume.
Billing is per character, so only characters explicitly switched to ElevenLabs use it.
"""

from __future__ import annotations

import logging
import time

import httpx
import numpy as np

from .base import SAMPLE_RATE

log = logging.getLogger(__name__)

API = "https://api.elevenlabs.io"

# Director emotion -> v3 performance tag. Neutral lines get no tag.
EMOTION_TAGS = {
    "happy": "[happily]", "excited": "[excited]", "amused": "[amused]", "teasing": "[playfully]",
    "sad": "[sad]", "pained": "[pained]", "tender": "[softly]", "whisper": "[whispers]",
    "angry": "[angry]", "shouting": "[shouting]", "fearful": "[scared]", "anxious": "[nervously]",
    "tense": "[tense]", "surprised": "[surprised]", "pleading": "[pleading]",
    "sarcastic": "[sarcastic]", "dry": "[deadpan]", "cold": "[coldly]",
}


class ElevenLabsError(RuntimeError):
    pass


class ElevenLabsEngine:
    name = "elevenlabs"
    native_emotion = True

    def __init__(self, api_key: str, model: str = "eleven_v3", client: httpx.Client | None = None):
        self.model = model
        self.client = client or httpx.Client(base_url=API, timeout=120)
        self.client.headers["xi-api-key"] = api_key
        self._voices: list[dict] | None = None

    # --- voices -------------------------------------------------------------

    def voice_list(self) -> list[dict]:
        """[{id, name, gender, age, accent, description}] for voices usable on this account."""
        if self._voices is None:
            data = self._get("/v1/voices")
            self._voices = [{
                "id": v["voice_id"], "name": v["name"],
                "gender": (v.get("labels") or {}).get("gender", ""),
                "age": (v.get("labels") or {}).get("age", ""),
                "accent": (v.get("labels") or {}).get("accent", ""),
                "description": (v.get("labels") or {}).get("description") or v.get("description") or "",
            } for v in data.get("voices", [])]
        return self._voices

    def voices(self) -> list[str]:
        return [v["id"] for v in self.voice_list()]

    def pick_voice(self, gender: str, taken: set[str]) -> str | None:
        """A voice matching the character's gender, preferring ones no one else uses."""
        pool = [v for v in self.voice_list() if v["gender"] == gender] or self.voice_list()
        free = [v for v in pool if v["id"] not in taken]
        return (free or pool)[0]["id"] if pool else None

    # --- speech -------------------------------------------------------------

    def tagged(self, text: str, emotion: str) -> str:
        if not self.model.startswith("eleven_v3"):
            return text  # older models would read the tag aloud
        tag = EMOTION_TAGS.get(emotion)
        return f"{tag} {text}" if tag else text

    def synth(self, text: str, voice: str, speed: float = 1.0, emotion: str = "neutral") -> np.ndarray:
        body = {"text": self.tagged(text, emotion), "model_id": self.model}
        for attempt in range(3):
            resp = self.client.post(f"/v1/text-to-speech/{voice}", params={"output_format": f"pcm_{SAMPLE_RATE}"},
                                    json=body)
            if resp.status_code == 429 and attempt < 2:  # rate limited: back off and retry
                time.sleep(2 * (attempt + 1))
                continue
            self._raise_for(resp)
            pcm = np.frombuffer(resp.content, dtype="<i2")
            return (pcm.astype(np.float32) / 32768.0)
        raise ElevenLabsError("ElevenLabs is rate-limiting requests; try again in a minute.")

    # --- account ------------------------------------------------------------

    def usage(self) -> dict:
        """{'used': characters used this period, 'limit': allowance}."""
        data = self._get("/v1/user/subscription")
        return {"used": data.get("character_count", 0), "limit": data.get("character_limit", 0),
                "tier": data.get("tier", "")}

    def _get(self, path: str) -> dict:
        resp = self.client.get(path)
        self._raise_for(resp)
        return resp.json()

    @staticmethod
    def _raise_for(resp: httpx.Response) -> None:
        if resp.is_success:
            return
        try:
            detail = resp.json().get("detail", {})
            status, message = (detail.get("status", ""), detail.get("message", "")) if isinstance(detail, dict) \
                else ("", str(detail))
        except ValueError:
            status, message = "", resp.text[:200]
        if resp.status_code == 401:
            raise ElevenLabsError("ElevenLabs rejected the API key. Check ELEVENLABS_API_KEY in .env.")
        if status == "quota_exceeded" or "quota" in message.lower():
            raise ElevenLabsError("Your ElevenLabs character allowance is used up for this month. "
                                  "Switch those characters back to Kokoro, or wait for the reset.")
        raise ElevenLabsError(f"ElevenLabs error {resp.status_code}: {message or status}")
