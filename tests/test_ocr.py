from pathlib import Path

from hermes.ocr import Word, _drop_short_runs, _mid_sentence, _render_words, _viterbi, fix_capital_i_names, sort_photos


def words(text):
    return [Word(t, 0, 0) for t in text.split()]


def test_viterbi_keeps_noisy_word_inside_italic_run():
    ws = words("I said. You are smaller than expected.")
    # "You" measures as upright (noise) but its neighbours are clearly italic.
    diffs = [(-5, 0.3), (-5, 1), (-2, 0.4), (3, 0.5), (4, 1), (4, 1), (4, 1)]
    assert _viterbi(ws, diffs) == [False, False, True, True, True, True, True]


def test_short_italic_runs_are_dropped():
    ws = words("a b c d e")
    assert _drop_short_runs(ws, [True, True, False, True, True]) == [False] * 5
    assert _drop_short_runs(ws, [False, True, True, True, False]) == [False, True, True, True, False]


def test_render_words_puts_markers_inside_quotes():
    ws = words("“Get up,” she said. Hold on, Silver One.")
    for w, it in zip(ws, [True, True, False, False, True, True, True, True]):
        w.italic = it
    assert _render_words(ws) == "“_Get up,_” she said. _Hold on, Silver One._"


def test_mid_sentence_detection():
    assert _mid_sentence("the dragon said. And that I have been", "chosen by no one.")
    assert not _mid_sentence("I do the choosing.", "I swallowed hard")


def test_capital_i_names():
    text = "“Maren,” lone whispered. lone’s hand shook. A lone rider waited."
    assert fix_capital_i_names(text) == "“Maren,” Ione whispered. Ione’s hand shook. A lone rider waited."


def test_sort_photos_uses_phone_names_then_upload_order():
    by_name = ["00002-IMG_0010.jpg", "00000-IMG_0009.jpg", "00001-IMG_0100.jpg"]
    assert [p.name for p in sort_photos([Path(n) for n in by_name])] == [
        "00000-IMG_0009.jpg", "00002-IMG_0010.jpg", "00001-IMG_0100.jpg"]
    same_name = ["00004-image.jpg", "00003-image.jpg", "00005-notes.txt"]
    assert [p.name for p in sort_photos([Path(n) for n in same_name])] == ["00003-image.jpg", "00004-image.jpg"]
