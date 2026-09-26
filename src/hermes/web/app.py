"""Hermes web app: upload a book, fix the cast and script, generate and listen.

    uv run hermes serve        # http://localhost:8000
"""

from __future__ import annotations

import hashlib
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
from ..store import LIBRARY, BookProject
from ..tts.kokoro_engine import FEMALE_VOICES, MALE_VOICES
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
    if LIBRARY.exists():
        for d in sorted(LIBRARY.iterdir()):
            if (d / "chapters.json").exists():
                proj = BookProject(d.name)
                rows = chapter_rows(proj)
                books.append({"slug": d.name, "title": book_title(proj), "chapters": len(rows),
                              "done": sum(r["status"] == "done" for r in rows)})
    return templates.TemplateResponse(request, "library.html", {"books": books})


@app.post("/upload")
async def upload(file: UploadFile):
    suffix = Path(file.filename or "book.epub").suffix.lower()
    if suffix not in (".epub", ".pdf", ".txt"):
        raise HTTPException(400, "Please upload an EPUB, PDF or TXT file.")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / Path(file.filename).name
        with path.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        try:
            proj = pipeline.ingest(path)
        except ValueError as e:
            raise HTTPException(400, str(e))
    return RedirectResponse(f"/book/{proj.slug}", status_code=303)


# --- book ----------------------------------------------------------------------

@app.get("/book/{slug}", response_class=HTMLResponse)
def book(request: Request, slug: str):
    proj = project(slug)
    return templates.TemplateResponse(request, "book.html", {
        "slug": slug, "title": book_title(proj), "rows": chapter_rows(proj),
        "jobs": jobs.recent(slug), "cast": proj.load_cast(),
    })


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
    speaking = sorted([c for c in cast.characters if c.line_count], key=lambda c: -c.line_count)
    lexicon = Lexicon.load(proj.lexicon_path).entries
    return templates.TemplateResponse(request, "cast.html", {
        "slug": slug, "title": book_title(proj), "cast": cast, "speaking": speaking, "saved": saved,
        "lexicon_text": "\n".join(f"{k} = {v}" for k, v in lexicon.items()),
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
    for c in cast.characters:
        key = c.name
        if f"voice::{key}" in form:
            c.voice = form[f"voice::{key}"] or None
            c.gender = form.get(f"gender::{key}", c.gender)
            c.kind = form.get(f"kind::{key}", c.kind)
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


PREVIEWS = LIBRARY / "_previews"


@app.get("/voice-preview")
def voice_preview(voice: str, name: str = ""):
    if voice not in FEMALE_VOICES + MALE_VOICES:
        raise HTTPException(400)
    text = (f"Hi, I'm {name}. " if name else "") + \
        "This is how I sound. I've waited a long time to tell you this story, so listen closely."
    out = PREVIEWS / f"{voice}-{hashlib.sha1(text.encode()).hexdigest()[:10]}.mp3"
    if not out.exists():
        export_mp3(pipeline.engine().synth(text, voice), out)
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
    for field in ("speaker", "type", "emotion", "text"):
        if field in form:
            setattr(line, field, str(form[field]).strip())
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
    renderer = Renderer(pipeline.engine(), proj.load_cast(), Lexicon.load(proj.lexicon_path), proj.cache_dir)
    buf = io.BytesIO()
    sf.write(buf, renderer.line_audio(line), 24_000, format="WAV")
    return Response(buf.getvalue(), media_type="audio/wav", headers={"Cache-Control": "no-store"})
