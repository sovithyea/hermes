"""Hermes web app: upload a book, fix the cast and script, generate and listen.

    uv run hermes serve        # http://localhost:8000
"""

from __future__ import annotations

import hashlib
import os
import io
import json
import shutil
import tempfile
from pathlib import Path

import soundfile as sf
from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import pipeline
from ..casting import auto_cast
from ..director import EMOTIONS
from ..lexicon import Lexicon
from ..models import NARRATOR
from ..render import Renderer, export_mp3
from .. import store
from ..store import BookProject
from ..tts.kokoro_engine import FEMALE_VOICES, MALE_VOICES
from .identity import current_user, owner as mac_owner
from .jobs import JobQueue

HERE = Path(__file__).parent
app = FastAPI(title="Hermes")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
jobs = JobQueue()

LINE_TYPES = ["narration", "dialogue", "thought", "mindspeech"]


def voice_label(v: str) -> str:
    accent = "American" if v[0] == "a" else "British"
    sex = "female" if v[1] == "f" else "male"
    return f"{v.split('_', 1)[1].capitalize()} — {accent} {sex}"


templates.env.globals.update(voice_label=voice_label, VOICES=FEMALE_VOICES + MALE_VOICES)


def owns(user, proj: BookProject) -> bool:
    return (proj.owner() or mac_owner().login) == user.login


@app.middleware("http")
async def per_person_libraries(request: Request, call_next):
    """Work out who is asking, and hide every book that isn't theirs (as if it didn't exist)."""
    request.state.user = current_user(request.client.host if request.client else None, request.headers)
    parts = request.url.path.split("/")
    if len(parts) > 2 and parts[1] == "book":
        proj = BookProject(parts[2])
        if proj.dir.exists() and not owns(request.state.user, proj):
            return HTMLResponse("No such book", status_code=404)
    return await call_next(request)


# --- helpers -------------------------------------------------------------------

def project(slug: str) -> BookProject:
    proj = BookProject(slug)
    if not (proj.dir / "chapters.json").exists():
        raise HTTPException(404, "No such book")
    return proj


def book_title(proj: BookProject) -> str:
    meta = proj.dir / "meta.json"
    if meta.exists():
        return json.loads(meta.read_text()).get("title") or proj.slug
    return proj.slug.replace("-", " ").title()


def chapter_rows(proj: BookProject) -> list[dict]:
    busy = jobs.busy_chapters(proj.slug)
    status = pipeline.chapter_status(proj)
    rows = []
    for c in proj.load_chapters():
        audio = proj.audio_path(c.index)
        rows.append({"index": c.index, "title": c.title, "words": c.word_count, "status": status[c.index],
                     "busy": busy.get(c.index), "version": int(audio.stat().st_mtime) if audio.exists() else 0})
    return rows


def parse_chapters(spec: str, rows: list[dict], kind: str) -> list[int]:
    if spec == "all":
        want = {"direct": {"new"}, "render": {"read", "stale"}}[kind]
        return [r["index"] for r in rows if r["status"] in want]
    return [int(x) for x in spec.split(",") if x.strip()]


# --- library -------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def library(request: Request):
    books = []
    if store.LIBRARY.exists():
        for d in sorted(store.LIBRARY.iterdir()):
            if (d / "chapters.json").exists() and owns(request.state.user, BookProject(d.name)):
                proj = BookProject(d.name)
                rows = chapter_rows(proj)
                books.append({"slug": d.name, "title": book_title(proj), "chapters": len(rows),
                              "done": sum(r["status"] == "done" for r in rows)})
    return templates.TemplateResponse(request, "library.html", {"books": books})


@app.post("/upload")
async def upload(request: Request, files: list[UploadFile], title: str = Form("")):
    who = request.state.user.login
    from ..ocr import IMAGE_SUFFIXES

    suffixes = {Path(f.filename or "").suffix.lower() for f in files}
    if suffixes and suffixes <= IMAGE_SUFFIXES:
        proj = pipeline.create_photo_book(title.strip() or "Photographed book", owner=who)
        _save_photos(proj, files)
        jobs.submit(proj.slug, "ocr", [])
        return RedirectResponse(f"/book/{proj.slug}", status_code=303)
    if len(files) != 1:
        raise HTTPException(400, "Upload one EPUB/PDF/TXT file, or any number of page photos.")
    file = files[0]
    suffix = Path(file.filename or "book.epub").suffix.lower()
    if suffix not in (".epub", ".pdf", ".txt"):
        raise HTTPException(400, "Please upload an EPUB, PDF or TXT file, or photos of the pages.")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / Path(file.filename).name
        with path.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        try:
            proj = pipeline.ingest(path, owner=who, unique=True)
        except ValueError as e:
            raise HTTPException(400, str(e))
    return RedirectResponse(f"/book/{proj.slug}", status_code=303)


