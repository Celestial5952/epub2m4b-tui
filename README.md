# EPUB2M4B Audiobook Studio

EPUB2M4B is an Ubuntu-first terminal application that converts EPUB ebooks into
chaptered M4B audiobooks. The Textual UI and CLI share one backend service; EPUB
processing, resumability, audio caching, and FFmpeg assembly remain deterministic.

The project is in early development. Tests use a fake TTS provider and never make
paid OpenAI requests.

## Development

Requires Python 3.12 or newer.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
```

The Ubuntu package includes its private Python dependencies. End users do not
need to create a virtual environment or install packages with pip.

## Estimating cost before you convert

`epub2m4b estimate` measures one EPUB, or every EPUB under a folder, and prints
characters, words, audio length, and the estimated cost for OpenAI and ElevenLabs
(dollars, plus ElevenLabs subscription credits and the smallest plan that covers
them in one month):

```bash
epub2m4b estimate ~/Books/rosa-luxemburg/     # a folder
epub2m4b estimate ~/Books/reform-or-revolution.epub
```

It is entirely offline: it makes no network request, never reads an API key, and
works even though ElevenLabs is still UNTESTED live. Text is measured exactly as a
real job would chunk it, and prices include the same 15% safety margin. ElevenLabs
plan sizes are approximate; confirm them at <https://elevenlabs.io/pricing>. The
same comparison appears on a job's detail screen in the terminal UI.

## Ubuntu package

Release packages are built on Ubuntu 24.04 amd64 so bundled binary Python
extensions match the target system. On that build host:

```bash
packaging/debian/build.sh
sudo apt install ./dist/epub2m4b_0.1.0_amd64.deb
```

The package installs the `epub2m4b` command and an **EPUB2M4B Audiobook
Studio** application-menu entry. Configuration, credentials, job state, and
audio caches remain in the invoking user's XDG directories; package upgrades
and removal do not touch them.
