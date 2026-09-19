# Public interfaces

These contracts are owned by the orchestrator. Implementers must stop and propose
a change rather than editing them implicitly.

## Paths

`AppPaths.resolve(env, home)` returns immutable paths for `config`, `data`, `cache`,
and `state`. Each uses its corresponding `XDG_*_HOME` value or the documented home
fallback. Resolution has no filesystem side effects. `ensure()` creates only the
application-owned directories and returns the same object.

## Configuration repository

`ConfigRepository.load(path)` returns defaults when the file is absent and otherwise
parses schema-versioned TOML into `AppConfig`. Unknown top-level fields, invalid
types, unsupported schema versions, and credential-like generation option names are
configuration errors. API keys are never valid configuration fields.

`save(path, config)` emits deterministic UTF-8 TOML and uses a same-directory
temporary file, flush, fsync, and atomic replacement. A failed save preserves the
previous valid file. Paths are serialized as strings; absent optional paths are
omitted.

`cache_directory` and `book_directory` are optional non-secret paths. Onboarding
stores resolved absolute paths only after the cache directory can be created and
written and the book directory is confirmed to be an existing directory.

## Domain models

`BookMetadata` contains normalized package metadata without extracting content:
title, ordered authors, language, publisher, publication date, and identifier.
The EPUB title is required; the remaining values may be absent.

`Book` contains source metadata and an ordered tuple of `Chapter` objects.
`Chapter.index` is zero-based and stable in EPUB reading order. Cleaned text is
stored separately from the original XHTML string.

## EPUB metadata

`read_metadata(source)` opens an EPUB as an untrusted ZIP, locates the package
document through `META-INF/container.xml`, and returns `BookMetadata`. It rejects
missing files, invalid ZIP/XML, missing or unsafe rootfile paths, missing package
documents, and missing titles with `EpubError`. It does not extract archive entries
or write files. Multiple creators retain document order; surrounding whitespace is
trimmed; empty optional elements become `None`.

## EPUB chapter discovery

`inspect_book(source)` returns a `Book` whose chapters follow the package spine,
not archive filename order. Only local HTML/XHTML manifest items referenced by a
linear spine entry contribute content. External, absolute, backslash, NUL, or
escaping item hrefs are rejected. EPUB 3 navigation or EPUB 2 NCX labels define
chapter starts; continuation spine documents are grouped with the preceding TOC
chapter. Without a usable TOC, each spine document becomes a chapter. Titles then
fall back to the document title, first heading, or `Chapter N`.

Discovery stores decoded source markup in `Chapter.html`, separating grouped source
documents with a deterministic boundary comment, and leaves `Chapter.text` empty
for the normalization task. It does not execute or extract content. The book source
SHA-256 is computed from the original EPUB bytes. Cover extraction and
intra-document anchor splitting are separate tasks.

## EPUB cover discovery

`read_cover(source)` returns immutable cover bytes, declared media type, and a safe
suggested suffix without extracting files. EPUB 3 `cover-image` manifest properties
take precedence over EPUB 2 `<meta name="cover" content="...">`. The selected item
must be a local non-traversing manifest member with a supported raster media type
and a bounded non-empty payload. A book with no declared cover returns `None`;
malformed declarations, missing members, unsafe paths, unsupported media, or an
oversized payload raise `EpubError`.

## Text cleaning and normalization

`html_to_text(markup)` removes non-narrative markup with the standard-library HTML
parser. It excludes script, style, navigation, hidden content, page-break markers,
and EPUB2M4B document-boundary comments while preserving prose order, punctuation,
paragraphs, headings, block quotations, line breaks, and visible scene breaks. It
never rewrites or corrects prose.

`normalize_text(text)` returns NFC Unicode with `\n` line endings, removes soft
hyphens and zero-width formatting artifacts, converts non-breaking and horizontal
Unicode whitespace to ordinary spaces, trims line edges, and collapses runs of
blank lines to a single paragraph break. It is deterministic and idempotent.

`NarrationSettings` contains provider, model, voice, speed, and instructions.
`Chunk` contains stable chapter/chunk indexes, normalized text, a text hash, and a
generation hash. `Chunk.id` is derived, human-readable, and collision-resistant.

`JobManifest` is the durable schema root. Schema version 1 contains source,
book-summary, narration, and chunk state. It contains no API key or headers.