def _save_photos(proj: BookProject, files: list[UploadFile]) -> None:
    """Keep the phone's names (IMG_1234…) so pages sort in shooting order; prefix with the
    upload position so identically named files (some phones send 'image.jpg') still keep order."""
    folder = proj.dir / "photos"
    start = len([p for p in folder.iterdir() if p.is_file()])
    for i, f in enumerate(files):
        name = Path(f.filename or f"page{i}.jpg").name
        with (folder / f"{start + i:05d}-{name}").open("wb") as out:
            shutil.copyfileobj(f.file, out)


# --- scanning pages in the app ---------------------------------------------------

@app.post("/scan/new")
def scan_new(request: Request, title: str = Form(...)):
    proj = pipeline.create_photo_book(title.strip() or "Scanned book", owner=request.state.user.login)
    return RedirectResponse(f"/book/{proj.slug}/scan", status_code=303)


@app.get("/book/{slug}/scan", response_class=HTMLResponse)
def scan_page(request: Request, slug: str):
    proj = project(slug)
    phone_url = os.environ.get("HERMES_PHONE_BASE")
    qr = None
    if phone_url:
        import segno

        qr = segno.make(f"{phone_url}/book/{slug}/scan", error="m").svg_inline(scale=5, omitsize=True, dark="#1b1815", light="#ffffff")
    pages = pipeline.scanned_pages(proj)
    return templates.TemplateResponse(request, "scan.html", {
        "slug": slug, "title": book_title(proj), "pages": pages[-8:][::-1], "count": len(pages),
        "qr": qr, "phone_url": phone_url,
    })


@app.post("/book/{slug}/scan")
async def scan_upload(slug: str, file: UploadFile):
    proj = project(slug)
    suffix = Path(file.filename or "page.jpg").suffix or ".jpg"
    return pipeline.add_scanned_page(proj, await file.read(), suffix)


@app.post("/book/{slug}/scan/{page_id}/delete")
def scan_delete(slug: str, page_id: str):
    count = pipeline.remove_scanned_page(project(slug), page_id)
    return {"ok": True, "page": count}


@app.post("/book/{slug}/photos")
async def add_photos(slug: str, files: list[UploadFile]):
    proj = BookProject(slug)
    if not (proj.dir / "photos").is_dir():
        raise HTTPException(404)
    _save_photos(proj, files)
    jobs.submit(slug, "ocr", [])
    return RedirectResponse(f"/book/{slug}", status_code=303)


@app.get("/whoami")
def whoami(request: Request):
    u = request.state.user
    return {"login": u.login, "name": u.name, "is_owner": u.is_owner}


# --- book ----------------------------------------------------------------------

@app.get("/book/{slug}", response_class=HTMLResponse)
def book(request: Request, slug: str):
    proj = project(slug)
    is_photo_book = (proj.dir / "photos").is_dir()
    return templates.TemplateResponse(request, "book.html", {
        "slug": slug, "title": book_title(proj), "rows": chapter_rows(proj),
        "jobs": jobs.recent(slug), "cast": proj.load_cast(),
        "page_count": len(pipeline.scanned_pages(proj)) if is_photo_book else None,
    })


@app.post("/book/{slug}/delete")
def delete_book(slug: str):
    """Remove a book and everything made from it (text, scripts, audio). Owner-only via the middleware."""
    proj = project(slug)
    if jobs.active(slug):
        raise HTTPException(409, "Wait for this book's reading/voicing to finish before deleting it.")
    shutil.rmtree(proj.dir)
    return RedirectResponse("/", status_code=303)


@app.get("/book/{slug}/progress", response_class=HTMLResponse)
def progress(request: Request, slug: str):
    proj = project(slug)
    return templates.TemplateResponse(request, "_progress.html", {
        "slug": slug, "rows": chapter_rows(proj), "jobs": jobs.recent(slug),
    })


