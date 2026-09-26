"""Performance direction for engines that can act (ElevenLabs v3).

A single mood per paragraph reads like a news report. Real narration shifts within a
paragraph: a breath before a confession, a sigh, a dry aside, a pause before a reveal. This
pass asks the local LLM to place a few v3 audio tags ([sighs], [whispers], …) and pacing
punctuation inside each line. The book's words must come back unchanged: any output that adds,
drops or alters a word is rejected and the plain text is used instead.
"""

from __future__ import annotations

import logging
import re

import ollama

from .director import DEFAULT_MODEL
from .models import ScriptLine

log = logging.getLogger(__name__)

TAGS = [
    "sighs", "exhales", "inhales sharply", "breathless", "whispers", "softly", "quietly", "laughs softly",
    "chuckles", "snorts", "sarcastic", "dryly", "wry", "amused", "teasing", "curious", "awed", "wistful",
    "tender", "longing", "nervous", "tense", "shaky", "urgent", "frustrated", "angry", "excited",
    "serious", "pause", "long pause", "gulps", "swallows",
]
TAG_RE = re.compile(r"\[([a-z ]+)\]")
BATCH = 8
CONTEXT = 2

SYSTEM = f"""You are the director of a full-cast fantasy romance audiobook recorded with an AI voice actor.
You mark up lines so the actor gives a vivid, intimate, emotional performance — never a flat, even
news-reader delivery. First-person narration should sound like the narrator living the moment:
wry, breathless, tender, frightened, amused, as the text calls for.

For each line, return the SAME words with:
- 1 to 3 performance tags in square brackets, placed right before the words they colour.
  Use only: {", ".join(f"[{t}]" for t in TAGS)}
- optional pacing punctuation: "..." for a hesitation, "—" for a break. Do not over-use either.
Short lines (under ~8 words) usually need at most one tag, or none.
Put tags INSIDE long lines where the feeling shifts, not only at the start. There is no [neutral]
tag: if a stretch is plain description, leave it untagged.
NEVER add, remove, reorder or change any word. Keep all original punctuation unless adding pauses.

Example
input:  L0 (Narrator, narration, feeling: tense): My chest tightens. He's alive. After everything, he's standing right there, and I can't breathe.
output: L0 [inhales sharply] My chest tightens. [shaky] He's alive... After everything, he's standing right there — [whispers] and I can't breathe.

Answer with one line per input line, exactly: <id> <marked-up text>"""


def _words(text: str) -> list[str]:
    plain = TAG_RE.sub(" ", text.lower().replace("’", "'"))
    return re.findall(r"[a-z0-9']+", plain)


def valid(original: str, performed: str) -> bool:
    tags = TAG_RE.findall(performed)
    return bool(performed.strip()) and _words(original) == _words(performed) and \
        all(t in TAGS for t in tags) and len(tags) <= 4


def perform_lines(lines: list[ScriptLine], all_lines: list[ScriptLine], pov: str | None,
                  model: str = DEFAULT_MODEL) -> dict[str, str]:
    """Performance text for `lines` (the ones going to an acting engine). Returns {line id: text}."""
    order = {l.id: i for i, l in enumerate(all_lines)}
    out: dict[str, str] = {}
    for start in range(0, len(lines), BATCH):
        batch = lines[start:start + BATCH]
        first, last = order[batch[0].id], order[batch[-1].id]
        before = all_lines[max(0, first - CONTEXT):first]
        after = all_lines[last + 1:last + 1 + CONTEXT]
        ids = {f"L{i}": l for i, l in enumerate(batch)}
        user = (
            (f"The narrator is {pov}, telling the story in first person.\n\n" if pov else "")
            + "CONTEXT BEFORE:\n" + "\n".join(f"{l.speaker}: {l.text}" for l in before)
            + "\n\nLINES TO MARK UP:\n"
            + "\n".join(f"{k} ({l.speaker}, {l.type}, feeling: {l.emotion}): {l.text}" for k, l in ids.items())
            + "\n\nCONTEXT AFTER:\n" + "\n".join(f"{l.speaker}: {l.text}" for l in after)
        )
        resp = ollama.chat(model=model, messages=[{"role": "system", "content": SYSTEM},
                                                  {"role": "user", "content": user}],
                           options={"temperature": 0.5, "num_ctx": 16384}, think=False)
        for row in resp.message.content.splitlines():
            m = re.match(r"^\s*(L\d+)\s*[:.)-]?\s*(.+)$", row)
            if not m or m.group(1) not in ids:
                continue
            line, text = ids[m.group(1)], m.group(2).strip()
            if valid(line.text, text):
                out[line.id] = text
            else:
                log.info("performance for %s changed the words; using plain text", line.id)
    return out
