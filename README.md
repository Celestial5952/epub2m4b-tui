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
