"""hermes ingest | direct | show"""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from . import director
from .ingest import load_book
from .store import BookProject

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


@app.callback()
def _main(verbose: bool = typer.Option(False, "-v", "--verbose")) -> None:
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING, format="%(levelname)s %(message)s")


@app.command()
def ingest(path: Path) -> None:
    """Import a book (EPUB/PDF/TXT) into the library."""
    chapters = load_book(path)
    proj = BookProject.create(path)
    proj.save_chapters(chapters)
    table = Table("#", "Title", "Words")
    for c in chapters:
        table.add_row(str(c.index), c.title[:60], f"{c.word_count:,}")
    console.print(table)
    console.print(f"[green]Saved {len(chapters)} chapters to[/] {proj.dir}  (slug: [bold]{proj.slug}[/])")


@app.command()
def direct(
    slug: str,
    chapter: list[int] = typer.Option(..., "--chapter", "-c", help="Chapter number(s) to process"),
    model: str = typer.Option(director.DEFAULT_MODEL, help="Ollama model"),
    think: bool = typer.Option(False, help="Let the model reason first (slower, more accurate)"),
) -> None:
    """Run the director (speaker + emotion labelling) on chapters."""
    proj = BookProject(slug)
    chapters = {c.index: c for c in proj.load_chapters()}
    cast = proj.load_cast()
    with Progress(console=console) as progress:
        for n in chapter:
            task = progress.add_task(f"Chapter {n}", total=None)
            lines = director.direct_chapter(
                chapters[n], cast, model,
                on_progress=lambda done, total: progress.update(task, completed=done, total=total),
                think=think,
            )
            proj.save_script(n, lines)
            proj.save_cast(cast)
    console.print(f"[green]Done.[/] Cast now has {len(cast.characters)} characters.")


@app.command()
def show(slug: str, chapter: int = typer.Option(..., "--chapter", "-c"), all_lines: bool = False) -> None:
    """Print a chapter's script (dialogue only unless --all-lines) and speaker counts."""
    proj = BookProject(slug)
    lines = proj.load_script(chapter)
    for l in lines:
        if l.type == "narration" and not all_lines:
            continue
        colour = "dim" if l.type == "narration" else ("magenta" if l.type == "mindspeech" else "cyan")
        console.print(f"[{colour}]{l.id} {l.speaker:>14} ({l.type}, {l.emotion})[/] {l.text}")
    counts = Counter(l.speaker for l in lines if l.type != "narration")
    console.print("\n[bold]Speaker counts:[/]", dict(counts.most_common()))
    cast = proj.load_cast()
    console.print(f"[bold]POV:[/] {cast.pov_character}")
