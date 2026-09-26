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


_eleven = None


def elevenlabs():
    """The ElevenLabs engine, or None when no API key is configured."""
    global _eleven
    from . import config

    if _eleven is None and config.elevenlabs_key():
        from .tts.elevenlabs_engine import ElevenLabsEngine

        _eleven = ElevenLabsEngine(config.elevenlabs_key(), config.elevenlabs_model())
    return _eleven


def engines() -> dict:
    out = {"kokoro": engine()}
    if elevenlabs():
        out["elevenlabs"] = elevenlabs()
    return out


class _StandIn:
    """Same name/abilities as a real engine, without loading it — for fingerprints and estimates."""

    def __init__(self, name: str, native_emotion: bool = False):
        self.name, self.native_emotion = name, native_emotion


def stand_in_engines() -> dict:
    from . import config

    out = {"kokoro": _StandIn("kokoro")}
    if config.elevenlabs_key():
        out["elevenlabs"] = _StandIn("elevenlabs", native_emotion=True)
    return out


def elevenlabs_estimate(proj: BookProject) -> dict:
    """Characters of text the ElevenLabs-voiced lines would bill, total and not yet rendered."""
    renderer = Renderer(stand_in_engines(), proj.load_cast(), Lexicon.load(proj.lexicon_path), proj.cache_dir)
    total = pending = 0
    for lines in proj.all_scripts():
        for line in lines:
            plan = renderer._plan(line)
            if plan[0].name == "elevenlabs":
                chars = len(plan[2])
                total += chars
                if not (proj.cache_dir / f"{plan[-1]}.wav").exists():
                    pending += chars
    return {"total": total, "pending": pending}


def ingest(path: Path, root: Path | None = None, owner: str | None = None, unique: bool = False) -> BookProject:
    """Import a book file. `unique` gives it a fresh folder rather than replacing a same-named book
    (web uploads, where two people may add the same title)."""
    from .store import LIBRARY, slugify

    chapters = load_book(path)
    if not chapters:
        raise ValueError("No chapters found in that file.")
    root = root or LIBRARY
    slug = _free_slug(slugify(path.stem), root) if unique else slugify(path.stem)
    proj = BookProject.create(path, root, slug=slug)
    proj.save_chapters(chapters)
    meta = {"title": _epub_title(path) or path.stem}
    if owner:
        meta["owner"] = owner
    (proj.dir / "meta.json").write_text(json.dumps(meta))
    return proj


def _free_slug(base: str, root: Path) -> str:
    slug, n = base, 2
    while (root / slug).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


def create_photo_book(title: str, owner: str | None = None) -> BookProject:
    """An empty book that photos get added to; its text comes from OCR (see ocr_photos)."""
    from .store import LIBRARY, slugify

    proj = BookProject(_free_slug(slugify(title), LIBRARY))
    (proj.dir / "photos").mkdir(parents=True)
    proj.save_chapters([])
    meta = {"title": title, "source": "photos"}
    if owner:
        meta["owner"] = owner
    (proj.dir / "meta.json").write_text(json.dumps(meta))
    return proj


MIN_PAGE_WORDS = 25        # fewer than this means the shot missed the text (blurry, cut off…)
DUPLICATE_SIMILARITY = 0.9  # a page this similar to the previous one was photographed twice
_scan_lock = threading.Lock()


def _pages_dir(proj: BookProject) -> Path:
    """Where each page's OCR result lives. Photos themselves are deleted once read."""
    d = proj.dir / "photos" / ".ocr"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _page_files(proj: BookProject) -> list[Path]:
    from .ocr import sort_photos

    files = {p.with_suffix("").name: p for p in _pages_dir(proj).glob("*.json")}
    # Page JSONs are named after their photo ("00012-IMG_4410.jpg.json"); sort as photos sort.
    order = sort_photos([Path(n) for n in files])
    return [files[p.name] for p in order]


