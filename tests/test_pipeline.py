from hermes.director import _chunk, parse_output
from hermes.ingest import html_to_chapters
from hermes.models import Cast, Character
from hermes.segment import segment_paragraphs


def test_segments_split_quotes_and_long_italics():
    segs = segment_paragraphs([
        "“Get up,” Xaden said. _You are not dying today, Silver One._ She _really_ tried.",
    ])
    assert [(s.kind, s.text) for s in segs] == [
        ("quote", "Get up,"),
        ("narr", "Xaden said."),
        ("italic", "You are not dying today, Silver One."),
        ("narr", "She really tried."),  # short italics are emphasis, stay in narration
    ]


def test_unclosed_quote_runs_to_paragraph_end():
    segs = segment_paragraphs(["“This speech continues into the next paragraph"])
    assert segs[0].kind == "quote"


def test_no_text_is_lost_in_segmentation():
    para = "He said, “Hello there,” and left. “Wait!” _Do not follow him, you fool._"
    joined = " ".join(s.text for s in segment_paragraphs([para]))
    for word in ["He", "said", "Hello", "left", "Wait", "follow", "fool"]:
        assert word in joined


def test_html_chapters_keep_italics_and_titles():
    html = """<html><body>
      <h1>Chapter One</h1><p>“Run,” she said. <em>I am coming for you, little one.</em></p>
      <p>""" + "word " * 200 + """</p>
      <h1>Chapter Two</h1><p>""" + "more " * 200 + "</p></body></html>"
    chapters = html_to_chapters(html)
    assert [c.title for c in chapters] == ["Chapter One", "Chapter Two"]
    assert "_I am coming for you, little one._" in chapters[0].paragraphs[0]


def test_tiny_section_merges_into_previous_chapter():
    html = "<h2>Chapter 1</h2><p>" + "word " * 200 + "</p><h2>A caption</h2><p>short tail</p>"
    chapters = html_to_chapters(html)
    assert len(chapters) == 1 and chapters[0].paragraphs[-1] == "short tail"


def test_chunks_never_split_a_paragraph():
    paras = [f"“{'word ' * 300}” he said." for _ in range(10)]
    chunks = list(_chunk(segment_paragraphs(paras)))
    assert len(chunks) > 1
    for a, b in zip(chunks, chunks[1:]):
        assert a[-1].paragraph != b[0].paragraph


def test_parse_director_output_is_tolerant():
    out = parse_output("""Sure! Here you go:
POV: Violet Sorrengail
CHARACTERS:
+ Xaden Riorson | male | young | human | Riorson, Xaden | wingleader
+ Tairn | male | old | dragon | - | black dragon
LABELS:
1 D Xaden Riorson | cold
2 M Tairn | angry
3 D Violet Sorrengail | furious
nonsense line
""")
    assert out.pov_character == "Violet Sorrengail"
    assert [c.name for c in out.new_characters] == ["Xaden Riorson", "Tairn"]
    assert out.new_characters[1].kind == "dragon" and out.new_characters[1].aliases == []
    assert out.labels[2].type == "mindspeech"
    assert out.labels[3].emotion == "neutral"  # unknown emotion falls back


def test_cast_find_matches_aliases_case_insensitively():
    cast = Cast(characters=[Character(name="Xaden Riorson", aliases=["Riorson"])])
    assert cast.find("riorson").name == "Xaden Riorson"
    assert cast.find("Dain") is None