## Chunk identity

The generation hash is SHA-256 over canonical UTF-8 JSON containing normalized
text, provider, model, voice, decimal speed, instructions, and generation options.
The ID format is `chapter-NNN_chunk-NNN_<first-12-hex>`.

## Deterministic chunking

`chunk_text(text, chapter_index, settings, target_chars=3200,
max_chars=4000)` normalizes its input and returns ordered `Chunk` models. Empty
normalized text returns an empty tuple. Limits are positive, target is not greater
than maximum, and maximum may never exceed 4,000 characters.

Boundaries prefer, in order: scene breaks, paragraphs, sentence endings,
punctuation followed by whitespace, ordinary whitespace, then a hard boundary only
when unavoidable. A single word longer than the maximum is hard-split. Chunk text
is trimmed only at its outer boundary; prose characters are never reordered or
rewritten. Identical inputs/settings produce identical text, hashes, and IDs.

## Job preparation and cost estimate

`prepare_job(source, settings, job_id, app_version, timestamp)` inspects the EPUB,
cleans every included chapter, chunks its normalized prose, and returns a prepared
book plus a schema-version-1 `JobManifest` without writing files or calling a
provider. Empty chapters are allowed, but a book with no narratable chunks is an
`EpubError`. Chunk indexes restart at zero in each chapter.

`estimate_narration(chunks, pricing, words_per_minute, safety_multiplier)` returns
word/character counts, estimated minutes, text/audio token estimates, and a
conservative USD total. Pricing and the audio-token rate are explicit inputs so a
stale hard-coded price cannot silently authorize paid work. Inputs must be finite
and positive, and the estimate uses ceiling arithmetic before applying the safety
multiplier.

## TTS provider

`TTSProvider.synthesize(request, destination)` is asynchronous. It writes a WAV to
the caller-provided temporary destination and returns `SynthesisResult` metadata.
It raises a typed `ProviderError`; callers decide retries. Providers never own job
state or cache policy.

`OpenAITTSProvider` always requests WAV output and receives its credential through
construction; it never reads configuration files, logs a credential, or includes
remote exception text in a user-facing error. Authentication, permission, invalid
request, and quota failures are non-retryable. Network/timeout failures, HTTP 408,
409, 429, and 5xx responses are retryable. A successful response must be a
non-empty readable WAV before it becomes a synthesis result. Unit tests inject a
fake client and never contact OpenAI.

## Bundled voice registry

The voice registry loads `resources/voice_samples/manifest.json`, rejects unknown
schema versions, unsafe relative paths, duplicate voice IDs, missing files, and
integrity mismatches, and returns immutable entries in display order. Auditioning a
bundled entry never calls a TTS provider.

`VoiceRegistry.load_bundled()` resolves the manifest within the installed Python
package so voice auditions work from a wheel or Debian installation rather than
depending on the source checkout's current directory.

## Audio player

`AudioPlayer.play(path)` starts one validated local audio file and stops any active
preview first. `stop()` is idempotent. The Ubuntu implementation resolves `ffplay`
from `PATH`, uses an argument array with `shell=False`, suppresses child terminal
output, and reaps the child on stop and application shutdown. Player state changes
are published as application events; Textual widgets never own subprocesses.

## Onboarding

`OnboardingService` exposes non-secret state: completion flag, selected voice,
dependency status, and credential status (`configured`, `environment`, or
`unconfigured`). Credential values cross only the credential-service boundary.
Completing or skipping onboarding never performs a paid request. Connection tests
are explicit user actions and redact authentication material from every result.

`OnboardingService.state(env)` combines persisted non-secret configuration,
verified bundled voices, local dependency status, and the OpenAI credential status.
`complete(voice_id, cache_directory, book_directory)` validates the voice and both
storage choices, creates and write-checks the cache directory, then atomically marks
onboarding complete. The book directory must already exist. `skip()` marks completion
while preserving defaults. Credential set/remove
delegates to `CredentialService`. None of these methods tests a connection or calls
a narration provider.

## Book-library discovery