@app.post("/book/{slug}/jobs", response_class=HTMLResponse)
def start_job(request: Request, slug: str, kind: str = Form(...), chapters: str = Form("all")):
    proj = project(slug)
    if kind not in ("direct", "render"):
        raise HTTPException(400)
    rows = chapter_rows(proj)
    wanted = parse_chapters(chapters, rows, kind)
    if kind == "render":
        wanted = [n for n in wanted if proj.script_path(n).exists()]
    if wanted:
        jobs.submit(slug, kind, wanted)
    return progress(request, slug)


@app.get("/book/{slug}/audio/{n}.mp3")
def chapter_mp3(slug: str, n: int):
    path = project(slug).audio_path(n)
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="audio/mpeg")


# --- cast ----------------------------------------------------------------------

@app.get("/book/{slug}/cast", response_class=HTMLResponse)
def cast_page(request: Request, slug: str, saved: bool = False):
    proj = project(slug)
    cast = proj.load_cast()
    if not cast.narrator_voice or any(c.line_count and not c.voice for c in cast.characters):
        cast = auto_cast(cast, proj.all_scripts())  # fill in any voices that are missing
        proj.save_cast(cast)
    speaking = sorted([c for c in cast.characters if c.line_count], key=lambda c: -c.line_count)
    lexicon = Lexicon.load(proj.lexicon_path).entries
    eleven, eleven_error = pipeline.elevenlabs(), None
    eleven_voices, usage, usage_error = [], None, None
    if eleven:
        try:
            eleven_voices = eleven.voice_list()
        except Exception as e:
            eleven_error = str(e)
        try:
            usage = eleven.usage()
        except Exception as e:  # the meter is optional (keys can lack the user_read permission)
            usage_error = str(e)
    return templates.TemplateResponse(request, "cast.html", {
        "slug": slug, "title": book_title(proj), "cast": cast, "speaking": speaking, "saved": saved,
        "lexicon_text": "\n".join(f"{k} = {v}" for k, v in lexicon.items()),
        "eleven": bool(eleven), "eleven_error": eleven_error, "eleven_voices": eleven_voices,
        "usage_error": usage_error,
        "usage": usage, "estimate": pipeline.elevenlabs_estimate(proj) if eleven else None,
    })


@app.post("/book/{slug}/cast")
async def save_cast(request: Request, slug: str):
    proj = project(slug)
    form = await request.form()
    cast = proj.load_cast()
    was_split = cast.split_pov_voice
    cast.narrator_voice = form.get("narrator_voice") or cast.narrator_voice
    cast.unknown_voice = form.get("unknown_voice") or cast.unknown_voice
    cast.split_pov_voice = form.get("split_pov_voice") == "on"
    if "narrator_engine" in form:
        cast.narrator_engine = "elevenlabs" if form["narrator_engine"] == "elevenlabs" else "kokoro"
        cast.narrator_engine_voice = form.get("narrator_engine_voice") or cast.narrator_engine_voice
    for c in cast.characters:
        key = c.name
        if f"voice::{key}" in form:
            c.voice = form[f"voice::{key}"] or None
            c.gender = form.get(f"gender::{key}", c.gender)
            c.kind = form.get(f"kind::{key}", c.kind)
        if f"engine::{key}" in form:
            c.engine = "elevenlabs" if form[f"engine::{key}"] == "elevenlabs" else "kokoro"
            c.engine_voice = form.get(f"evoice::{key}") or c.engine_voice
    eleven = pipeline.elevenlabs()
    if eleven:
        taken = {c.engine_voice for c in cast.characters if c.engine == "elevenlabs" and c.engine_voice}
        if cast.narrator_engine == "elevenlabs" and not cast.narrator_engine_voice:
            pov = cast.find(cast.pov_character) if cast.pov_character else None
            cast.narrator_engine_voice = eleven.pick_voice(pov.gender if pov else "female", taken)
            taken.add(cast.narrator_engine_voice)
        for c in cast.characters:
            if c.engine == "elevenlabs" and not c.engine_voice:
                c.engine_voice = eleven.pick_voice("male" if c.kind == "dragon" else c.gender, taken)
                taken.add(c.engine_voice)
    pov = cast.find(cast.pov_character) if cast.pov_character else None
    if pov and cast.split_pov_voice and not was_split and pov.voice == cast.narrator_voice:
        pov.voice = None  # give the POV character their own voice
    proj.save_cast(auto_cast(cast, proj.all_scripts()))
    proj.lexicon_path.write_text(json.dumps(_parse_lexicon(form.get("lexicon", "")), indent=2, ensure_ascii=False))
    return RedirectResponse(f"/book/{slug}/cast?saved=1", status_code=303)


