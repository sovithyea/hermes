"""A single background worker: the LLM and the voice model both want the whole GPU, so jobs run one at a time."""

from __future__ import annotations

import itertools
import logging
import queue
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Literal

from .. import pipeline
from ..store import BookProject

log = logging.getLogger(__name__)

JobKind = Literal["ocr", "direct", "render"]


@dataclass
class Job:
    id: int
    slug: str
    kind: JobKind
    chapters: list[int]
    status: Literal["queued", "running", "done", "error"] = "queued"
    done: int = 0
    total: int = 1
    message: str = "Waiting…"
    error: str = ""
    created: float = field(default_factory=time.time)

    @property
    def percent(self) -> int:
        return int(100 * self.done / max(self.total, 1))

    @property
    def label(self) -> str:
        if self.kind == "ocr":
            return "Reading page photos"
        what = "Reading" if self.kind == "direct" else "Voicing"
        chs = self.chapters
        span = f"chapter {chs[0]}" if len(chs) == 1 else f"{len(chs)} chapters"
        return f"{what} {span}"


class JobQueue:
    def __init__(self):
        self.jobs: dict[int, Job] = {}
        self._ids = itertools.count(1)
        self._q: queue.Queue[Job] = queue.Queue()
        threading.Thread(target=self._worker, daemon=True, name="hermes-worker").start()

    def submit(self, slug: str, kind: JobKind, chapters: list[int]) -> Job | None:
        # Skip chapters already waiting for the same work.
        if kind == "ocr":
            if any(j.kind == "ocr" and j.status == "queued" for j in self.active(slug)):
                return None  # a queued OCR run will pick up the new photos anyway
        else:
            pending = {c for j in self.active(slug) if j.kind == kind for c in j.chapters}
            chapters = [c for c in chapters if c not in pending]
            if not chapters:
                return None
        job = Job(next(self._ids), slug, kind, chapters)
        self.jobs[job.id] = job
        self._q.put(job)
        return job

    def active(self, slug: str) -> list[Job]:
        return [j for j in self.jobs.values() if j.slug == slug and j.status in ("queued", "running")]

    def recent(self, slug: str, seconds: float = 30) -> list[Job]:
        now = time.time()
        return [j for j in self.jobs.values() if j.slug == slug and
                (j.status in ("queued", "running") or now - j.created < seconds or j.status == "error")]

    def busy_chapters(self, slug: str) -> dict[int, str]:
        return {c: j.kind for j in self.active(slug) for c in j.chapters}

    def _worker(self) -> None:
        while True:
            job = self._q.get()
            job.status, job.message = "running", "Starting…"

            def progress(done: int, total: int, message: str, job=job) -> None:
                job.done, job.total, job.message = done, total, message

            try:
                proj = BookProject(job.slug)
                if job.kind == "ocr":
                    pipeline.ocr_photos(proj, progress)
                elif job.kind == "direct":
                    pipeline.direct(proj, job.chapters, progress)
                else:
                    pipeline.render(proj, job.chapters, progress)
                job.status, job.done, job.message = "done", job.total, "Finished"
            except Exception as e:  # surface any failure in the UI rather than killing the worker
                log.error("job %s failed:\n%s", job.id, traceback.format_exc())
                job.status, job.error = "error", f"{type(e).__name__}: {e}"
