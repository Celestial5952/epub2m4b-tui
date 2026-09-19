# Onboarding and voice previews

## Goals

First launch should explain the application, verify local audio tooling, let the
listener compare every bundled voice, and offer secure OpenAI setup without making
credentials a prerequisite for opening the application.

The onboarding wizard is always skippable and can be reopened from Settings.

The usability target is a listener who has never used a terminal. Installing the
Debian package and choosing **EPUB2M4B Audiobook Studio** from the application menu
must be enough to start. Normal use must not require commands, knowledge of Linux
paths, or an understanding of EPUB parsing, caches, FFmpeg, models, or job IDs.

## First-run flow

1. **Welcome** — explain that EPUB parsing and audiobook assembly happen locally,
   while narration uses the listener's own OpenAI API account.
2. **System check** — report FFmpeg, FFprobe, and audio-preview availability. A
   playback failure is non-fatal and includes the exact remediation.
3. **Storage and books** — choose a writable narration-cache location and an existing
   book-library folder. The cache may be created; the library is scanned read-only.
4. **Voice audition** — show all bundled samples with Play/Stop and Select actions.
   This step works offline and does not require an API key.
5. **OpenAI setup (optional)** — offer:
   - Create my own API key
   - Use an existing API key
   - Use `OPENAI_API_KEY` for this session
   - Skip for now
6. **Finish** — summarize the selected voice, credential status, cache location, and
   book folder. Home scans the selected folder and offers the discovered EPUBs in a
   deterministic list. No API request is made merely by completing onboarding.

Skipping API setup leaves EPUB inspection, chapter selection, estimates, settings,
and bundled voice auditions available. Paid preview generation and audiobook
generation remain disabled with a clear **Configure OpenAI** action.

## Individual API-key setup

Every listener supplies a key from their own OpenAI project. EPUB2M4B never ships a
shared key and never asks for an OpenAI password.

The **Create my own API key** action opens the official OpenAI API-key page through
`xdg-open` only after an explicit user action. If desktop opening is unavailable,
the TUI displays a copyable URL. The listener returns to a masked input, pastes the
key, and may run a minimal connection test before saving.

Credentials are stored with `keyring`/Secret Service. They never enter
`config.toml`, manifests, logs, shell scripts, screenshots, or bundled resources.
Removing a credential is available from Settings. The onboarding screen clearly
states that ChatGPT subscriptions and API billing are separate and links to billing
and project spend-limit settings.

The screen is provider-registry driven so **ElevenLabs / ElevenReader (UNTESTED)**
credentials use a separate keyring entry and can be selected independently of OpenAI. A provider is
selectable for narration only when it declares text-to-speech capability and has an
installed adapter; see `docs/provider-roadmap.md`.

## Voice audition

`resources/voice_samples/manifest.json` is the source of truth for bundled voices.
Each sample uses the same model, sentence, instructions, speed, and Opus format, so
listeners compare the voice rather than different prose or direction.

The voice picker displays one row per manifest entry:

```text
Voice       Preview                  Selection
Alloy       [▶ Play] [■ Stop]        ( )
Ash         [▶ Play] [■ Stop]        ( )
...
Marin       [▶ Play] [■ Stop]        (•)
```

Only one preview may play at a time. Starting another stops the current preview.
Selecting a voice does not make an API request. Later, a user may generate a paid
30–60 second book-specific preview after seeing its estimate and confirming it.

## Audio playback from Textual

The terminal renders controls and status; audio is played by a backend process.
`AudioPlayer` launches the system `ffplay` with an argument array equivalent to:

```text
ffplay -nodisp -autoexit -hide_banner -loglevel error SAMPLE.opus
```

The implementation uses `subprocess.Popen` with `shell=False`, redirects child
output away from the TUI, and monitors completion in a Textual worker. Stop sends a
graceful termination, waits briefly, then kills only that child if necessary. App
exit always stops the active preview. FFprobe supplies duration; the TUI uses a
monotonic timer for display only.

Playback is a service-layer capability. Textual widgets call `play_preview` and
`stop_preview`; they never construct commands or manage processes directly.

## Acceptance criteria

- All manifest files exist, match their size/SHA-256, and pass FFprobe as Opus.
- Voice audition works with no network and no API key.
- Starting a new sample stops the previous sample.
- Stop, screen change, application exit, SIGINT, and SIGTERM leave no player child.
- API setup can be skipped without warnings on every launch.
- Cache and book folders can be selected during onboarding and persist atomically.
- Home scans the configured book folder without following symlinks and offers EPUBs
  for selection while retaining manual path entry. Selecting a listed book opens it
  automatically; the primary flow never requires typing a path.
- Every primary action is mouse-clickable, uses plain-language labels, and explains
  what happens next. Technical terms remain confined to optional detail and errors.
- The Home screen provides a visible **Change folders** action; changing the library
  location does not require restarting the app or editing a configuration file.
- A pasted credential is masked, stored only through the credential service, and
  absent from config, logs, manifests, and error reports.
- A failed connection test is classified as authentication, exhausted credit,
  rate-limit, access, or transport failure without exposing the key.
- No real provider request runs without an estimate and explicit confirmation.
