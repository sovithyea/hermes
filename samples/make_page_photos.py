"""Turn the test story into fake phone photos of printed pages, for testing photo import.

    uv run python samples/make_page_photos.py <out_dir>   # writes page HTML; screenshot + photo-ify below

Layout mimics a trade paperback: running header, page number, chapter opener, justified text,
italics, and paragraphs that continue across page breaks. Step 2 (photoify) adds tilt, blur,
uneven lighting and noise.
"""

import html
import random
import re
import sys
from pathlib import Path

from build_test_book import CHAPTERS

WORDS_PER_PAGE = 210
FIRST_PAGE_WORDS = 130


def paragraphs(body: str) -> list[str]:
    return re.findall(r"<p>(.*?)</p>", body, re.S)


def paginate() -> list[dict]:
    pages, page_no = [], 1
    for title, body in CHAPTERS:
        budget, cur, first = FIRST_PAGE_WORDS, [], True
        for para in paragraphs(body):
            words = para.split(" ")
            continued = False
            while words:
                used = sum(len(re.sub("<[^>]+>", "", p).split()) for p, _ in cur)
                room = budget - used
                if len(words) <= room:
                    cur.append((" ".join(words), continued))
                    words = []
                else:
                    if room > 8:
                        take = _safe_split(words, room)
                        cur.append((" ".join(words[:take]), continued))
                        words, continued = words[take:], True
                    pages.append({"no": page_no, "title": title if first else None, "paras": cur, "ends_mid": bool(words)})
                    page_no, cur, first, budget = page_no + 1, [], False, WORDS_PER_PAGE
        pages.append({"no": page_no, "title": title if first else None, "paras": cur, "ends_mid": False})
        page_no += 1
    return pages


def _safe_split(words: list[str], n: int) -> int:
    # Don't split inside an <em>…</em> run, or the HTML breaks.
    depth = 0
    last_ok = 0
    for i, w in enumerate(words[:n]):
        depth += w.count("<em>") - w.count("</em>")
        if depth == 0:
            last_ok = i + 1
    return max(last_ok, 1)


PAGE_CSS = """
body { margin: 0; background: #fbf8f1; }
.page { width: 560px; height: 860px; padding: 56px 58px; box-sizing: border-box; position: relative;
        font: 15.5px/1.5 'Iowan Old Style', Georgia, serif; color: #1d1a16; background: #fbf8f1; }
.run { text-align: center; font-size: 11px; letter-spacing: 0.25em; color: #555; margin-bottom: 26px; }
.no { position: absolute; bottom: 36px; left: 0; right: 0; text-align: center; font-size: 12px; color: #444; }
h1 { text-align: center; font-weight: normal; letter-spacing: 0.2em; font-size: 20px; margin: 70px 0 40px; }
p { margin: 0; text-indent: 1.6em; text-align: justify; hyphens: auto; }
p.cont, h1 + p { text-indent: 0; }
"""


def page_html(page: dict) -> str:
    parts = [f"<html><head><style>{PAGE_CSS}</style></head><body><div class='page'>"]
    if page["title"]:
        parts.append(f"<h1>{html.escape(page['title'].upper())}</h1>")
    else:
        header = "THE BLACK DRAGON'S CHOICE" if page["no"] % 2 else "REBECCA TESTWRITER"
        parts.append(f"<div class='run'>{header}</div>")
    for text, cont in page["paras"]:
        parts.append(f"<p class='{'cont' if cont else ''}'>{text}</p>")
    parts.append(f"<div class='no'>{page['no']}</div></div></body></html>")
    return "".join(parts)


def photoify(src: Path, dst: Path, seed: int) -> None:
    """Make a clean render look like a handheld phone photo."""
    from PIL import Image, ImageFilter, ImageDraw
    import numpy as np

    rnd = random.Random(seed)
    img = Image.open(src).convert("RGB")
    w, h = img.size
    # Desk/background border, then tilt.
    canvas = Image.new("RGB", (int(w * 1.15), int(h * 1.12)), (84, 70, 58))
    canvas.paste(img, (int(w * 0.07), int(h * 0.05)))
    canvas = canvas.rotate(rnd.uniform(-3.5, 3.5), resample=Image.BICUBIC, fillcolor=(84, 70, 58))
    # Uneven lighting: a soft shadow from one side.
    shade = Image.new("L", canvas.size, 0)
    d = ImageDraw.Draw(shade)
    for i in range(0, canvas.size[0], 4):
        d.line([(i, 0), (i, canvas.size[1])], fill=int(70 * max(0, 1 - i / (canvas.size[0] * 0.55))))
    canvas = Image.composite(Image.new("RGB", canvas.size, (0, 0, 0)), canvas, shade.filter(ImageFilter.GaussianBlur(40)))
    canvas = canvas.filter(ImageFilter.GaussianBlur(rnd.uniform(0.6, 1.1)))
    arr = np.asarray(canvas).astype(np.int16)
    arr += np.random.default_rng(seed).normal(0, 6, arr.shape).astype(np.int16)
    Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).save(dst, quality=82)


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    if len(sys.argv) > 2 and sys.argv[2] == "photoify":
        for i, png in enumerate(sorted(out.glob("page-*.png"))):
            photoify(png, out / png.with_suffix(".jpg").name.replace("page-", "IMG_"), seed=i)
        print("photos done")
    else:
        pages = paginate()
        for p in pages:
            (out / f"page-{p['no']:03d}.html").write_text(page_html(p), encoding="utf-8")
        print(len(pages), "pages")
