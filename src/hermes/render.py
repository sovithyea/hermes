"""Script lines -> audio. Every line is cached by what affects its sound, so edits re-render only what changed."""

from __future__ import annotations

import hashlib
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from .lexicon import Lexicon
from .models import NARRATOR, Cast, ScriptLine
from .tts.base import EMOTION_PROSODY, SAMPLE_RATE, Prosody, TTSEngine

log = logging.getLogger(__name__)

PAUSE_SAME_PARAGRAPH = 0.15
PAUSE_NEW_PARAGRAPH = 0.45
PAUSE_AFTER_TITLE = 1.2

# ffmpeg filter chains for special line types.
EFFECTS = {
    # Dragon mind-speech: deeper, slightly slower, with a cavernous echo.
    "dragon": "asetrate=24000*0.86,aresample=24000,atempo=1.08,aecho=0.8:0.6:60|110:0.3|0.2",
    # Human mind-speech: a light echo so it reads as "inside the head".
    "mind": "aecho=0.8:0.5:40:0.2",
    # Inner thoughts: softer and a little closer.
    "thought": "lowpass=f=7000,volume=-2dB",
}


@dataclass
class RenderStats:
    lines: int = 0
    cache_hits: int = 0
    seconds: float = 0.0


class Renderer:
    def __init__(self, engines: TTSEngine | dict[str, TTSEngine], cast: Cast, lexicon: Lexicon, cache_dir: Path):
        # Kokoro is the default engine; others (ElevenLabs) are used for characters switched to them.
        self.engines = engines if isinstance(engines, dict) else {engines.name: engines}
        self.default = self.engines.get("kokoro") or next(iter(self.engines.values()))
        self.cast, self.lexicon = cast, lexicon
        self.cache_dir = cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.stats = RenderStats()

    # --- per line -----------------------------------------------------------

    def engine_and_voice(self, line: ScriptLine) -> tuple[TTSEngine, str]:
        if line.type == "narration" or line.speaker == NARRATOR:
            return self.default, self.cast.narrator_voice
        c = self.cast.find(line.speaker)
        if c and c.name == self.cast.pov_character and not self.cast.split_pov_voice:
            return self.default, self.cast.narrator_voice  # first-person narrator speaks in the narrator voice
        if c and c.engine != self.default.name and c.engine in self.engines and c.engine_voice:
            return self.engines[c.engine], c.engine_voice
        return self.default, (c.voice if c and c.voice else None) or self.cast.unknown_voice

    def voice_for(self, line: ScriptLine) -> str:
        return self.engine_and_voice(line)[1]

    def effect_for(self, line: ScriptLine) -> str | None:
        if line.type == "narration":
            return None
        c = self.cast.find(line.speaker)
        if c and c.kind == "dragon":
            return "dragon"  # however the director typed it, a dragon should sound like one
        if line.type == "mindspeech":
            return "mind"
        if line.type == "thought":
            return "thought"
        return None

    def _plan(self, line: ScriptLine):
        engine, voice = self.engine_and_voice(line)
        native = getattr(engine, "native_emotion", False)
        # Engines that can act get the emotion itself; others approximate it with pace and volume.
        emotion = line.emotion if native and line.type != "narration" else None
        prosody = EMOTION_PROSODY.get(line.emotion, Prosody()) if line.type != "narration" and not native else Prosody()
        effect = self.effect_for(line)
        text = self.lexicon.apply(line.text)
        return engine, voice, text, prosody, emotion, effect, cache_key(engine.name, voice, text, prosody, effect, emotion)

    def fingerprint(self, title: str, lines: list[ScriptLine]) -> str:
        """Identifies exactly what a chapter would sound like; changes iff its audio would change."""
        keys = [self._plan(_title_line(title, lines))[-1] if title else ""]
        keys += [f"{self._plan(l)[-1]}@{l.paragraph}" for l in lines]
        return hashlib.sha256("|".join(keys).encode()).hexdigest()[:24]

    def line_audio(self, line: ScriptLine) -> np.ndarray:
        engine, voice, text, prosody, emotion, effect, key = self._plan(line)
        path = self.cache_dir / f"{key}.wav"
        self.stats.lines += 1
        if path.exists():
            self.stats.cache_hits += 1
            audio, _ = sf.read(path, dtype="float32")
            return audio
        if emotion is not None:
            audio = engine.synth(text, voice, 1.0, emotion=emotion)
        else:
            audio = engine.synth(text, voice, prosody.speed)
        if prosody.gain_db:
            audio = audio * (10 ** (prosody.gain_db / 20))
        if effect:
            audio = apply_ffmpeg_filter(audio, EFFECTS[effect])
        audio = np.clip(audio, -1.0, 1.0).astype(np.float32)
        sf.write(path, audio, SAMPLE_RATE)
        return audio

    # --- per chapter ----------------------------------------------------------

    def chapter_audio(self, title: str, lines: list[ScriptLine], on_progress=None) -> np.ndarray:
        parts: list[np.ndarray] = []
        if title:
            parts += [self.line_audio(_title_line(title, lines)), silence(PAUSE_AFTER_TITLE)]
        prev_para = None
        for i, line in enumerate(lines):
            if prev_para is not None:
                parts.append(silence(PAUSE_NEW_PARAGRAPH if line.paragraph != prev_para else PAUSE_SAME_PARAGRAPH))
            parts.append(self.line_audio(line))
            prev_para = line.paragraph
            if on_progress:
                on_progress(i + 1, len(lines))
        audio = np.concatenate(parts) if parts else np.zeros(0, np.float32)
        self.stats.seconds += len(audio) / SAMPLE_RATE
        return audio