`scan_epub_folder(root, max_books=10000)` recursively discovers non-symlinked regular
files whose suffix is `.epub` case-insensitively. It never opens book contents,
follows symbolic links, or writes to the library. Results contain absolute and
root-relative paths, sort deterministically by relative path, and report truncation
when the configured bound is reached. Unreadable subdirectories are skipped; an
unavailable or non-directory root is a typed library error.

## Local dependencies

`check_dependencies(resolver)` returns immutable statuses for required `ffmpeg`
and `ffprobe` plus optional `ffplay`. It only resolves executable paths and performs
no subprocess or network operation. Required availability is summarized separately
from optional preview playback availability.

## Provider registry and credentials

Provider metadata is resolved through a registry with explicit capabilities such
as `text_to_speech`. Credentials are retrieved as `get(provider_id)` and stored as
`set(provider_id, secret)` by a keyring-backed service; callers never receive the
entire credential collection. OpenAI and ElevenLabs keys use distinct keyring
entries and environment names (`OPENAI_API_KEY` and `ELEVENLABS_API_KEY`).

`CredentialService.get(provider_id, env)` prefers a nonblank provider-specific
environment variable, then Secret Service/keyring, and returns a credential value
plus only its source (`environment` or `keyring`). `status` exposes no value.
`set` and `delete` affect only the named provider's keyring entry. Provider IDs are
validated, secrets are nonblank, and backend failures become a typed credential
error whose message and representation never contain credential text. These
operations perform no API request.

A provider without `text_to_speech` capability cannot be selected as the narration
provider. Connection tests are never automatic, never run in unit tests, and require
explicit user approval after showing whether the request may incur cost.

The retired legacy OpenAI model identifier `gpt-4o-tts` is atomically migrated to
`gpt-4o-mini-tts` when onboarding state is loaded and again immediately before job
preparation. Other model identifiers are preserved.

## Force re-onboard

`ApplicationService.force_reonboard()` atomically exports non-secret settings and
redacted audit entries to JSON outside the application state, then removes saved
provider credentials, configuration, jobs, logs, and the application-owned temporary
cache. EPUB library folders and completed M4B output are never deleted. A reset is
refused while narration is active.

`ApplicationService.test_openai_connection(model)` retrieves the selected model to
verify OpenAI reachability, saved-key authentication, and model access. It does not
create speech or incur TTS charges. Connection failures retain the provider's
credential-safe diagnostic details in the audit log.

`ApplicationService.delete_job(job_id)` deletes exactly one inactive job directory.
It rejects missing or unsafe targets and preserves content-addressed narration cache
and completed M4B files.

Narration execution is owned by the application rather than an individual UI screen,
so navigating between screens does not stop paid work. On process startup, a manifest
left in `running` state is atomically changed to `paused`; resuming it first recovers
any valid partial or cached audio before making another provider request.

## Manifest repository

`ManifestRepository.load(path)` parses schema version 1 or raises a typed manifest
error. `save(path, manifest)` writes canonical JSON to a same-directory temporary
file, flushes and fsyncs it, then atomically replaces the destination. A failed
save leaves the previous valid manifest intact and removes its temporary file.

## Audio cache

`AudioCache(root)` is side-effect free until `ensure()` is called. Narration WAVs
use `root/narration/<first-two-generation-hash-characters>/<generation-hash>.wav`;
preview audio uses a distinct `root/previews/` namespace and can never satisfy a
narration lookup.

`path_for(chunk)` is pure and depends only on the validated generation hash.
`lookup(chunk, validator)` returns a path only for a non-symlink, non-empty regular
file that the supplied audio validator accepts. Missing, empty, invalid, symlinked,
or validator-error entries are cache misses and are not deleted implicitly.

## Audio probing and concatenation

`probe_duration(path)` resolves `ffprobe` from `PATH`, invokes it with an argument
array and `shell=False`, and returns a finite positive duration in seconds. Missing
tools, missing/symlinked/empty inputs, non-zero exits, malformed output, and invalid
durations raise a typed audio/tool error without exposing unrelated process output.

`write_concat_list(paths, destination)` requires at least one non-symlinked,
non-empty regular input, writes an FFmpeg concat-demuxer list in the supplied order,
and safely escapes path text. It writes deterministic UTF-8 through a same-directory
temporary file and atomic replacement; it never invokes FFmpeg itself.

## Generation coordinator

