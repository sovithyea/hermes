import json

import httpx
import numpy as np
import pytest

from hermes.lexicon import Lexicon
from hermes.models import Cast, Character, ScriptLine
from hermes.render import Renderer
from hermes.tts.elevenlabs_engine import ElevenLabsEngine, ElevenLabsError


def fake_api(requests: list, status: int = 200, detail: dict | None = None):
    def handler(req: httpx.Request) -> httpx.Response:
        requests.append(req)
        if status != 200:
            return httpx.Response(status, json={"detail": detail or {}})
        if req.url.path == "/v1/voices":
            return httpx.Response(200, json={"voices": [
                {"voice_id": "v-f", "name": "Aria", "labels": {"gender": "female", "description": "warm"}},
                {"voice_id": "v-m", "name": "Roger", "labels": {"gender": "male"}},
            ]})
        if req.url.path == "/v1/user/subscription":
            return httpx.Response(200, json={"character_count": 1200, "character_limit": 10000, "tier": "free"})
        if req.url.path.startswith("/v1/text-to-speech/"):
            return httpx.Response(200, content=(np.ones(2400, dtype="<i2") * 16384).tobytes())
        return httpx.Response(404)
    return httpx.Client(base_url="https://api.elevenlabs.io", transport=httpx.MockTransport(handler))


def engine(requests, **kw):
    return ElevenLabsEngine("test-key", client=fake_api(requests, **kw))


def test_synth_sends_emotion_tag_and_decodes_pcm():
    reqs = []
    audio = engine(reqs).synth("Get down!", "v-m", emotion="shouting")
    req = reqs[-1]
    assert req.headers["xi-api-key"] == "test-key"
    assert req.url.params["output_format"] == "pcm_24000"
    assert json.loads(req.content) == {"text": "[shouting] Get down!", "model_id": "eleven_v3"}
    assert audio.dtype == np.float32 and len(audio) == 2400 and abs(audio[0] - 0.5) < 1e-6


def test_neutral_lines_and_older_models_get_no_tag():
    reqs = []
    e = engine(reqs)
    assert e.tagged("Hello.", "neutral") == "Hello."
    e.model = "eleven_multilingual_v2"
    assert e.tagged("Hello.", "whisper") == "Hello."


def test_voices_usage_and_picking_by_gender():
    e = engine([])
    assert [v["name"] for v in e.voice_list()] == ["Aria", "Roger"]
    assert e.usage() == {"used": 1200, "limit": 10000, "tier": "free"}
    assert e.pick_voice("male", taken=set()) == "v-m"
    assert e.pick_voice("female", taken={"v-f"}) == "v-f"  # reuse rather than fail


def test_friendly_errors():
    with pytest.raises(ElevenLabsError, match="rejected the API key"):
        engine([], status=401).synth("x", "v")
    with pytest.raises(ElevenLabsError, match="allowance is used up"):
        engine([], status=400, detail={"status": "quota_exceeded", "message": "quota"}).synth("x", "v")


class FakeKokoro:
    name = "kokoro"

    def __init__(self):
        self.calls = []

    def synth(self, text, voice, speed=1.0):
        self.calls.append((text, voice, speed))
        return np.full(2400, 0.1, np.float32)


def test_hybrid_routing_narrator_on_kokoro_character_on_elevenlabs(tmp_path):
    reqs = []
    kokoro, eleven = FakeKokoro(), engine(reqs)
    cast = Cast(narrator_voice="af_heart", pov_character="Maren", characters=[
        Character(name="Maren", voice="af_heart", engine="elevenlabs", engine_voice="v-f"),  # POV: narrator voice
        Character(name="Kael", voice="am_fenrir", engine="elevenlabs", engine_voice="v-m"),
        Character(name="Ione", voice="af_bella"),
    ])
    r = Renderer({"kokoro": kokoro, "elevenlabs": eleven}, cast, Lexicon(), tmp_path)
    L = lambda i, s, t, e="neutral": ScriptLine(id=f"x{i}", chapter=1, paragraph=i, type=t, speaker=s, text=f"line {i}", emotion=e)
    r.chapter_audio("", [L(0, "Narrator", "narration"), L(1, "Kael", "dialogue", "whisper"),
                         L(2, "Maren", "dialogue", "angry"), L(3, "Ione", "dialogue", "angry")])
    tts = [json.loads(q.content) for q in reqs if "text-to-speech" in q.url.path]
    assert tts == [{"text": "[whispers] line 1", "model_id": "eleven_v3"}]  # only Kael went to ElevenLabs
    assert [(t, v) for t, v, _ in kokoro.calls] == [("line 0", "af_heart"), ("line 2", "af_heart"), ("line 3", "af_bella")]
    assert kokoro.calls[2][2] > 1.0  # Kokoro still fakes "angry" with pace
