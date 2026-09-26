import numpy as np

from hermes.casting import auto_cast
from hermes.lexicon import Lexicon
from hermes.models import Cast, Character, ScriptLine
from hermes.render import Renderer, cache_key
from hermes.tts.base import SAMPLE_RATE, Prosody


def line(i, speaker, text="Hello there.", type="dialogue", para=None, emotion="neutral"):
    return ScriptLine(id=f"ch001-{i:04d}", chapter=1, paragraph=i if para is None else para,
                      type=type, speaker=speaker, text=text, emotion=emotion)


def test_lexicon_respells_whole_words_and_possessives():
    lex = Lexicon({"Xaden": "Zayden"})
    assert lex.apply("Xaden’s hand. Xadenia stays.") == "Zayden’s hand. Xadenia stays."


def test_auto_cast_gives_major_characters_unique_voices_and_pov_the_narrator_voice():
    cast = Cast(pov_character="Violet", characters=[
        Character(name="Violet", gender="female"),
        Character(name="Xaden", gender="male"),
        Character(name="Tairn", kind="dragon"),
        Character(name="Mira", gender="female", voice="bf_lily"),  # hand-picked, must be kept
    ])
    script = [line(1, "Violet"), line(2, "Xaden"), line(3, "Tairn", type="mindspeech"),
              line(4, "Mira"), line(5, "Rhiannon")]  # Rhiannon: speaker not in cast yet
    auto_cast(cast, [script])
    v = {c.name: c.voice for c in cast.characters}
    assert v["Violet"] == cast.narrator_voice
    assert v["Mira"] == "bf_lily"
    assert v["Tairn"].startswith(("am_", "bm_"))
    assert v["Rhiannon"] and len({v["Xaden"], v["Tairn"], v["Mira"], v["Rhiannon"], cast.narrator_voice}) == 5
    assert cast.unknown_voice not in v.values()


def test_cache_key_changes_with_anything_audible():
    base = cache_key("kokoro", "af_heart", "Hi.", Prosody(), None)
    assert base == cache_key("kokoro", "af_heart", "Hi.", Prosody(), None)
    assert base != cache_key("kokoro", "af_bella", "Hi.", Prosody(), None)
    assert base != cache_key("kokoro", "af_heart", "Hi!", Prosody(), None)
    assert base != cache_key("kokoro", "af_heart", "Hi.", Prosody(1.1), None)
    assert base != cache_key("kokoro", "af_heart", "Hi.", Prosody(), "dragon")


class FakeEngine:
    name = "fake"
    calls = 0

    def voices(self):
        return ["v"]

    def synth(self, text, voice, speed=1.0):
        FakeEngine.calls += 1
        return np.full(SAMPLE_RATE // 2, 0.1, np.float32)  # 0.5 s per line


def test_renderer_caches_lines_and_inserts_pauses(tmp_path):
    cast = Cast(narrator_voice="n", unknown_voice="u",
                characters=[Character(name="A", voice="a")])
    r = Renderer(FakeEngine(), cast, Lexicon(), tmp_path)
    lines = [line(0, "Narrator", type="narration", para=0), line(1, "A", para=0), line(2, "A", "Bye.", para=1)]
    audio = r.chapter_audio("", lines)
    # 3 lines x 0.5 s + same-paragraph pause 0.15 s + new-paragraph pause 0.45 s
    assert abs(len(audio) / SAMPLE_RATE - 2.1) < 0.01
    calls = FakeEngine.calls
    r.chapter_audio("", lines)
    assert FakeEngine.calls == calls and r.stats.cache_hits == 3


def test_speakable_title():
    from hermes.render import speakable_title
    assert speakable_title("CHAPTER II.") == "Chapter Two."
    assert speakable_title("Chapter I.") == "Chapter One."
    assert speakable_title("CHAPTER XIV") == "Chapter Fourteen."
    assert speakable_title("Chapter 42: The Gauntlet") == "Chapter Forty-two: The Gauntlet."
    assert speakable_title("Chapter One") == "Chapter One."
    assert speakable_title("Epilogue") == "Epilogue."


def test_dragon_lines_get_dragon_effect_even_if_typed_as_thought(tmp_path):
    cast = Cast(narrator_voice="n", characters=[Character(name="Skarth", kind="dragon", voice="d"),
                                                Character(name="Maren", voice="m")])
    r = Renderer(FakeEngine(), cast, Lexicon(), tmp_path)
    assert r.effect_for(line(1, "Skarth", type="thought")) == "dragon"
    assert r.effect_for(line(2, "Maren", type="mindspeech")) == "mind"
    assert r.effect_for(line(3, "Maren", type="thought")) == "thought"
    assert r.effect_for(line(4, "Narrator", type="narration")) is None
