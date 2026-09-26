"""The book → audiobook steps, shared by the CLI and the web app."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Callable

from . import director
from .casting import auto_cast
from .ingest import load_book
from .lexicon import Lexicon
from .render import Renderer, RenderStats, export_mp3
from .store import BookProject

Progress = Callable[[int, int, str], None]  # (done, total, message)

_engine = None
_engine_lock = threading.RLock()


class _LockedEngine:
    """Serialises GPU access per line, so previews can slip in between lines of a long render."""

    def __init__(self, inner):
        self.inner, self.name = inner, inner.name

    def voices(self) -> list[str]:
        return self.inner.voices()

    def synth(self, text: str, voice: str, speed: float = 1.0):
        with _engine_lock:
            return self.inner.synth(text, voice, speed)


def engine():
    """One TTS engine per process; the GPU model is loaded on first use."""
    global _engine
    with _engine_lock:
        if _engine is None:
            from .tts.kokoro_engine import KokoroEngine

            _engine = _LockedEngine(KokoroEngine())
    return _engine


def ingest(path: Path, root: Path | None = None) -> BookProject:
    chapters = load_book(path)
    if not chapters:
        raise ValueError("No chapters found in that file.")
    proj = BookProject.create(path, root) if root else BookProject.create(path)
    proj.save_chapters(chapters)
    (proj.dir / "meta.json").write_text(json.dumps({"title": _epub_title(path) or path.stem}))
    return proj


def create_photo_book(title: str) -> BookProject:
    """An empty book that photos get added to; its text comes from OCR (see ocr_photos)."""
    from .store import LIBRARY, slugify

    slug = base = slugify(title)
    n = 2
    while (LIBRARY / slug).exists():
        slug, n = f"{base}-{n}", n + 1
    proj = BookProject(slug)
    (proj.dir / "photos").mkdir(parents=True)
    proj.save_chapters([])
    (proj.dir / "meta.json").write_text(json.dumps({"title": title, "source": "photos"}))
    return proj


def ocr_photos(proj: BookProject, progress: Progress | None = None) -> int:
    """(Re)build a photo book's chapters from its photos. Each page's OCR is cached,
    so adding more photos later only reads the new ones. Returns the page count."""
    from .ingest import _load_txt, MIN_CHAPTER_WORDS
    from .ocr import ocr_page, assemble, sort_photos

    photos = sort_photos(list((proj.dir / "photos").iterdir()))
    cache_dir = proj.dir / "photos" / ".ocr"
    cache_dir.mkdir(exist_ok=True)
    pages = []
    for n, photo in enumerate(photos, start=1):
        cached = cache_dir / f"{photo.name}.json"
        if cached.exists():
            pages.append(json.loads(cached.read_text()))
        else:
            page = ocr_page(photo)
            cached.write_text(json.dumps(page, ensure_ascii=False))
            pages.append(page)
        if progress:
            progress(n, len(photos), f"Reading page photos ({n}/{len(photos)})")
    text = assemble(pages)
    (proj.dir / "source.txt").write_text(text, encoding="utf-8")
    chapters = [c for c in _load_txt(text) if c.word_count >= MIN_CHAPTER_WORDS] or _load_txt(text)
    for i, c in enumerate(chapters, start=1):
        c.index = i
    proj.save_chapters(chapters)
    return len(photos)


def _epub_title(path: Path) -> str | None:
    if path.suffix.lower() != ".epub":
        return None
    try:
        from ebooklib import epub

        meta = epub.read_epub(str(path), options={"ignore_ncx": True}).get_metadata("DC", "title")
        return meta[0][0] if meta else None
    except Exception:
        return None


def direct(proj: BookProject, chapters: list[int], progress: Progress | None = None,
           model: str = director.DEFAULT_MODEL, think: bool = False) -> None:
    """Label speakers for chapters, then (re)assign voices for any new characters."""
    by_index = {c.index: c for c in proj.load_chapters()}
    cast = proj.load_cast()
    for i, n in enumerate(chapters):
        def step(done: int, total: int, n=n, i=i) -> None:
            if progress:
                progress(i * 100 + done * 100 // total, len(chapters) * 100, f"Reading chapter {n}")
        lines = director.direct_chapter(by_index[n], cast, model, on_progress=step, think=think)
        proj.save_script(n, lines)
        proj.save_cast(cast)
    proj.save_cast(auto_cast(cast, proj.all_scripts()))


def render(proj: BookProject, chapters: list[int], progress: Progress | None = None) -> RenderStats:
    titles = {c.index: c.title for c in proj.load_chapters()}
    cast = auto_cast(proj.load_cast(), proj.all_scripts())  # fills in voices for any new speakers
    proj.save_cast(cast)
    renderer = Renderer(engine(), cast, Lexicon.load(proj.lexicon_path), proj.cache_dir)
    for i, n in enumerate(chapters):
        def step(done: int, total: int, n=n, i=i) -> None:
            if progress:
                progress(i * 100 + done * 100 // max(total, 1), len(chapters) * 100, f"Voicing chapter {n}")
        lines = proj.load_script(n)
        audio = renderer.chapter_audio(titles[n], lines, on_progress=step)
        export_mp3(audio, proj.audio_path(n), title=titles[n], album=proj.slug, track=n)
        proj.save_render_info(n, {"fingerprint": renderer.fingerprint(titles[n], lines),
                                  "seconds": round(len(audio) / 24_000, 1)})
    return renderer.stats


class _NoEngine:
    name = "kokoro"  # must match the real engine's name so fingerprints agree


def chapter_status(proj: BookProject) -> dict[int, str]:
    """new → read (script exists) → done, or stale when the script/cast/lexicon changed since rendering."""
    renderer = Renderer(_NoEngine(), proj.load_cast(), Lexicon.load(proj.lexicon_path), proj.cache_dir)
    out = {}
    for c in proj.load_chapters():
        if not proj.script_path(c.index).exists():
            out[c.index] = "new"
            continue
        info = proj.load_render_info(c.index)
        if not info or not proj.audio_path(c.index).exists():
            out[c.index] = "read"
        elif info.get("fingerprint") != renderer.fingerprint(c.title, proj.load_script(c.index)):
            out[c.index] = "stale"
        else:
            out[c.index] = "done"
    return out
