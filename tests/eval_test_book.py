"""Speaker accuracy on the original test story (samples/build_test_book.py).

    uv run hermes ingest samples/black-dragons-choice.epub
    uv run hermes direct black-dragons-choice -c 1 -c 2
    uv run python tests/eval_test_book.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "samples"))
from build_test_book import GOLD  # noqa: E402

from hermes.store import BookProject  # noqa: E402

proj = BookProject("black-dragons-choice")
cast = proj.load_cast()
main = {"Maren", "Ione", "Brask", "Kael", "Skarth", "Professor Hale"}


def matches(got: str, gold: str) -> bool:
    c = cast.find(got)
    names = [got] + ([c.name, *c.aliases] if c else [])
    if gold == "Unknown":
        return not any(m.lower() in n.lower() for n in names for m in main)
    key = gold.split()[-1].lower()  # "Professor Hale" -> "hale"
    return any(key in n.lower() for n in names)


total = right = 0
for ch, gold in GOLD.items():
    lines = [l for l in proj.load_script(ch) if l.type != "narration"]
    if len(lines) != len(gold):
        print(f"ch{ch}: expected {len(gold)} spoken lines, got {len(lines)}")
    for l, g in zip(lines, gold):
        total += 1
        if matches(l.speaker, g):
            right += 1
        else:
            print(f"  WRONG {l.id} got={l.speaker!r} want={g!r} ({l.type}) {l.text[:50]}")
print(f"{right}/{total} correct   POV={cast.pov_character!r}")
