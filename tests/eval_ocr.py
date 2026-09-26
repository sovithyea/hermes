"""Compare OCR of the fake page photos against the original test-story text.

    uv run python samples/make_page_photos.py <dir> ; (screenshot pages) ; ... photoify
    uv run python tests/eval_ocr.py <dir>
"""
import difflib
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "samples"))
from build_test_book import CHAPTERS  # noqa: E402

from hermes.ocr import photos_to_text, sort_photos  # noqa: E402

gold_blocks = []
for title, body in CHAPTERS:
    gold_blocks.append(title)
    for p in re.findall(r"<p>(.*?)</p>", body, re.S):
        gold_blocks.append(re.sub(r"</?em>", "_", p).replace("_ _", " "))

d = Path(sys.argv[1])
t = time.time()
text = photos_to_text(sort_photos(list(d.glob("IMG_*.jpg"))))
print(f"OCR {len(list(d.glob('IMG_*.jpg')))} pages in {time.time() - t:.1f}s")
got_blocks = text.split("\n\n")
print(f"paragraphs: got {len(got_blocks)}, want {len(gold_blocks)}")

norm = lambda s: re.sub(r"[‘’']", "'", re.sub(r"[“”\"]", '"', s))
gw, ow = norm(" ".join(gold_blocks).replace("_", "")).split(), norm(" ".join(got_blocks).replace("_", "")).split()
print(f"word accuracy: {difflib.SequenceMatcher(None, gw, ow).ratio():.1%}")

gi = [norm(m) for b in gold_blocks for m in re.findall(r"_([^_]+)_", b) if len(m.split()) >= 3]
oi = [norm(m) for b in got_blocks for m in re.findall(r"_([^_]+)_", b)]
hit = [g for g in gi if any(difflib.SequenceMatcher(None, g, o).ratio() > 0.9 for o in oi)]
print(f"italic spans found: {len(hit)}/{len(gi)}; spurious italic spans: "
      f"{sum(1 for o in oi if not any(difflib.SequenceMatcher(None, g, o).ratio() > 0.9 for g in gi))}")
for g in gi:
    if g not in hit:
        print("  MISSED:", g)
for o in oi:
    if not any(difflib.SequenceMatcher(None, g, o).ratio() > 0.9 for g in gi):
        print("  SPURIOUS:", o)
sm = difflib.SequenceMatcher(None, [norm(b) for b in gold_blocks], [norm(b) for b in got_blocks])
for op, a1, a2, b1, b2 in sm.get_opcodes():
    if op != "equal":
        for b in gold_blocks[a1:a2]: print("  - want:", b[:90])
        for b in got_blocks[b1:b2]: print("  + got: ", b[:90])