def ocr_photos(proj: BookProject, progress: Progress | None = None, keep_photos: bool = False) -> int:
    """Read any photos not yet read, delete them (only the text is kept), and rebuild the
    book's chapters from every page read so far. Returns the number of pages."""
    from .ocr import ocr_page, sort_photos

    photos = sort_photos([p for p in (proj.dir / "photos").iterdir() if p.is_file()])
    for n, photo in enumerate(photos, start=1):
        page = ocr_page(photo)
        (_pages_dir(proj) / f"{photo.name}.json").write_text(json.dumps(page, ensure_ascii=False))
        if not keep_photos:
            photo.unlink()
        if progress:
            progress(n, len(photos), f"Reading page photos ({n}/{len(photos)})")
    return rebuild_from_pages(proj)


def rebuild_from_pages(proj: BookProject) -> int:
    from .ingest import _load_txt, MIN_CHAPTER_WORDS
    from .ocr import assemble

    files = _page_files(proj)
    text = assemble([json.loads(f.read_text()) for f in files])
    (proj.dir / "source.txt").write_text(text, encoding="utf-8")
    chapters = [c for c in _load_txt(text) if c.word_count >= MIN_CHAPTER_WORDS] or _load_txt(text)
    for i, c in enumerate(chapters, start=1):
        c.index = i
    proj.save_chapters(chapters if text.strip() else [])
    return len(files)


def add_scanned_page(proj: BookProject, image: bytes, suffix: str = ".jpg") -> dict:
    """Read one page photographed in the app. The photo is deleted straight after reading.
    Rejects unreadable shots and accidental double shots so the reader can retake."""
    import difflib

    from .ocr import ocr_page

    with _scan_lock:
        files = _page_files(proj)
        seq = 1 + max((int(f.name[:5]) for f in files if f.name[:5].isdigit()), default=-1)
        name = f"{seq:05d}-scan{suffix.lower()}"
        photo = proj.dir / "photos" / name
        photo.write_bytes(image)
        try:
            page = ocr_page(photo)
        finally:
            photo.unlink(missing_ok=True)
        text = " ".join(page["paragraphs"])
        words = len(text.split())
        if words < MIN_PAGE_WORDS:
            return {"ok": False, "reason": "unreadable", "words": words}
        if files:
            prev = json.loads(files[-1].read_text())
            prev_text = " ".join(prev["paragraphs"])
            if difflib.SequenceMatcher(None, prev_text, text).ratio() > DUPLICATE_SIMILARITY:
                return {"ok": False, "reason": "duplicate", "words": words}
        (_pages_dir(proj) / f"{name}.json").write_text(json.dumps(page, ensure_ascii=False))
        count = rebuild_from_pages(proj)
    return {"ok": True, "id": name, "page": count, "words": words, "heading": page["heading"],
            "preview": _preview(page)}


def remove_scanned_page(proj: BookProject, page_id: str) -> int:
    with _scan_lock:
        target = _pages_dir(proj) / f"{Path(page_id).name}.json"
        target.unlink(missing_ok=True)
        return rebuild_from_pages(proj)


def scanned_pages(proj: BookProject) -> list[dict]:
    out = []
    for n, f in enumerate(_page_files(proj), start=1):
        page = json.loads(f.read_text())
        out.append({"id": f.with_suffix("").name, "n": n, "heading": page["heading"], "preview": _preview(page),
                    "words": sum(len(p.split()) for p in page["paragraphs"])})
    return out


def _preview(page: dict) -> str:
    first = (page["paragraphs"] or [""])[0].replace("_", "")
    return first[:70] + ("…" if len(first) > 70 else "")


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
    renderer = Renderer(engines(), cast, Lexicon.load(proj.lexicon_path), proj.cache_dir)
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


def chapter_status(proj: BookProject) -> dict[int, str]:
    """new → read (script exists) → done, or stale when the script/cast/lexicon changed since rendering."""
    renderer = Renderer(stand_in_engines(), proj.load_cast(), Lexicon.load(proj.lexicon_path), proj.cache_dir)
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
