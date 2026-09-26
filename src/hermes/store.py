"""Per-book project folder under library/<slug>/.

library/<slug>/
  source.<ext>        original upload
  chapters.json       ingested chapter text
  cast.json           character bible (editable)
  script/ch001.json   director output per chapter (editable)
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from .ingest import Chapter
from .models import Cast, ScriptLine

LIBRARY = Path(__file__).resolve().parents[2] / "library"


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "book"


class BookProject:
    def __init__(self, slug: str, root: Path = LIBRARY):
        self.slug = slug
        self.dir = root / slug

    @classmethod
    def create(cls, source: Path, root: Path = LIBRARY) -> "BookProject":
        proj = cls(slugify(source.stem), root)
        proj.dir.mkdir(parents=True, exist_ok=True)
        dest = proj.dir / f"source{source.suffix.lower()}"
        if source.resolve() != dest.resolve():
            shutil.copyfile(source, dest)
        return proj

    # chapters
    def save_chapters(self, chapters: list[Chapter]) -> None:
        data = [{"index": c.index, "title": c.title, "paragraphs": c.paragraphs} for c in chapters]
        _write_json(self.dir / "chapters.json", data)

    def load_chapters(self) -> list[Chapter]:
        return [Chapter(**d) for d in _read_json(self.dir / "chapters.json")]

    # cast
    def load_cast(self) -> Cast:
        path = self.dir / "cast.json"
        return Cast.model_validate(_read_json(path)) if path.exists() else Cast()

    def save_cast(self, cast: Cast) -> None:
        _write_json(self.dir / "cast.json", cast.model_dump())

    # script
    def script_path(self, chapter: int) -> Path:
        return self.dir / "script" / f"ch{chapter:03d}.json"

    def save_script(self, chapter: int, lines: list[ScriptLine]) -> None:
        _write_json(self.script_path(chapter), [l.model_dump() for l in lines])

    def load_script(self, chapter: int) -> list[ScriptLine]:
        return [ScriptLine.model_validate(d) for d in _read_json(self.script_path(chapter))]

    def directed_chapters(self) -> list[int]:
        return sorted(int(p.stem[2:]) for p in (self.dir / "script").glob("ch*.json"))

    def all_scripts(self) -> list[list[ScriptLine]]:
        return [self.load_script(n) for n in self.directed_chapters()]

    # audio
    @property
    def lexicon_path(self) -> Path:
        return self.dir / "lexicon.json"

    @property
    def cache_dir(self) -> Path:
        return self.dir / "cache"

    def audio_path(self, chapter: int) -> Path:
        return self.dir / "audio" / f"ch{chapter:03d}.mp3"

    def save_render_info(self, chapter: int, info: dict) -> None:
        _write_json(self.audio_path(chapter).with_suffix(".json"), info)

    def load_render_info(self, chapter: int) -> dict | None:
        path = self.audio_path(chapter).with_suffix(".json")
        return _read_json(path) if path.exists() else None


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))
