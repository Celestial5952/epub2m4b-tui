# Onboarding and voice previews

## Goals

First launch should explain the application, verify local audio tooling, let the
listener compare every bundled voice, and let them pick a narration service and save
that service's API key securely, without making credentials a prerequisite for opening
the application.

The onboarding wizard is always skippable and can be reopened from Settings.

The usability target is a listener who has never used a terminal. Installing the
Debian package and choosing **EPUB2M4B Audiobook Studio** from the application menu
must be enough to start. Normal use must not require commands, knowledge of Linux
paths, or an understanding of EPUB parsing, caches, FFmpeg, models, or job IDs.

## First-run flow

1. **Welcome** — explain that EPUB parsing and audiobook assembly happen locally,
   while narration uses an account the listener controls.
2. **System check** — report FFmpeg, FFprobe, and audio-preview availability. A
   playback failure is non-fatal and includes the exact remediation.
3. **Storage and books** — choose a writable narration-cache location and an existing
   book-library folder. The cache may be created; the library is scanned read-only.
4. **Voice audition** — show all bundled samples with Play/Stop and Select actions.
   This step works offline and does not require an API key.
5. **Narration service** — choose which provider reads the books aloud. The list comes
   from the provider registry, so a new provider appears with no wizard changes. Each
   entry is labelled *verified* or *UNTESTED live*. Choosing an unverified provider
   explains that its key can be saved now but narration keeps using the current
   verified provider until it is verified.
6. **API key (optional)** — for the provider chosen in step 5, show its official
   key-creation and billing pages and whether a key is already saved or supplied by
   its environment variable, then offer a masked input. The key is saved under that
   provider only; changing the provider discards anything typed. The step can be
   skipped.
7. **Finish** — summarize the selected voice, narration service, that service's key
   status, cache location, and book folder. Home scans the selected folder and offers
   the discovered EPUBs in a deterministic list. No API request is made merely by
   completing onboarding.

Skipping API setup leaves EPUB inspection, chapter selection, estimates, settings,
and bundled voice auditions available. Paid preview generation and audiobook
generation remain disabled with a clear action to configure the narration service.

## Individual API-key setup

Every listener supplies a key from their own provider account. EPUB2M4B never ships a
shared key and never asks for a provider password.

Onboarding displays the provider's official API-key and billing URLs as copyable text
(taken from the provider registry; only `https` URLs are accepted). The listener
creates a key there, returns to a masked input, and pastes it. A connection test is
available from Settings for providers that implement one.

Credentials are stored with `keyring`/Secret Service. They never enter
`config.toml`, manifests, logs, shell scripts, screenshots, or bundled resources.
Removing a credential is available from Settings. The onboarding screen clearly
states that ChatGPT subscriptions and API billing are separate and links to billing
and project spend-limit settings.

The screen is provider-registry driven so **ElevenLabs / ElevenReader (UNTESTED)**
credentials use a separate keyring entry and can be saved independently of OpenAI. A
provider is selectable for narration only when it declares text-to-speech capability,
has an installed adapter, and is marked `live_verified`; otherwise onboarding saves
its key but leaves the narration provider unchanged. See `docs/provider-roadmap.md`.

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
- The provider and key steps stay fully visible on an 80x24 terminal.
- A key typed for one provider is never saved under another.
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