def _parse_lexicon(text: str) -> dict[str, str]:
    out = {}
    for row in text.splitlines():
        if "=" in row:
            word, spoken = (s.strip() for s in row.split("=", 1))
            if word and spoken:
                out[word] = spoken
    return out


PREVIEWS = store.LIBRARY / "_previews"


@app.get("/voice-preview")
def voice_preview(voice: str, name: str = "", engine: str = "kokoro"):
    text = (f"Hi, I'm {name}. " if name else "") + \
        "This is how I sound. I've waited a long time to tell you this story, so listen closely."
    if engine == "elevenlabs":
        tts = pipeline.elevenlabs()
        if not tts or voice not in tts.voices():
            raise HTTPException(400)
    elif voice in FEMALE_VOICES + MALE_VOICES:
        tts = pipeline.engine()
    else:
        raise HTTPException(400)
    # Previews are cached on disk, so an ElevenLabs sample is only paid for once.
    out = PREVIEWS / f"{engine}-{voice}-{hashlib.sha1(text.encode()).hexdigest()[:10]}.mp3"
    if not out.exists():
        export_mp3(tts.synth(text, voice), out)
    return FileResponse(out, media_type="audio/mpeg")


# --- script --------------------------------------------------------------------

@app.get("/book/{slug}/chapter/{n}", response_class=HTMLResponse)
def script_page(request: Request, slug: str, n: int):
    proj = project(slug)
    if not proj.script_path(n).exists():
        return RedirectResponse(f"/book/{slug}", status_code=303)
    chapters = {c.index: c for c in proj.load_chapters()}
    cast = proj.load_cast()
    lines = proj.load_script(n)
    speakers = sorted({c.name for c in cast.characters} | {l.speaker for l in lines} - {NARRATOR, "Unknown"})
    return templates.TemplateResponse(request, "script.html", {
        "slug": slug, "title": book_title(proj), "chapter": chapters[n], "lines": lines, "cast": cast,
        "speakers": speakers, "emotions": sorted(EMOTIONS), "types": LINE_TYPES,
        "prev": n - 1 if n - 1 in chapters else None, "next": n + 1 if n + 1 in chapters else None,
    })


@app.post("/book/{slug}/chapter/{n}/line/{line_id}", status_code=204)
async def edit_line(request: Request, slug: str, n: int, line_id: str):
    proj = project(slug)
    form = await request.form()
    lines = proj.load_script(n)
    line = next((l for l in lines if l.id == line_id), None)
    if not line:
        raise HTTPException(404)
    old_text = line.text
    for field in ("speaker", "type", "emotion", "text"):
        if field in form:
            setattr(line, field, str(form[field]).strip())
    if line.text != old_text:
        line.performance = None  # re-direct the performance for the new wording
    if line.type == "narration":
        line.speaker = NARRATOR
    elif line.speaker == NARRATOR:
        line.type = "narration"
    proj.save_script(n, lines)
    cast = proj.load_cast()
    if line.speaker not in (NARRATOR, "Unknown") and not cast.find(line.speaker):
        proj.save_cast(auto_cast(cast, proj.all_scripts()))  # a brand-new speaker needs a voice
    return Response(status_code=204)


@app.get("/book/{slug}/line/{n}/{line_id}.wav")
def line_audio(slug: str, n: int, line_id: str):
    proj = project(slug)
    line = next((l for l in proj.load_script(n) if l.id == line_id), None)
    if not line:
        raise HTTPException(404)
    renderer = Renderer(pipeline.engines(), proj.load_cast(), Lexicon.load(proj.lexicon_path), proj.cache_dir)
    buf = io.BytesIO()
    sf.write(buf, renderer.line_audio(line), 24_000, format="WAV")
    return Response(buf.getvalue(), media_type="audio/wav", headers={"Cache-Control": "no-store"})
