# Design

## Product boundary

EPUB2M4B is a local audiobook-production workstation for Ubuntu 24.04 and newer.
OpenAI is responsible only for turning normalized text into narration. Everything
else—book parsing, text cleanup, chunking, cache identity, job persistence, cost
estimation, retry decisions, and M4B assembly—is deterministic local behavior.

## Architecture

```text
Textual TUI / CLI
        |
ApplicationService
        |
  +-----+------------------+
  |                        |
EPUB pipeline       Generation coordinator       M4B assembler
  |                        |                           |
normalizer/chunker      TTSProvider                 FFmpeg
  |                        |
manifest + content-addressed WAV cache
```

The UI may display state and invoke service methods. It must not parse EPUB
internals, call a TTS provider, construct FFmpeg commands, calculate chapter
timestamps, or manage cache files.

## Durable invariants

- A chunk identity includes normalized text and every setting that can change
  narration. Output paths, cover art, and final filenames are excluded.
- A completed chunk is trusted only after its WAV exists and passes audio
  validation. State is persisted immediately after validation.
- Durable files are written beside their final path and atomically replaced.
- Credentials never appear in configuration, manifests, logs, task prompts, or
  screenshots. Interactive credentials use Secret Service through `keyring`.
- Normal execution never writes under `/usr` and never requires root.
- Subprocesses use argument arrays and never `shell=True`.

## Persistence

Configuration, data, cache, and logs follow XDG base-directory rules. Each job
lives below the application data directory and owns its manifest, normalized text,
WAV chunks, chapter audio, and final output. Schema migrations will be explicit;
unknown future schema versions fail safely.

## First-run onboarding

Onboarding is a skippable Textual wizard. It checks local tools, lets the listener
audition bundled voice samples offline, and offers secure setup for the listener's
own OpenAI project key. Skipping credentials leaves all local inspection and voice
audition features available; only paid API operations remain disabled.

The listener also chooses a writable narration-cache directory and an existing book
folder. After onboarding, Home recursively scans that folder for regular `.epub`
files without following symbolic links and presents a bounded, deterministic list.
Manual path entry remains available when no library is configured.

After onboarding, every primary screen exposes persistent **Library**, **Jobs**,
and **Settings** navigation. Settings edits book-library, cache, and voice choices
directly instead of replaying the onboarding wizard. Jobs distinguishes local
preparation from paid narration and always shows real persisted chunk progress.

Settings also has a deliberately destructive **Force re-onboard** action. After a
typed confirmation, it atomically exports non-secret settings and redacted audit
history outside application state, removes saved provider credentials and
application-owned state, and returns to onboarding. EPUB folders and completed M4B
files are preserved.

The application may open the official API-key page with `xdg-open` after an
explicit action, but it never collects OpenAI account passwords or creates a shared
application key. Pasted credentials go directly to the credential service backed
by Secret Service/keyring.

## Voice previews and playback

Audition samples are app-owned Opus assets listed in
`resources/voice_samples/manifest.json`. They use identical prose and narration
instructions and require no network access at runtime. Book-specific previews are
separate paid artifacts in the XDG preview cache and never mark book chunks complete.

Textual provides playback controls while the application service owns an
`AudioPlayer` subprocess. The Ubuntu implementation uses audio-only `ffplay`, one
active preview at a time, argument arrays, and `shell=False`. See
`docs/onboarding-and-voice-preview.md` for the lifecycle and acceptance criteria.

## Dependency choices

- `textual`: terminal UI and background workers.
- `EbookLib` plus `beautifulsoup4`: EPUB structure and conservative HTML cleanup.
- `openai`: typed OpenAI API client behind `TTSProvider`.
- ElevenLabs support uses the provider-neutral HTTP adapter; no second SDK is
  required by the initial integration.
- `keyring`: Secret Service credential storage with graceful unavailable-backend
  handling.
- System `ffmpeg`/`ffprobe`: validated at runtime and declared by the Debian package.
- Python standard-library dataclasses and JSON: explicit, inspectable durable models.

## Provider expansion

The core depends on `TTSProvider`, a provider registry, and provider-namespaced
credentials rather than OpenAI SDK types. OpenAI is the first shipping narration
provider. ElevenLabs—the developer API behind the ElevenReader ecosystem—is the
second text-to-speech integration target and is explicitly labeled **UNTESTED**
until it passes an authorized live API verification. It has its own credentials,
model limits, voices, estimates, and cache namespace. See `docs/provider-roadmap.md`.

No paid provider request—OpenAI, ElevenLabs, or future—is permitted during startup,
onboarding, automated tests, book inspection, or voice selection. Every live test
or generation action shows an estimate and requires explicit confirmation.

## Non-goals for 1.0

No web server, browser UI, Electron, Docker runtime, speaker detection, multi-voice
dialogue, background daemon, or non-Debian package format.
