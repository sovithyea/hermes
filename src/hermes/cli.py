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
def photos(folder: Path, title: str = typer.Option(..., help="Book title")) -> None:
    """Import photos of printed pages (a folder of JPG/PNG/HEIC, in shooting order)."""
    import shutil

    from . import pipeline
    from .ocr import sort_photos

    proj = pipeline.create_photo_book(title)
    for i, src in enumerate(sort_photos(list(folder.iterdir()))):
        shutil.copyfile(src, proj.dir / "photos" / f"{i:05d}-{src.name}")
    with Progress(console=console) as progress:
        task = progress.add_task("Reading pages", total=None)
        pages = pipeline.ocr_photos(proj, lambda d, t, m: progress.update(task, completed=d, total=t))
    table = Table("#", "Title", "Words")
    for c in proj.load_chapters():
        table.add_row(str(c.index), c.title[:60], f"{c.word_count:,}")
    console.print(table)
    console.print(f"[green]Read {pages} pages into[/] {proj.dir}  (slug: [bold]{proj.slug}[/])")
    console.print(f"Check the text: {proj.dir / 'source.txt'}")


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
def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
    phone: bool = typer.Option(False, "--phone", help="Let phones on the same Wi-Fi connect (to scan pages)"),
    tailscale: bool = typer.Option(False, "--tailscale",
                                   help="Private https link via Tailscale: works from anywhere, only for your tailnet"),
) -> None:
    """Start the web app (open http://localhost:8000)."""
    import os

    import uvicorn

    if tailscale:
        base = _tailscale_https(port)
        os.environ["HERMES_PHONE_BASE"] = base
        console.print(f"[green]Hermes is running →[/] http://localhost:{port}   (private link: {base})")
        console.print("[dim]Only devices signed in to your Tailscale (or ones you share this Mac with) can open it.[/]")
    elif phone:
        host = "0.0.0.0"
        base = f"http://{_lan_ip()}:{port}"
        os.environ["HERMES_PHONE_BASE"] = base
        console.print(f"[green]Hermes is running →[/] http://localhost:{port}   (phones on this Wi-Fi: {base})")
        console.print("[dim]Anyone on this Wi-Fi network can open it while it runs.[/]")
    else:
        console.print(f"[green]Hermes is running →[/] http://{'localhost' if host == '127.0.0.1' else host}:{port}")
    uvicorn.run("hermes.web.app:app", host=host, port=port, log_level="warning")


TAILSCALE = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"


def _tailscale_https(port: int) -> str:
    """Point Tailscale's private https address at the app (the app itself stays on localhost)."""
    import json
    import shutil
    import subprocess

    exe = shutil.which("tailscale") or TAILSCALE
    try:
        status = json.loads(subprocess.run([exe, "status", "--json"], capture_output=True, text=True,
                                           timeout=10).stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise typer.BadParameter("Tailscale isn't running. Open the Tailscale app and log in.")
    name = (status.get("Self") or {}).get("DNSName", "").rstrip(".")
    if not name:
        raise typer.BadParameter("Tailscale isn't logged in. Open the Tailscale app and log in.")
    proc = subprocess.run([exe, "serve", "--bg", "--https=443", f"http://127.0.0.1:{port}"],
                          capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise typer.BadParameter("Tailscale couldn't publish the https link:\n" + (proc.stdout + proc.stderr).strip())
    return f"https://{name}"


def _lan_ip() -> str:
    """This Mac's Wi-Fi/Ethernet address. Asks macOS for the physical interfaces first, because
    VPNs such as Tailscale otherwise win the route lookup and phones on the Wi-Fi can't reach that."""
    import socket
    import subprocess

    for iface in ("en0", "en1"):
        try:
            ip = subprocess.run(["ipconfig", "getifaddr", iface], capture_output=True, text=True, timeout=2).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            ip = ""
        if ip:
            return ip

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


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
