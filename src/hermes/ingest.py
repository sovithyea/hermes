"""Turn an EPUB / PDF / TXT file into a list of chapters.

Italic text is kept as _underscore_ markers so the director can spot
inner thoughts and dragon mind-speech later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

MIN_CHAPTER_WORDS = 150  # smaller spine items are front/back matter (copyright page, etc.)


@dataclass
class Chapter:
    index: int
    title: str
    paragraphs: list[str]

    @property
    def word_count(self) -> int:
        return sum(len(p.split()) for p in self.paragraphs)


def load_book(path: Path) -> list[Chapter]:
    suffix = path.suffix.lower()
    if suffix == ".epub":
        chapters = _load_epub(path)
    elif suffix == ".pdf":
        chapters = _load_pdf(path)
    elif suffix in (".txt", ".md"):
        chapters = _load_txt(path.read_text(encoding="utf-8", errors="replace"))
    else:
        raise ValueError(f"Unsupported file type: {suffix}")
    chapters = [c for c in chapters if c.word_count >= MIN_CHAPTER_WORDS]
    for i, c in enumerate(chapters, start=1):
        c.index = i
    return chapters


# --- EPUB -----------------------------------------------------------------

def _load_epub(path: Path) -> list[Chapter]:
    import ebooklib
    from ebooklib import epub

    book = epub.read_epub(str(path), options={"ignore_ncx": True})
    chapters: list[Chapter] = []
    for idref, _linear in book.spine:
        item = book.get_item_with_id(idref)
        if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        chapters.extend(html_to_chapters(item.get_content().decode("utf-8", errors="replace")))
    return chapters


def html_to_chapters(html: str) -> list[Chapter]:
    """One HTML document may hold one chapter or several (split on h1/h2)."""
    soup = BeautifulSoup(html, "html.parser")
    body = soup.body or soup
    chapters: list[Chapter] = []
    headings: list[str] = []
    paragraphs: list[str] = []

    def flush() -> None:
        if not paragraphs:
            return
        # A tiny piece (e.g. split off by an illustration caption) joins the previous chapter.
        if chapters and sum(len(p.split()) for p in paragraphs) < MIN_CHAPTER_WORDS:
            chapters[-1].paragraphs.extend(paragraphs)
        else:
            chapters.append(Chapter(0, _pick_title(headings, paragraphs), list(paragraphs)))

    for el in body.find_all(["h1", "h2", "h3", "p", "blockquote"]):
        if el.name in ("h1", "h2", "h3"):
            heading = _clean(el.get_text(" "))
            if el.name in ("h1", "h2") and paragraphs:
                flush()
                headings, paragraphs = [], []
            if heading:
                headings.append(heading)
            continue
        if el.find_parent(["p", "blockquote"]):
            continue  # nested; already captured by its parent
        text = _clean(_text_with_italics(el))
        if text:
            paragraphs.append(text)
    flush()
    return chapters


def _pick_title(headings: list[str], paragraphs: list[str]) -> str:
    for h in headings:
        m = CHAPTER_IN_HEADING_RE.search(h)
        if m:
            return m.group().strip()
    return headings[0] if headings else _guess_title(paragraphs)


def _text_with_italics(el: Tag) -> str:
    parts: list[str] = []
    for child in el.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif isinstance(child, Tag):
            if child.name == "br":
                parts.append(" ")
            elif child.name in ("em", "i") or "italic" in " ".join(child.get("class", [])):
                inner = _clean(child.get_text())
                parts.append(f"_{inner}_" if inner else "")
            else:
                parts.append(_text_with_italics(child))
    return "".join(parts)


# --- PDF / TXT ------------------------------------------------------------

CHAPTER_RE = re.compile(r"^\s*(chapter|prologue|epilogue)\b[^\n]{0,60}$", re.IGNORECASE)
CHAPTER_IN_HEADING_RE = re.compile(r"\b(chapter|prologue|epilogue)\b.{0,60}$", re.IGNORECASE)


def _load_pdf(path: Path) -> list[Chapter]:
    from pypdf import PdfReader

    text = "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    return _load_txt(text)


def _load_txt(text: str) -> list[Chapter]:
    chapters: list[Chapter] = []
    title, buf = "", []
    for block in re.split(r"\n\s*\n", text):
        block = _clean(block)
        if not block:
            continue
        if CHAPTER_RE.match(block):
            if buf:
                chapters.append(Chapter(0, title or _guess_title(buf), buf))
            title, buf = block, []
        else:
            buf.append(block)
    if buf:
        chapters.append(Chapter(0, title or _guess_title(buf), buf))
    return chapters


# --- helpers --------------------------------------------------------------

def _clean(s: str) -> str:
    s = s.replace(" ", " ").replace("__", "")
    return re.sub(r"\s+", " ", s).strip()


def _guess_title(paragraphs: list[str]) -> str:
    first = paragraphs[0]
    return first if len(first) < 60 else "Untitled"
