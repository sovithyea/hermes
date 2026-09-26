"""Photos of printed pages -> book text (with _italics_ kept), using Apple's on-device OCR.

Why not a vision LLM: tested qwen2.5-vl 7B at ~30 s/page (7+ hours for a long novel) and it
still dropped italics — which matter, because in many fantasy books italics are the ONLY
marker of telepathic speech. Apple Vision reads a page in <1 s; italics are then found by
measuring how much each word's letters lean (italic type slants ~10-15°).
"""

from __future__ import annotations

import logging
import re
import statistics
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

log = logging.getLogger(__name__)

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff"}
ITALIC_EXTRA_SLANT = 5.0   # italic type leans ~8-12° more than upright text; split the difference
INDENT_FRACTION = 0.025    # paragraph indent, as a fraction of page width
HEADING_RE = re.compile(r"^(chapter\b.*|prologue|epilogue|part\b.*|[a-z-]+|\d{1,3})$", re.IGNORECASE)
NUMBER_WORDS = {"one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
                "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
                "nineteen", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"}


@dataclass
class Word:
    text: str
    x0: float
    x1: float
    italic: bool = False


@dataclass
class Line:
    text: str
    x0: float  # left edge, 0..1 of page width
    x1: float
    y: float   # vertical centre, 0 = top
    h: float
    words: list[Word]


@dataclass
class Page:
    lines: list[Line]
    heading: str | None = None


# --- reading one photo --------------------------------------------------------

def read_photo(path: Path) -> Page:
    img = _load(path)
    with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
        img.save(tmp.name)
        lines = _vision_lines(tmp.name, img.size)
    page = _clean_page(lines)  # drop headers/page numbers first so they don't skew italic runs
    _mark_italics(page.lines, np.asarray(img.convert("L"), dtype=np.float32))
    return page


def _load(path: Path) -> Image.Image:
    if path.suffix.lower() in (".heic", ".heif"):
        from pillow_heif import register_heif_opener

        register_heif_opener()
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    if max(img.size) > 3000:  # phone photos are huge; this is plenty for OCR
        img.thumbnail((3000, 3000))
    return img


def _vision_lines(path: str, size: tuple[int, int]) -> list[Line]:
    import Vision
    from Foundation import NSURL, NSMakeRange

    handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(path), None)
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setUsesLanguageCorrection_(True)
    req.setRecognitionLanguages_(["en-US"])
    ok, err = handler.performRequests_error_([req], None)
    if not ok:
        raise RuntimeError(f"Apple Vision OCR failed: {err}")
    W, H = size
    raw = []
    for obs in req.results() or []:
        cand = obs.topCandidates_(1)[0]
        text = str(cand.string())
        words = []
        for m in re.finditer(r"\S+", text):
            wb, _ = cand.boundingBoxForRange_error_(NSMakeRange(m.start(), m.end() - m.start()), None)
            if wb is None:
                continue
            r = wb.boundingBox()
            words.append(Word(m.group(), r.origin.x, r.origin.x + r.size.width))
            words[-1]._box = (r.origin.x, 1 - r.origin.y - r.size.height, r.size.width, r.size.height)
        # Corners in pixels, y down. Vision's corners follow the text's own rotation.
        corners = [(pt.x * W, (1 - pt.y) * H) for pt in
                   (obs.topLeft(), obs.topRight(), obs.bottomLeft(), obs.bottomRight())]
        raw.append((text, corners, words))
    # Page tilt = typical angle of the text baselines (long lines are the most reliable).
    angles, weights = [], []
    for _, (tl, tr, bl, br), _ in raw:
        dx, dy = br[0] - bl[0], br[1] - bl[1]
        if dx > 0:
            angles.append(np.arctan2(dy, dx))
            weights.append(dx)
    theta = float(np.average(angles, weights=weights)) if angles else 0.0
    cos, sin = np.cos(-theta), np.sin(-theta)
    cx, cy = W / 2, H / 2

    def straighten(pt):  # rotate about the centre so baselines become horizontal
        x, y = pt[0] - cx, pt[1] - cy
        return (x * cos - y * sin + cx) / W, (x * sin + y * cos + cy) / H

    lines = []
    for text, (tl, tr, bl, br), words in raw:
        (x_tl, y_tl), (x_bl, y_bl), (x_tr, _), (x_br, _) = map(straighten, (tl, bl, tr, br))
        lines.append(Line(text, min(x_tl, x_bl), max(x_tr, x_br), (y_tl + y_bl) / 2, abs(y_bl - y_tl), words))
    lines.sort(key=lambda l: l.y)
    return lines


