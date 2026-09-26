"""Assign a voice to every speaking character. Voices already set (e.g. by hand) are kept."""

from __future__ import annotations

from collections import Counter

from .models import NARRATOR, Cast, Character, ScriptLine
from .tts.kokoro_engine import FEMALE_VOICES, MALE_VOICES

# Deep voices that sound good pitched down for dragons.
DRAGON_VOICES = ["am_onyx", "bm_george", "am_fenrir", "bm_daniel", "am_adam"]
# Major characters keep a unique voice; minor ones may share once voices run out.
UNIQUE_TOP_N = 10


def count_lines(cast: Cast, scripts: list[list[ScriptLine]]) -> Counter:
    counts: Counter = Counter()
    for lines in scripts:
        for l in lines:
            if l.type == "narration" or l.speaker in (NARRATOR, "Unknown"):
                continue
            c = cast.find(l.speaker)
            counts[c.name if c else l.speaker] += 1
    for c in cast.characters:
        c.line_count = counts.get(c.name, 0)
    return counts


def auto_cast(cast: Cast, scripts: list[list[ScriptLine]]) -> Cast:
    counts = count_lines(cast, scripts)
    # Speakers the director named but never registered as characters.
    for name in counts:
        if not cast.find(name):
            cast.characters.append(Character(name=name, line_count=counts[name]))

    pov = cast.find(cast.pov_character) if cast.pov_character else None
    if not cast.narrator_voice:
        cast.narrator_voice = MALE_VOICES[0] if pov and pov.gender == "male" else FEMALE_VOICES[0]
    if pov and not cast.split_pov_voice:
        pov.voice = cast.narrator_voice

    speaking = sorted((c for c in cast.characters if c.line_count > 0), key=lambda c: -c.line_count)
    used = {cast.narrator_voice} | {c.voice for c in speaking if c.voice}
    for rank, c in enumerate(speaking):
        if c.voice:
            continue
        pool = _pool(c)
        free = [v for v in pool if v not in used]
        if free:
            c.voice = free[0]
        else:
            # Out of unique voices: reuse one not held by a major character.
            protected = {cast.narrator_voice} | {s.voice for s in speaking[:UNIQUE_TOP_N]}
            reusable = [v for v in pool if v not in protected] or pool
            c.voice = reusable[rank % len(reusable)]
        used.add(c.voice)

    if not cast.unknown_voice:
        spare = [v for v in FEMALE_VOICES[::-1] + MALE_VOICES[::-1] if v not in used]
        cast.unknown_voice = spare[0] if spare else FEMALE_VOICES[-1]
    return cast


def _pool(c: Character) -> list[str]:
    if c.kind == "dragon":
        return DRAGON_VOICES
    if c.gender == "female":
        return FEMALE_VOICES
    if c.gender == "male":
        return MALE_VOICES
    return [v for pair in zip(FEMALE_VOICES, MALE_VOICES) for v in pair]
