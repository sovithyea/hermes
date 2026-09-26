"""Deterministically split paragraphs into narration / quote / italic segments.

The LLM never rewrites book text — it only labels these segments — so no
words can be dropped or hallucinated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Curly or straight double quotes. An unclosed quote runs to paragraph end
# (common for multi-paragraph speeches).
QUOTE_RE = re.compile(r"“[^”]*(?:”|$)|\"[^\"]*(?:\"|$)")
# Italic runs of 3+ words are candidate thoughts / mind-speech; shorter ones are emphasis.
ITALIC_RE = re.compile(r"_([^_]+)_")
MIN_ITALIC_WORDS = 3


@dataclass
class Segment:
    id: int
    paragraph: int
    kind: str  # "narr" | "quote" | "italic"
    text: str


def segment_paragraphs(paragraphs: list[str]) -> list[Segment]:
    segments: list[Segment] = []
    for p_idx, para in enumerate(paragraphs):
        for kind, text in _split_paragraph(para):
            segments.append(Segment(len(segments), p_idx, kind, text))
    return segments


def _split_paragraph(para: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    pos = 0
    for m in QUOTE_RE.finditer(para):
        out.extend(_split_italics(para[pos:m.start()]))
        out.append(("quote", _strip_markers(m.group().strip("“”\""))))
        pos = m.end()
    out.extend(_split_italics(para[pos:]))
    return [(k, t) for k, t in out if _has_words(t)]


def _split_italics(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    pos = 0
    for m in ITALIC_RE.finditer(text):
        if len(m.group(1).split()) < MIN_ITALIC_WORDS:
            continue
        out.append(("narr", _strip_markers(text[pos:m.start()])))
        out.append(("italic", m.group(1).strip()))
        pos = m.end()
    out.append(("narr", _strip_markers(text[pos:])))
    return out


def _strip_markers(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("_", "")).strip()


def _has_words(s: str) -> bool:
    return bool(re.search(r"\w", s))
