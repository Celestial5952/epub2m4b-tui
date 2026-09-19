# Provider roadmap

## Provider-neutral core

EPUB parsing, cleaning, chunking, manifests, cache identity, jobs, progress events,
audio validation, and M4B assembly must not depend on OpenAI-specific types. A
provider adapter implements the `TTSProvider` contract and declares capabilities,
models, voices, request limits, pricing metadata, and credential requirements.

Cache and manifest identities always include provider plus model. Switching
providers can never reuse incompatible narration audio accidentally.

## ElevenLabs / ElevenReader integration target — UNTESTED

> **UNTESTED:** The implementation has deterministic offline coverage but has not
> been verified against the live ElevenLabs API. It must retain this label in the
> registry and user interface until an explicitly authorized live test succeeds.

ElevenReader is the listener-facing product, while the supported developer speech
API is provided by **ElevenLabs**. The application therefore uses provider ID
`elevenlabs`, display name `ElevenLabs / ElevenReader (UNTESTED)`, and a separately stored
`ELEVENLABS_API_KEY`. Credential records are namespaced by provider; selecting or
removing one provider never exposes, overwrites, or deletes another provider's key.

The synthesis adapter calls the ElevenLabs text-to-speech endpoint with a stable
voice ID and model ID, requests `pcm_24000`, and atomically wraps the returned raw
audio in a validated mono 24 kHz WAV. It passes provider request IDs through to the
generation result and maps failures without exposing response bodies or credentials.
Voice choices come from an explicit-only, paginated provider voice search. Model
metadata, TTS capability, character limits, and cost multipliers come from the model
endpoint rather than being silently assumed. `eleven_multilingual_v2` is the initial
long-form candidate, but the selected model and its current limits must be persisted
in the job manifest.

`TTSProvider` requires validated WAV output. Cache identity includes `elevenlabs`,
the model, voice ID,
speed, instructions, and normalized text so output can never collide with OpenAI
narration.

ElevenLabs billing is character based. The offline estimator uses only the verified
PAYG model allowlist: $0.05 per 1,000 characters for Flash/Turbo and $0.10 per 1,000
characters for Multilingual v2/v3, then adds the standard 15% safety margin. Unknown
models and voices with custom rates fail closed instead of receiving a guessed price.
The adapter surfaces provider request IDs, and runtime wiring must also record the
`character-cost` response header for reconciliation, enforce global and per-job
spending caps, and require explicit confirmation before the first live request.
Bundled local voice samples remain the normal audition path so browsing voices never
consumes credits.

The synthesis and catalog milestones include redacted error mapping, PCM/WAV
validation, retry classification, explicit paginated discovery, and deterministic
fake-transport tests. The next milestone adds guarded runtime selection and
provider-specific pricing. No milestone may add an automatic connection test or
make a live request in CI.

## Provider onboarding contract

Onboarding starts with a provider selector backed by the provider registry. Each
provider owns:

- display name and capability flags;
- official key-creation and billing URLs;
- masked credential input and keyring service name;
- connection-test implementation and redacted error mapping;
- models, voices, request limits, pricing, and spending controls.

Provider setup remains skippable. No provider connection test or model request runs
automatically. A real request requires a cost estimate and explicit confirmation.
