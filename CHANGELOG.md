# Changelog

## 0.1.6 - Unreleased

- Add format-aware cover video codec selection (`mjpeg`, `png`, `libwebp`) with `-pix_fmt yuvj420p` for JPEG covers.
- Fix FFmpeg concat-list path escaping from shell-style to demuxer format `\'`.
- Unify `ConfigurationError(Epub2M4BError)` hierarchy and improve header credential filtering.
- Make chunk audio validation failure a retryable error rather than crashing the whole job.
- Add cross-filesystem promotion fallback for audio artifacts.
- Skip redundant state re-saving on already-complete chunks during recovery.
- Validate narration speed to reject non-finite float values (NaN, Inf).
- Wire missing navigation button handlers (`nav-jobs`, `nav-logs`) in Job Details.
- Expand chapter timing tolerance to 50ms for AAC packet boundaries.

## 0.1.5 - Unreleased

- Keep narration running when navigating between application screens.
- Recover jobs interrupted by an earlier application process as resumable.
- Refresh progress on a reopened Job Details screen from durable state.

## 0.1.4 - Unreleased

- Migrate legacy `gpt-4o-tts` configuration to `gpt-4o-mini-tts` before a job
  is created.
- Prevent the Settings screen and job creator from disagreeing about the model.

## 0.1.3 - Unreleased

- Add a no-audio OpenAI connection test for the saved key and selected model.
- Add confirmed deletion of inactive old job records while preserving narration
  cache and completed M4B files.

## 0.1.2 - Unreleased

- Remove the unavailable `gpt-4o-tts` settings choice after a confirmed
  `model_not_found` response and retain `gpt-4o-mini-tts`.
- Make force re-onboarding tolerate provider keys that were never saved and
  visibly report reset failures.

## 0.1.1 - Unreleased

- Add force re-onboarding: a typed-confirmation reset that exports non-secret
  settings and redacted audit history, removes saved app state and credentials,
  and preserves EPUB and completed M4B files.
- Include structured redacted OpenAI HTTP failure details in the activity log.

## 0.1.0 - Unreleased

- Establish project architecture, public contracts, and deterministic test provider.
- Guided onboarding and skippable first-run setup: book/cache/output folders,
  bundled offline voice auditions, and optional OpenAI API key saved to the
  system keyring (add, change, or remove later from Settings).
- Persistent Library/Jobs/Settings navigation with mouse-driven job cards,
  live progress, pause/resume/cancel, typed-START paid confirmation, and
  chaptered M4B assembly opened with the desktop player.
- OpenAI narration behind cost estimates with a 15% safety margin and dual
  spending caps; ElevenLabs support present but fail-closed as UNTESTED live.
- Ubuntu 26.04 (resolute) amd64 `.deb` with an isolated private runtime,
  desktop entry, icon, manual page, and Debian changelog.
