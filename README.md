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

## Web app

```sh
uv run hermes serve        # http://localhost:8000
```

Upload an EPUB/PDF/TXT, or **photos of a printed book's pages** (phone photos, any order of
upload: pages are sorted by the phone's file names, IMG_0001, IMG_0002…). Photos are read with
Apple's on-device OCR; italics (often the only marker of telepathic speech) are recovered by
measuring letter slant. Check the result in `library/<slug>/source.txt`. CLI equivalent:
`uv run hermes photos <folder> --title "Book title"`.

To scan from a phone anywhere, use Tailscale (free): install it on the Mac and the phone,
sign in to the same account, then run `uv run hermes serve --tailscale`. The app gets a private
https link (only your tailnet can open it) and the scanner gets a one-tap live viewfinder.
Share the Mac from the Tailscale admin console to give a friend access.

**Each person gets their own library.** Tailscale tells the app who is signed in, so books
someone adds are visible only to them; books added on this Mac (or from the CLI) belong to the
Mac's owner. Delete a book from the bottom of its page.

Alternatively, to upload straight from a phone on the same Wi-Fi, run `uv run hermes serve --phone`
and open `http://<this-mac>.local:8000` on the phone (anyone on that network can reach it while
it runs), or AirDrop the photos to the Mac.

## ElevenLabs (optional, paid per character)

Put your key in a `.env` file in this folder (it's git-ignored):

```
ELEVENLABS_API_KEY=...
```

Then on the Cast page switch individual characters to ElevenLabs. The narrator stays on free
Kokoro. ElevenLabs lines are performed from the script's emotions with v3 tags like
`[whispers]`, and the page shows how many characters the book's ElevenLabs lines will use
against your monthly allowance before you generate anything.

Books and generated audio live in `library/`, which is git-ignored. Only use books you own,
and don't distribute the audio.
