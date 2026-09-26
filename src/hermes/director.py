"""The 'director' pass: label who speaks each quote/italic segment, and how.

Each chunk (~1.2k words) is sent with the current cast list and the last few
attributed lines so speakers stay consistent across chunk boundaries.

The model answers in a compact line format rather than JSON: local models
generate ~10 tokens/s, and JSON syntax roughly tripled the output length.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import get_args, Literal

import ollama

from .ingest import Chapter
from .models import NARRATOR, Cast, Character, LineType, ScriptLine
from .segment import Segment, segment_paragraphs

log = logging.getLogger(__name__)

DEFAULT_MODEL = "qwen3:14b"
CHUNK_WORDS = 1200
CONTEXT_LINES = 8
MAX_RETRIES = 2

Emotion = Literal[
    "neutral", "happy", "sad", "angry", "fearful", "surprised", "whisper",
    "shouting", "sarcastic", "tender", "tense", "pained", "amused", "cold",
    "excited", "anxious", "pleading", "teasing", "dry",
]
EMOTIONS = set(get_args(Emotion))
TYPE_CODES: dict[str, LineType] = {"D": "dialogue", "T": "thought", "M": "mindspeech", "N": "narration"}

LABEL_RE = re.compile(r"^\s*(\d+)\s+([DTMN])\s+(.+?)\s*\|\s*([a-z]+)\s*$")
CHAR_RE = re.compile(r"^\s*\+\s*(.+)$")
POV_RE = re.compile(r"^\s*POV:\s*(.+?)\s*$", re.IGNORECASE)


@dataclass
class Label:
    id: int
    type: LineType
    speaker: str
    emotion: str = "neutral"


@dataclass
class DirectorOutput:
    pov_character: str | None = None
    labels: dict[int, Label] = field(default_factory=dict)
    new_characters: list[Character] = field(default_factory=list)


SYSTEM = f"""You are the casting director for a full-cast audiobook. You label who speaks.

The passage is split into numbered segments:
  [Q<n>] a quoted span (usually spoken dialogue)
  [I<n>] an italic span (inner thought, telepathic/mind-speech, a sign or letter, or emphasis)
Plain text between them is narration and needs no label.

Answer in EXACTLY this format and nothing else:

POV: <name of the first-person "I" narrator, or none>
CHARACTERS:
+ Name | gender | age | kind | aliases | short description
LABELS:
<id> <type> <speaker> | <emotion>

CHARACTERS lists only people who speak in this passage and are NOT already in the cast list
(may be empty). gender: female/male/unknown. age: child/young/adult/old/unknown.
kind: human/dragon/other. aliases: comma-separated nicknames or surnames, or -.

