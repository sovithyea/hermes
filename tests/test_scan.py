import hermes.ocr as ocr
from hermes import pipeline
from hermes.store import BookProject


def fake_pages(monkeypatch, pages):
    """ocr_page returns the next canned page; records which photo files existed when read."""
    seen = []

    def fake(path):
        seen.append(path.exists())
        return pages.pop(0)
    monkeypatch.setattr(ocr, "ocr_page", fake)
    return seen


def page(text, heading=None, cont=False):
    return {"heading": heading, "paragraphs": [text], "continues": cont}


LONG = " ".join(f"w{i}" for i in range(40))
OTHER = " ".join(f"x{i}" for i in range(40))


def test_scanning_reads_deletes_photos_and_rejects_bad_shots(tmp_path, monkeypatch):
    monkeypatch.setattr("hermes.store.LIBRARY", tmp_path)
    proj = BookProject("book", tmp_path)
    (proj.dir / "photos").mkdir(parents=True)
    proj.save_chapters([])
    seen = fake_pages(monkeypatch, [
        page("Chapter text " + LONG, heading="Chapter One"),
        page("Chapter text " + LONG, heading="Chapter One"),  # same page twice
        page("blurry"),                                        # unreadable
        page("more text " + OTHER),
    ])
    results = [pipeline.add_scanned_page(proj, b"jpeg") for _ in range(4)]
    assert [r["ok"] for r in results] == [True, False, False, True]
    assert [r.get("reason") for r in results] == [None, "duplicate", "unreadable", None]
    assert all(seen)                                            # photo existed while being read…
    assert not [p for p in (proj.dir / "photos").iterdir() if p.is_file()]  # …and is gone after
    chapters = proj.load_chapters()
    assert [c.title for c in chapters] == ["Chapter One"] and chapters[0].word_count > 80

    pipeline.remove_scanned_page(proj, results[3]["id"])
    assert len(pipeline.scanned_pages(proj)) == 1