# --- italics --------------------------------------------------------------------

def word_slant(crop: np.ndarray) -> float | None:
    """Lean of the letters in degrees (positive = leaning right), by finding the shear that
    makes vertical strokes most vertical (sharpest column-sum profile)."""
    if crop.size == 0 or crop.shape[0] < 8 or crop.shape[1] < 8:
        return None
    ink = crop < (crop.mean() - 0.5 * crop.std())  # dark pixels = ink
    ys, xs = np.nonzero(ink)
    if len(xs) < 30:
        return None
    h = crop.shape[0]
    best, best_score = 0.0, -1.0
    for deg in np.arange(-20, 30.1, 1.0):
        shift = (h - 1 - ys) * np.tan(np.radians(deg))  # undo a lean of `deg`
        cols = np.round(xs - shift).astype(int)
        cols -= cols.min()
        score = float((np.bincount(cols) ** 2).sum())
        if score > best_score:
            best, best_score = float(deg), score
    return best


def _mark_italics(lines: list[Line], gray: np.ndarray) -> None:
    H, W = gray.shape
    words: list[Word] = [w for line in lines for w in line.words]
    measured: list[tuple[float | None, float, float]] = []  # (slant, weight, y)
    for line in lines:
        for w in line.words:
            x, y, bw, bh = w._box
            x0, x1 = int(x * W), int((x + bw) * W)
            y0, y1 = int(y * H), int((y + bh) * H)
            s = word_slant(gray[max(y0, 0):y1, max(x0, 0):x1])
            # Long words have many strokes, so their slant is trustworthy; "a", "I", "to" are not.
            weight = min(1.0, (x1 - x0) / (3.0 * max(y1 - y0, 1)))
            measured.append((s, weight, line.y))
    valid = [(s, y) for s, _, y in measured if s is not None]
    if len(valid) < 10:
        return
    # A tilted photo makes all text appear to lean, and a curved page varies that down the page:
    # compare each word with the typical slant of text near it.
    ys = np.array([y for _, y in valid])
    ss = np.array([s for s, _ in valid])
    diffs = []
    for s, wt, y in measured:
        if s is None:
            diffs.append((0.0, 0.0))
            continue
        near = ss[np.abs(ys - y) < 0.15]
        base = _roman_slant(near if len(near) >= 10 else ss)
        diffs.append((s - base - ITALIC_EXTRA_SLANT, wt))
    labels = _drop_short_runs(words, _viterbi(words, diffs))
    for w, italic in zip(words, labels):
        w.italic = italic
    for line in lines:
        line.text = _render_words(line.words)


def _roman_slant(slants: np.ndarray) -> float:
    """Typical slant of upright text, ignoring italic words (which lean further right)."""
    base = float(np.median(slants))
    for _ in range(5):
        upright = slants[slants < base + ITALIC_EXTRA_SLANT - 1]
        if len(upright) < 5:
            break
        base = float(np.median(upright))
    return base


MIN_ITALIC_RUN = 3  # shorter runs are emphasis (or noise) and don't change who is speaking


def _drop_short_runs(words: list[Word], labels: list[bool]) -> list[bool]:
    out, i = list(labels), 0
    while i < len(out):
        if out[i]:
            j = i
            while j < len(out) and out[j]:
                j += 1
            if j - i < MIN_ITALIC_RUN:
                out[i:j] = [False] * (j - i)
            i = j
        else:
            i += 1
    return out


SWITCH_COST_MIDSENTENCE = 9.0
SWITCH_COST_AT_PUNCTUATION = 1.0