`GenerationCoordinator.run(manifest_path)` is the sole owner of narration state
transitions. It processes only chunks whose validated content-addressed WAV is
missing. Before a provider call it persists `generating` plus an incremented
attempt count. After a call it validates and fsyncs a deterministic partial WAV,
atomically promotes it into the cache, and only then persists `complete` with its
duration. A restart first recovers a valid partial or final cache file, so a crash
between paid synthesis and manifest persistence does not cause a duplicate call.

Provider failures are recorded with credential-safe messages. Retryable failures
may be attempted up to the configured bound; non-retryable failures stop the job.
`request_pause()` and `request_cancel()` are synchronous, idempotent control
signals. They are checked between chunks and after any in-flight provider response
has been validated and durably committed, so neither control can discard paid
audio or interrupt an atomic cache/manifest write. The final persisted status is
`paused` or `cancelled`, and `run()` returns normally with that manifest; cancellation
takes precedence when both were requested. A fresh coordinator may resume a paused
manifest and requests only missing chunks. A cancelled manifest requires creation
of a new job. Version 1 is serial by default; bounded parallel generation is a later
integration milestone.

Paid execution is gated outside the coordinator by a persisted estimate and an
explicit per-run spending authorization. Unit tests use `FakeTTSProvider` only.

## M4B assembly

`assemble_m4b(manifest, chapter_titles, destination, bitrate_kbps, cover=None)`
accepts only a complete manifest whose chunks have validated audio paths and finite
positive durations. It orders audio by `(chapter_index, chunk_index)`, writes concat,
FFmetadata, and optional cover inputs in a private same-filesystem temporary
directory, and invokes FFmpeg with argument arrays and `shell=False`. Chapter
boundaries are cumulative milliseconds derived from chunk durations; chapters
without narration are omitted.

The assembler writes a temporary `.m4b`, validates its duration, chapter table, and
optional attached cover stream with FFprobe, then atomically replaces the
destination. Any tool or validation failure preserves an existing destination and
removes temporary artifacts. Version 1 embeds title, authors, genre, and an EPUB
cover when one was declared.

## Application service

Textual screens and CLI commands depend only on `ApplicationService`. Long-running
operations publish immutable application events. Pause, resume, and cancel are
service calls and never mutate persistent files directly from the UI.

The first-run UI uses `onboarding_state()`, `complete_onboarding(voice_id,
cache_directory, book_directory)`,
`skip_onboarding()`, `set_openai_credential(secret)`, `remove_openai_credential()`,
`play_voice_preview(voice_id)`, and `stop_voice_preview()`. These calls delegate to
the onboarding, credential, registry, and player components; the UI never receives
a credential value or an executable path. `shutdown()` always stops preview audio.

The home screen first calls `scan_book_folder()` and renders its immutable candidates
as a selectable library list. It then calls `inspect_book(source)` to show an EPUB's title, authors,
and spine-ordered chapters, then `create_job(source)` to persist a ready narration
job. Inspection and preparation perform no provider request. Textual supplies a
path chosen by the listener and renders returned immutable models; it never opens
or parses the EPUB itself.

`list_jobs()` offloads `JobStore.list()` and returns newest-first immutable job
summaries. The Jobs screen is read-only until the cost-confirmation and generation
controls are connected. A `ready` job is explicitly labeled as locally prepared
with no narration started and no provider credits used.

`estimate_job(job_id)` returns a conservative estimate for chunks not yet marked
complete and never accesses credentials or a provider. `generate(job_id,
authorized_max_cost_usd)` and `resume(...)` refuse to construct a provider unless
that estimate is no greater than both the explicit per-run authorization and the
configured spending cap. Generation publishes safe immutable `ProgressEvent`s from
durably persisted manifest transitions. A completed run assembles and validates the
M4B locally. `pause(job_id)` and `cancel(job_id)` only signal that job's active
coordinator and take effect at its next safe boundary.

## Job discovery

`JobStore(root)` is side-effect free until `ensure()`. Safe job IDs map only to
direct child directories and `manifest.json`. `list()` inspects only non-symlinked
direct children, returns immutable summaries with status and completed/total chunk
counts, and represents corrupt manifests as generic error summaries instead of
crashing or exposing their contents. Results are newest-updated first with job ID
as a deterministic tie-breaker. Discovery never deletes or mutates jobs.
