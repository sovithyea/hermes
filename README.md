# Hermes

Turn a book into a full-cast audiobook with free, local AI: an LLM "director" works out who
says each line, and every character gets their own voice.

Runs entirely on an Apple Silicon Mac: [Ollama](https://ollama.com) (`qwen3:14b`) for the
director and [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) for voices.

## Setup

```sh
brew install ffmpeg espeak-ng ollama
ollama serve &            # leave running
ollama pull qwen3:14b
uv sync
```

## Usage

```sh
uv run hermes ingest path/to/book.epub        # lists chapters, prints the book's slug
uv run hermes direct <slug> -c 1 -c 2         # who-says-what (~45 s per 1k words)
uv run hermes show <slug> -c 1                # review the dialogue attribution
uv run hermes cast <slug>                     # assign voices
uv run hermes render <slug> -c 1 -c 2         # -> library/<slug>/audio/ch001.mp3
uv run hermes say "Hello there" --voice am_fenrir --emotion cold   # audition a voice
```

Everything the tool decides is plain JSON in `library/<slug>/` and can be edited by hand:

- `script/ch001.json`: every line with its `speaker`, `type` (narration / dialogue / thought /
  mindspeech) and `emotion`. Fix a wrong speaker here and re-render; only changed lines regenerate.
- `cast.json`: characters, their voices, `narrator_voice`, and `split_pov_voice` (give a
  first-person narrator a separate dialogue voice).
- `lexicon.json`: pronunciation fixes, e.g. `{"Xaden": "Zayden"}`.

Voices: `af_*`/`bf_*` are American/British female, `am_*`/`bm_*` male.

Books and generated audio live in `library/`, which is git-ignored. Only use books you own,
and don't distribute the audio.