def _viterbi(words: list[Word], diffs: list[tuple[float, float]]) -> list[bool]:
    """Label each word italic/roman. Evidence per word is (slant above threshold) x (reliability);
    changing style is cheap right after punctuation and expensive mid-sentence."""
    n = len(words)
    if n == 0:
        return []
    INF = float("inf")
    cost = [[0.0, 0.0] for _ in range(n)]  # [roman, italic]
    back = [[0, 0] for _ in range(n)]
    for i, (d, wt) in enumerate(diffs):
        emit = (max(0.0, d) * wt, max(0.0, -d) * wt)  # roman pays for positive evidence, italic for negative
        for state in (0, 1):
            if i == 0:
                cost[i][state] = emit[state]
                continue
            boundary = bool(re.search(r"[,.;:!?—”\"’)]$", words[i - 1].text)) or bool(re.match(r"^[“\"‘(]", words[i].text))
            sw = SWITCH_COST_AT_PUNCTUATION if boundary else SWITCH_COST_MIDSENTENCE
            stay, move = cost[i - 1][state], cost[i - 1][1 - state] + sw
            cost[i][state], back[i][state] = (stay, state) if stay <= move else (move, 1 - state)
            cost[i][state] += emit[state]
    state = 0 if cost[-1][0] <= cost[-1][1] else 1
    out = [False] * n
    for i in range(n - 1, -1, -1):
        out[i] = bool(state)
        state = back[i][state]
    return out


def _render_words(words: list[Word]) -> str:
    out, in_italic = [], False
    for w in words:
        t = w.text
        if w.italic and not in_italic:
            lead = re.match(r"^[“\"‘'(]*", t).group()
            t = lead + "_" + t[len(lead):]
            in_italic = True
        elif not w.italic and in_italic:
            out[-1] = _close(out[-1])
            in_italic = False
        out.append(t)
    if in_italic and out:
        out[-1] = _close(out[-1])
    return " ".join(out)


def _close(t: str) -> str:
    trail = re.search(r"[”\"’')]*$", t).group()
    return t[: len(t) - len(trail)] + "_" + trail if trail else t + "_"


# --- page cleanup ---------------------------------------------------------------

def _clean_page(lines: list[Line]) -> Page:
    lines = [l for l in lines if l.text.strip()]
    heading = None
    # Page number at the very top or bottom.
    for idx in (0, -1):
        if lines and re.fullmatch(r"\d{1,4}", lines[idx].text.strip().strip("_")):
            lines.pop(idx)
    # Running header: short, top line, mostly capitals, well above the next line.
    if len(lines) > 1 and _is_caps(lines[0].text) and len(lines[0].text) < 60 and lines[0].y < 0.2 and \
            not _looks_like_heading(_plain(lines[0].text)):
        lines.pop(0)
    # Chapter opener: a short heading line near the top, followed by a gap.
    if lines and lines[0].y < 0.35 and len(lines) > 1 and lines[1].y - lines[0].y > 2.2 * lines[0].h:
        cand = _plain(lines[0].text)
        if HEADING_RE.match(cand) and (not cand.isalpha() or cand.lower() in NUMBER_WORDS or
                                       cand.lower().startswith(("chapter", "prologue", "epilogue", "part"))):
            heading = cand.title() if cand.lower().startswith(("chapter", "part")) or cand.isalpha() else cand
            if heading.lower() in NUMBER_WORDS or heading.isdigit():
                heading = f"Chapter {heading}"  # bare "ONE" / "1" openers
            lines.pop(0)
    return Page(lines, heading)


def _looks_like_heading(s: str) -> bool:
    low = s.lower()
    return low in NUMBER_WORDS or low.isdigit() or low.startswith(("chapter", "prologue", "epilogue", "part "))


def _is_caps(s: str) -> bool:
    letters = [c for c in s if c.isalpha()]
    return bool(letters) and sum(c.isupper() for c in letters) / len(letters) > 0.8


def _plain(s: str) -> str:
    return s.replace("_", "").strip()


# --- pages -> text --------------------------------------------------------------

