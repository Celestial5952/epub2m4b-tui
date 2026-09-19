# Task board

See [`docs/roadmap.md`](roadmap.md) for the active development path, ElevenLabs integration milestones, and public release plan.

| ID | Status | Owner | Task | Acceptance |
|---|---|---|---|---|
| F0 | Accepted | Orchestrator | Foundation, contracts, fake provider | Core models/interfaces documented; fake WAV deterministic; 5 focused tests pass |
| B1 | Accepted | Luna | XDG path resolution | 6 focused tests pass; overrides/fallbacks and explicit `ensure` verified |
| B1C | Accepted | Luna + Orchestrator | Configuration loading and atomic persistence | 13 focused tests; schema-versioned TOML, credential rejection, deterministic round trip, and failed-write preservation verified |
| B2 | Accepted | Luna | EPUB metadata extraction | 13 synthetic tests plus private real-book metadata smoke test pass |
| B3 | Accepted | Luna + Orchestrator | Spine/chapter discovery | 12 synthetic tests; EPUB 2 NCX and private real-book smoke test yield 80 grouped chapters |
| B4 | Accepted | Luna + Orchestrator | HTML cleaning and text normalization | 14 focused tests; private real-book smoke test yields 80 non-empty chapters |
| B5 | Accepted | Luna + Orchestrator | Deterministic chunker | 19 focused tests; private real-book smoke test yields 599 chunks with max 3,992 chars |
| B6 | Accepted | Luna | Atomic manifest persistence | 4 focused tests pass; round trip, schema errors, and failed replace verified |
| B7 | Accepted | Luna + Orchestrator | Cache layout and lookup | 14 focused tests; stable content paths and strict non-symlink validated cache hits verified |
| B2C | Accepted | Luna + Orchestrator | EPUB cover discovery | 9 synthetic tests; EPUB 3/2 declarations, safe bounded raster bytes, no extraction |
| G1 | Accepted | Luna + Orchestrator | OpenAI TTS provider adapter | 33 injected-client tests; async dispatch, protected fields, quota-aware retries, and credential-safe errors; no network calls |
| G2 | Accepted | Orchestrator | Serial resumable generation coordinator | 10 focused tests; final/partial recovery, no duplicate synthesis, atomic transitions, bounded delayed retry |
| G3 | Accepted | Luna + Orchestrator | FFprobe duration reader and concat-list writer | 12 focused tests; safe subprocess contract, strict validation, escaping, and atomic deterministic output |
| G0 | Accepted | Luna + Orchestrator | Job preparation and explicit pricing estimate | 9 focused tests; pure normalized EPUB-to-manifest preparation and Decimal conservative estimate |
| G4 | Accepted | Orchestrator | M4B assembly, metadata, and cover art | 11 focused tests plus real local FFmpeg → M4B → FFprobe integration with two chapters and attached cover |
| G5 | Accepted | Orchestrator + Luna tests | Pause/cancel generation control | 5 control tests plus 10 coordinator regressions; safe boundaries persist paid audio, cancel wins, and paused work resumes only missing chunks |
| V0 | Accepted | Orchestrator | Bundled voice comparison assets | 13 Opus samples generated, FFprobe-validated, and integrity-manifested |
| V1 | Accepted | Luna + Orchestrator | Package bundled voice assets | 10 focused tests; installed-package lookup loads all 13 byte-identical verified samples without checkout-relative paths |
| U0 | Accepted | Luna + Orchestrator | Provider-namespaced credential service | 18 focused tests; environment/keyring lookup, secure namespaced mutation, redacted backend failures; no network |
| U1A | Accepted | Luna + Orchestrator | Voice registry and preview player | 13 focused tests; all 13 bundled assets integrity-checked; safe one-child ffplay lifecycle |
| U0B | Accepted | Luna + Orchestrator | Skippable onboarding service | 7 focused tests; atomic completion/skip, verified voice selection, dependency and credential status; no API calls |
| D0 | Accepted | Luna + Orchestrator | Local dependency status | 4 focused tests; required FFmpeg/FFprobe and optional ffplay resolution, immutable status |
| U1B | Accepted | Luna + Orchestrator | Textual onboarding screen | 5 headless Textual tests; service-only staged flow, masked optional key, voice audition, skip/finish, and clean shutdown |
| U2 | Accepted | Luna + Orchestrator | Home EPUB inspection/preparation screen | 3 focused Home tests plus 5 onboarding regressions; service-only async inspection/preparation, ordered chapters, keyboard flow, generic safe errors |
| U3 | Accepted | Orchestrator | Onboarding storage and EPUB library | Configured cache/book paths, write-checked cache, bounded deterministic recursive EPUB scan, post-onboarding selectable Home list, manual-path fallback; 51 focused and regression tests pass |
| U4 | In progress | Orchestrator | First-time-computer-user UX and navigation | Desktop-launch-first language, click-first folder selection, numbered Library flow, persistent Library/Jobs/Settings navigation, direct book/cache/output settings, automatic book inspection, clickable job cards with detail/estimate, typed-START paid-work confirmation, live progress with pause/cancel, duplicate-preparation guard, and plain errors; human usability pass remains |
| D1 | In progress | Orchestrator | Ubuntu 26.04 Debian packaging | Validated package metadata/archive, isolated private runtime, launcher, desktop entry, scalable icon, pinned runtime dependencies, manual page, Debian changelog, and 8 offline packaging tests; 26.04 `.deb` built and extraction-validated on the build host; clean-VM install/remove/upgrade validation remains |
| A0 | Accepted | Orchestrator + Luna tests | Local application runtime composition | 4 runtime tests plus 2 CLI tests; XDG/bootstrap wiring, voice/player lifecycle, async EPUB inspection, and atomic ready-job preparation; no provider calls |
| A1 | Accepted | Orchestrator + Luna tests | Cost-gated generation service | Offline remaining-cost estimate, dual spending caps before credentials/provider, streamed durable progress, pause/cancel routing, and final cover-aware M4B assembly; connected to the TUI only behind the typed-START confirmation modal |
| P0 | Accepted | Luna + Orchestrator | Provider capability registry | 6 focused tests; OpenAI and ElevenLabs declare TTS capability with separate credential namespaces |
| J0 | Accepted | Luna + Orchestrator | Persistent job discovery | 8 focused tests; safe direct-child lookup, immutable progress summaries, corrupt-job isolation |
| E1 | Accepted — UNTESTED live | Orchestrator | ElevenLabs / ElevenReader synthesis adapter | 31 focused offline tests; documented HTTP payload, safe voice IDs, speed/settings merge, PCM-to-WAV normalization, atomic writes, request IDs, and redacted retry classification; no live request |
| E2 | Accepted — UNTESTED live | Orchestrator | ElevenLabs voice/model catalog | 28 focused offline tests; explicit-only paginated voice search, TTS model filtering, request limits and character multipliers, immutable validated results, and redacted failures; no live request |
| E3 | Accepted — UNTESTED live | Orchestrator | Guarded ElevenLabs pricing & estimation | 17 offline pricing tests accepted; verified PAYG model allowlist, 15% safety margin, unknown/custom-rate fail-closed behavior |
| E4 | In progress — UNTESTED live | Orchestrator | ElevenLabs Settings & Keyring UI wiring | Provider switcher in Settings, isolated keyring storage (`ELEVENLABS_API_KEY`), dynamic model/voice selection without leaking keys |
| E5 | Backlog — UNTESTED live | Orchestrator | ElevenLabs chunker & coordinator wiring | Reconcile character limits with EPUB chunker; per-provider rate limits; audio cache collision isolation |
| E6 | Gate — UNTESTED live | Orchestrator | ElevenLabs spending guard & live verification | Explicit confirmation modal; bounded live test on small public-domain sample with authorized key; remove UNTESTED label |
| OS1 | In progress | Orchestrator | GitHub open-source launch readiness | Automated security checking, GPL-3.0 LICENSE file, CI pipeline (.github/workflows), community documentation |
| G1+ | Backlog | Mixed | Generation, audio, UI, packaging phases | See `docs/roadmap.md` and product specification |

No task may make a real OpenAI request. The first paid smoke test is an explicit
release gate after provider, validation, spending guard, and resumability tests.