def cache_key(engine: str, voice: str, text: str, prosody: Prosody, effect: str | None,
              emotion: str | None = None) -> str:
    parts = [engine, voice, text, f"{prosody.speed:.3f}", f"{prosody.gain_db:.2f}", effect or ""]
    if emotion is not None:  # only engines that act on emotion include it (keeps older cache keys valid)
        parts.append(emotion)
    raw = "\x1f".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * SAMPLE_RATE), np.float32)


def _title_line(title: str, lines: list[ScriptLine]) -> ScriptLine:
    chapter = lines[0].chapter if lines else 0
    return ScriptLine(id=f"ch{chapter:03d}-title", chapter=chapter, paragraph=-1,
                      type="narration", speaker=NARRATOR, text=speakable_title(title))


ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
        "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def speakable_title(title: str) -> str:
    """'CHAPTER XIV.' -> 'Chapter Fourteen.'  TTS engines misread roman numerals and shouty caps."""
    words: list[str] = []
    for raw in title.replace("—", " — ").split():
        w = raw.strip(".,:;")
        tail = raw[len(raw.rstrip(".,:;")):]
        after_chapter = bool(words) and words[-1].lower() in ("chapter", "part", "book")
        if w.isdigit():
            w = _num_words(int(w))
        elif _is_roman(w) and (after_chapter or len(w) > 1):  # a lone "I" is usually the pronoun
            w = _num_words(_roman(w))
        elif w.isupper() and len(w) > 1:
            w = w.capitalize()
        if w:
            words.append(w + tail)
    return " ".join(words).rstrip(".,:; ") + "."


def _is_roman(w: str) -> bool:
    return bool(w) and w.isupper() and set(w) <= ROMAN.keys()


def _roman(s: str) -> int:
    total = 0
    for a, b in zip(s, s[1:] + " "):
        v = ROMAN[a]
        total += -v if b != " " and ROMAN[b] > v else v
    return total


def _num_words(n: int) -> str:
    if n < 20:
        w = ONES[n]
    elif n < 100:
        w = TENS[n // 10] + ("-" + ONES[n % 10] if n % 10 else "")
    else:
        rest = n % 100
        w = ONES[n // 100] + " hundred" + (" and " + _num_words(rest).lower() if rest else "")
    return w.capitalize()


def apply_ffmpeg_filter(audio: np.ndarray, af: str) -> np.ndarray:
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-i", "pipe:0",
         "-af", af, "-f", "f32le", "-ar", str(SAMPLE_RATE), "-ac", "1", "pipe:1"],
        input=audio.astype(np.float32).tobytes(), capture_output=True, check=True,
    )
    return np.frombuffer(proc.stdout, dtype=np.float32).copy()


def export_mp3(audio: np.ndarray, out: Path, title: str = "", album: str = "", track: int | None = None) -> Path:
    """Loudness-normalise (audiobook-style -18 LUFS) and encode to MP3."""
    out.parent.mkdir(parents=True, exist_ok=True)
    meta = ["-metadata", f"title={title}", "-metadata", f"album={album}", "-metadata", "genre=Audiobook"]
    if track is not None:
        meta += ["-metadata", f"track={track}"]
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-i", "pipe:0",
         "-af", "loudnorm=I=-18:TP=-2:LRA=11", "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "96k",
         *meta, str(out)],
        input=audio.astype(np.float32).tobytes(), check=True,
    )
    return out