LABELS has one line for EVERY [Q] and [I] id, in order.
type codes: D = spoken dialogue, T = unspoken inner thought,
M = mind-speech (telepathy, e.g. a dragon speaking into a rider's mind),
N = not spoken by anyone (emphasis, titles, signs, a quoted word) — use speaker Narrator.
speaker: the canonical name from the cast list if listed; "Unknown" only if truly impossible to tell.
emotion, one of: {", ".join(sorted(EMOTIONS))}

Attribution rules:
- Use dialogue tags ("said X"), actions in the same paragraph, and who is being addressed.
- A new paragraph usually means a new speaker. In an untagged two-person exchange, speakers alternate —
  a question is usually answered by the OTHER person.
- In first-person books, the "I" narrator's own dialogue and thoughts belong to the POV character
  (use their name, never "Narrator").

Example:
POV: none
CHARACTERS:
+ Elizabeth Bennet | female | young | human | Lizzy, Eliza | witty second daughter
LABELS:
3 D Elizabeth Bennet | teasing
5 D Mr. Darcy | cold
6 N Narrator | neutral"""


def direct_chapter(
    chapter: Chapter,
    cast: Cast,
    model: str = DEFAULT_MODEL,
    on_progress=None,
    think: bool = False,
) -> list[ScriptLine]:
    """Label one chapter. Mutates `cast` with any newly discovered characters."""
    segments = segment_paragraphs(chapter.paragraphs)
    chunks = list(_chunk(segments))
    lines: list[ScriptLine] = []
    for n, chunk in enumerate(chunks, start=1):
        labels = _label_chunk(chunk, cast, lines[-CONTEXT_LINES:], model, think)
        lines.extend(_to_lines(chapter.index, chunk, labels, cast))
        if on_progress:
            on_progress(n, len(chunks))
    return lines


def _chunk(segments: list[Segment]):
    """Group segments into ~CHUNK_WORDS pieces, never splitting a paragraph."""
    buf: list[Segment] = []
    words = 0
    for seg in segments:
        starts_new_para = not buf or seg.paragraph != buf[-1].paragraph
        if starts_new_para and words >= CHUNK_WORDS:
            yield buf
            buf, words = [], 0
        buf.append(seg)
        words += len(seg.text.split())
    if buf:
        yield buf


def _render_chunk(chunk: list[Segment]) -> str:
    paras: list[list[str]] = []
    last_para = None
    for seg in chunk:
        if seg.paragraph != last_para:
            paras.append([])
            last_para = seg.paragraph
        if seg.kind == "quote":
            paras[-1].append(f"[Q{seg.id}] “{seg.text}”")
        elif seg.kind == "italic":
            paras[-1].append(f"[I{seg.id}] _{seg.text}_")
        else:
            paras[-1].append(seg.text)
    return "\n\n".join(" ".join(p) for p in paras)


def _cast_summary(cast: Cast) -> str:
    if not cast.characters:
        return "(empty — this is the start of the book)"
    rows = []
    for c in cast.characters:
        alias = f" (aka {', '.join(c.aliases)})" if c.aliases else ""
        rows.append(f"- {c.name}{alias}: {c.gender}, {c.kind}. {c.description}".strip())
    pov = f"\nPOV character (first-person narrator): {cast.pov_character}" if cast.pov_character else ""
    return "\n".join(rows) + pov


def _context(prev: list[ScriptLine]) -> str:
    spoken = [l for l in prev if l.type != "narration"]
    if not spoken:
        return "(none)"
    return "\n".join(f"{l.speaker}: “{l.text[:120]}”" for l in spoken)


def _label_chunk(
    chunk: list[Segment], cast: Cast, prev: list[ScriptLine], model: str, think: bool
) -> dict[int, Label]:
    targets = {s.id for s in chunk if s.kind != "narr"}
    if not targets:
        return {}
    base = (
        f"CAST SO FAR:\n{_cast_summary(cast)}\n\n"
        f"PREVIOUS SPOKEN LINES (for continuity):\n{_context(prev)}\n\n"
        f"PASSAGE:\n{_render_chunk(chunk)}\n\n"
    )
    labels: dict[int, Label] = {}
    for attempt in range(MAX_RETRIES + 1):
        missing = sorted(targets - labels.keys())
        if not missing:
            break
        out = parse_output(_call(model, base + f"Label these ids: {missing}", think))
        _merge_characters(cast, out)
        labels.update({i: l for i, l in out.labels.items() if i in targets and i not in labels})
    missing = targets - labels.keys()
    if missing:
        log.warning("director could not label %d segment(s): %s", len(missing), sorted(missing)[:10])
    return labels


def _call(model: str, user: str, think: bool) -> str:
    resp = ollama.chat(
        model=model,
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        options={"temperature": 0.1, "num_ctx": 16384},
        think=think,
    )
    return resp.message.content


def parse_output(text: str) -> DirectorOutput:
    out = DirectorOutput()
    for raw in text.splitlines():
        if m := LABEL_RE.match(raw):
            emotion = m.group(4) if m.group(4) in EMOTIONS else "neutral"
            out.labels[int(m.group(1))] = Label(int(m.group(1)), TYPE_CODES[m.group(2)], m.group(3).strip(), emotion)
        elif m := CHAR_RE.match(raw):
            if c := _parse_character(m.group(1)):
                out.new_characters.append(c)
        elif m := POV_RE.match(raw):
            name = m.group(1).strip()
            out.pov_character = None if name.lower() in ("none", "null", "-", "") else name
    return out


def _parse_character(row: str) -> Character | None:
    parts = [p.strip() for p in row.split("|")]
    if not parts[0]:
        return None
    parts += [""] * (6 - len(parts))
    name, gender, age, kind, aliases, desc = parts[:6]
    return Character(
        name=name,
        gender=gender if gender in ("female", "male") else "unknown",
        age=age if age in ("child", "young", "adult", "old") else "unknown",
        kind=kind if kind in ("human", "dragon") else ("other" if kind else "human"),
        aliases=[a.strip() for a in aliases.split(",") if a.strip() and a.strip() != "-"],
        description=desc,
    )


def _merge_characters(cast: Cast, out: DirectorOutput) -> None:
    if out.pov_character and not cast.pov_character:
        cast.pov_character = out.pov_character
    for nc in out.new_characters:
        if nc.name in (NARRATOR, "Unknown"):
            continue
        existing = cast.find(nc.name) or next((cast.find(a) for a in nc.aliases if cast.find(a)), None)
        if existing:
            for a in [nc.name, *nc.aliases]:
                if a != existing.name and a not in existing.aliases:
                    existing.aliases.append(a)
            continue
        cast.characters.append(nc)


def _to_lines(chapter: int, chunk: list[Segment], labels: dict[int, Label], cast: Cast) -> list[ScriptLine]:
    lines = []
    for seg in chunk:
        label = labels.get(seg.id)
        if seg.kind == "narr" or (label and label.type == "narration"):
            ltype, speaker, emotion = "narration", NARRATOR, "neutral"
        elif label:
            known = cast.find(label.speaker)
            ltype, speaker, emotion = label.type, (known.name if known else label.speaker), label.emotion
        else:
            ltype = "dialogue" if seg.kind == "quote" else "thought"
            speaker, emotion = "Unknown", "neutral"
        lines.append(ScriptLine(
            id=f"ch{chapter:03d}-{seg.id:04d}", chapter=chapter, paragraph=seg.paragraph,
            type=ltype, speaker=speaker, text=seg.text, emotion=emotion,
        ))
    return lines

