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
from .store import BookProject

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


@app.callback()
def _main(verbose: bool = typer.Option(False, "-v", "--verbose")) -> None:
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING, format="%(levelname)s %(message)s")


@app.command()
def ingest(path: Path) -> None:
    """Import a book (EPUB/PDF/TXT) into the library."""
    from . import pipeline

    proj = pipeline.ingest(path)
    chapters = proj.load_chapters()
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
    """Run the director (speaker + emotion labelling) on chapters, then assign voices."""
    from . import pipeline

    proj = BookProject(slug)
    with Progress(console=console) as progress:
        task = progress.add_task("Reading", total=None)
        pipeline.direct(proj, chapter, lambda done, total, msg: progress.update(
            task, completed=done, total=total, description=msg), model=model, think=think)
    console.print(f"[green]Done.[/] Cast now has {len(proj.load_cast().characters)} characters.")


@app.command("cast")
def cast_cmd(slug: str) -> None:
    """Assign voices to every speaking character (keeps voices you've set by hand)."""
    from .casting import auto_cast

    proj = BookProject(slug)
    cast = auto_cast(proj.load_cast(), proj.all_scripts())
    proj.save_cast(cast)
    table = Table("Character", "Lines", "Voice", "Kind")
    table.add_row("[bold]Narrator[/]", "", cast.narrator_voice, "")
    for c in sorted(cast.characters, key=lambda c: -c.line_count):
        if c.line_count:
            table.add_row(c.name, str(c.line_count), c.voice or "-", c.kind)
    table.add_row("[dim]Unknown[/]", "", cast.unknown_voice, "")
    console.print(table)
    if cast.pov_character:
        console.print(f"POV character [bold]{cast.pov_character}[/] shares the narrator voice"
                      + (" (split)" if cast.split_pov_voice else ""))


@app.command()
def render(slug: str, chapter: list[int] = typer.Option(..., "--chapter", "-c")) -> None:
    """Generate the MP3 for chapters (only changed lines are re-synthesised)."""
    import time

    from . import pipeline

    proj = BookProject(slug)
    start = time.time()
    with Progress(console=console) as progress:
        task = progress.add_task("Voicing", total=None)
        stats = pipeline.render(proj, chapter, lambda done, total, msg: progress.update(
            task, completed=done, total=total, description=msg))
    for n in chapter:
        console.print(f"  → {proj.audio_path(n)}")
    console.print(f"[green]Rendered {stats.seconds / 60:.1f} min of audio in {time.time() - start:.0f}s[/] "
                  f"({stats.cache_hits}/{stats.lines} lines from cache)")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Start the web app (open http://localhost:8000)."""
    import uvicorn

    console.print(f"[green]Hermes is running →[/] http://{'localhost' if host == '127.0.0.1' else host}:{port}")
    uvicorn.run("hermes.web.app:app", host=host, port=port, log_level="warning")


@app.command()
def say(text: str, voice: str = "af_heart", emotion: str = "neutral", out: Path = Path("say.mp3")) -> None:
    """Preview a voice: hermes say "Hello there" --voice am_fenrir"""
    from .render import export_mp3
    from .tts.base import EMOTION_PROSODY, Prosody
    from .tts.kokoro_engine import KokoroEngine

    p = EMOTION_PROSODY.get(emotion, Prosody())
    audio = KokoroEngine().synth(text, voice, p.speed) * (10 ** (p.gain_db / 20))
    console.print(f"Saved {export_mp3(audio, out)}")


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