def page_paragraphs(page: Page) -> tuple[list[str], bool]:
    """Returns (paragraphs, first_is_continuation)."""
    lines = page.lines
    if not lines:
        return [], False
    # Line positions are already straightened (see _vision_lines), so the left margin is
    # simply where the flush-left lines start.
    xs = np.array([l.x0 for l in lines])
    width = statistics.median(l.x1 - l.x0 for l in lines) or 1.0
    indent = INDENT_FRACTION * (width / 0.8)
    margin = float(np.sort(xs)[max(0, int(0.05 * len(xs)))])
    right = float(np.percentile([l.x1 for l in lines], 80))
    resid = xs
    a, b = 0.0, 0.0

    paras: list[str] = []
    first_cont = False
    for i, (line, r) in enumerate(zip(lines, resid)):
        indented = r - margin > indent
        prev_short = i > 0 and lines[i - 1].x1 < right - 0.08
        new_para = indented or prev_short
        if new_para and i > 0 and _mid_sentence(lines[i - 1].text, line.text):
            new_para = False  # "...I have been / chosen by no one": a paragraph can't break mid-sentence
        text = line.text.strip()
        if i == 0:
            first_cont = not indented and not page.heading
            paras.append(text)
        elif new_para:
            paras.append(text)
        else:
            paras[-1] = _join(paras[-1], text)
    return paras, first_cont


def _mid_sentence(prev: str, cur: str) -> bool:
    return not re.search(r"[.!?:;—”\"’_)]\s*$", prev.strip()) and bool(re.match(r"^[_\"“]?[a-z]", cur.strip()))


def _join(a: str, b: str) -> str:
    if re.search(r"[A-Za-z]-$", a) and b[:1].islower():
        return a[:-1] + b  # re-join a hyphenated word
    return f"{a} {b}"


def ocr_page(path: Path) -> dict:
    """One photo -> {"heading", "paragraphs", "continues"} (JSON-friendly, so it can be cached)."""
    page = read_photo(path)
    paras, cont = page_paragraphs(page)
    return {"heading": page.heading, "paragraphs": paras, "continues": cont}


def assemble(pages: list[dict]) -> str:
    """Per-page OCR results (in page order) -> plain text: blank line between paragraphs,
    chapter headings on their own lines, italics as _underscores_."""
    blocks: list[str] = []
    for page in pages:
        paras = list(page["paragraphs"])
        if page["heading"]:
            blocks.append(page["heading"])
        elif page["continues"] and blocks and paras and not re.search(r"[.!?”\"_’]$", blocks[-1]):
            blocks[-1] = _join(blocks[-1], paras.pop(0))  # paragraph carried over from last page
        blocks.extend(paras)
    return fix_capital_i_names("\n\n".join(_fix_italic_joins(b) for b in blocks))


def photos_to_text(paths: list[Path], on_progress=None) -> str:
    pages = []
    for n, path in enumerate(paths, start=1):
        pages.append(ocr_page(path))
        if on_progress:
            on_progress(n, len(paths))
    return assemble(pages)


SPEECH_VERBS = r"(?:said|says|asked|asks|whispered|shouted|replied|called|snapped|murmured|muttered|" \
               r"added|answered|yelled|laughed|sighed|growled|hissed|told|nodded|smiled|grinned)"


def fix_capital_i_names(text: str) -> str:
    """OCR often reads a capital I as a lowercase l: 'Ione' -> 'lone', 'Imogen' -> 'lmogen'.
    A lowercase 'l…' word that ever appears as the subject of a speech verb is a misread name;
    fix it wherever it sits in a name-like position."""
    suspects = set(re.findall(rf"\b(l[a-z]+)\s+{SPEECH_VERBS}\b", text))
    for word in suspects:
        name = "I" + word[1:]
        # Before a speech verb, as a possessive, after a comma/quote, or at the start of a sentence.
        text = re.sub(rf"\b{word}(?=\s+{SPEECH_VERBS}\b|['’]s\b)", name, text)
        text = re.sub(rf"(^|[.!?”\"]\s+|,\s+|—){word}\b", lambda m: m.group(1) + name, text, flags=re.M)
    return text


def _fix_italic_joins(s: str) -> str:
    # An italic run that spans a line break renders as "_foo_ _bar_"; merge into "_foo bar_".
    return re.sub(r"_ _", " ", s)


def sort_photos(paths: list[Path]) -> list[Path]:
    """Phones name photos in shooting order (IMG_0001, IMG_0002…): natural-sort on the phone's name.
    Uploads are stored as '<upload position>-<phone name>'; the position breaks ties (e.g. every
    file called 'image.jpg')."""
    def key(p: Path):
        m = re.match(r"^(\d{5})-(.*)$", p.name)
        pos, name = (int(m.group(1)), m.group(2)) if m else (0, p.name)
        return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)] + [pos]
    return sorted((p for p in paths if p.suffix.lower() in IMAGE_SUFFIXES), key=key)
