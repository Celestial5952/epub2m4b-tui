# EPUB2M4B Development Roadmap

This document outlines the current development path and upcoming milestones for EPUB2M4B.

---

## 1. Active Development Focus: ElevenLabs TTS Integration

The immediate priority is completing the full, guarded integration of the **ElevenLabs / ElevenReader** TTS provider. The offline foundations (synthesis adapter, catalog, and pricing estimator) are completed. The remaining work wires ElevenLabs safely into the UI, settings, generation engine, and spending controls.

> **Safety Rule:** All automated tests must use mocked responses (`FakeTransport` / `FakeTTSProvider`). Live API calls require explicit user authorization, a displayed estimate, and bounded test scope.

### ElevenLabs Task Breakdown

| Task ID | Component | Status | Deliverable & Acceptance Criteria |
|---|---|---|---|
| **E1** | Synthesis Adapter | **Completed (Offline)** | `ElevenLabsTTSProvider` implementation with PCM-to-WAV normalization, atomic writes, request IDs, and redacted errors. |
| **E2** | Voice & Model Catalog | **Completed (Offline)** | Paginated voice query, TTS model validation, request limit resolution, and character multiplier handling. |
| **E3** | Pricing Estimator | **Completed (Offline)** | PAYG pricing matrix ($0.05/1k chars for Turbo/Flash, $0.10/1k for Multilingual v2), 15% safety margin, fail-closed behavior for unknown models. |
| **E4** | Settings & Keyring Wiring | **Next Up** | - Add ElevenLabs credential management in Settings screen.<br>- Securely save/read `ELEVENLABS_API_KEY` in system keyring (namespace isolated from OpenAI).<br>- Dynamic model & voice selector in Settings and Job creation modals.<br>- No plaintext secrets in UI or logs. |
| **E5** | Coordinator & Chunk Limits | **Next Up** | - Reconcile ElevenLabs chunk character limits (e.g. 5,000–10,000 characters depending on tier/model) with chunker.<br>- Content-addressed cache key isolation (`elevenlabs` namespace prevent audio collision with OpenAI).<br>- Retry and backoff tuning for ElevenLabs 429 rate limits. |
| **E6** | Spending Guard & Live Smoke Test | **Next Up** | - Enforce per-job and lifetime spending caps for ElevenLabs jobs.<br>- Confirmation modal displaying character count, model rate, and 15% safety buffer.<br>- One bounded live smoke test with an authorized key on a tiny public-domain chapter.<br>- Remove `UNTESTED live` label once live verification passes. |

---

## 2. Next Milestone: GitHub Open Source Launch

Once ElevenLabs integration is stabilized, the project will be prepared for public release on GitHub.

| Item | Scope | Acceptance Criteria |
|---|---|---|
| **Licensing** | Add root `LICENSE` file | GPL-3.0-or-later license file added at repository root matching `pyproject.toml` and Debian packaging copyright. |
| **Repository Hygiene** | Clean Git initialization | Initialize repository with clean history; exclude local test epubs, `.deb` packages, and internal notes. |
| **Security Automation** | Automated secret scan | Pre-commit check and CI step running `scripts/security_check.py` to prevent any accidental API key leaks. |
| **Public Documentation** | Public README & Guide | - Visual screenshots and terminal demos of Textual TUI.<br>- Step-by-step installation (`pipx`, `.deb`).<br>- System prerequisites (`ffmpeg`, audio utilities).<br>- Contributing guide (`CONTRIBUTING.md`) and Security policy (`SECURITY.md`). |
| **GitHub Actions CI** | Automated test pipeline | Workflow running `pytest` (455+ tests) and `ruff check` on Ubuntu runners across supported Python versions (3.12+). |

---

## 3. Subsequent Milestone: Distribution & Usability Polish

| Area | Focus |
|---|---|
| **First-Time User UX** | Refine mouse interactions, file picker usability, keyboard navigation, and progress feedback for users unfamiliar with terminal applications. |
| **Ubuntu Packaging** | Validate Debian package installation, upgrades, desktop entry integration, and uninstallation on clean Ubuntu 24.04 and 26.04 environments. |
| **Release Automation** | Automate `.deb` package and Python wheel generation as part of GitHub Release workflows. |

---

## 4. Future Milestone: Local / Offline TTS Provider

To enable completely free and offline audiobook generation:
- Explore integration of local open neural TTS models (e.g., **Piper TTS** or **Kokoro TTS**).
- Implement a provider adapter implementing `TTSProvider` for local execution without API keys or costs.
- Provide bundled local models for common languages.
