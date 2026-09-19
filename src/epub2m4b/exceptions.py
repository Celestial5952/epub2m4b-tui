"""Typed errors crossing EPUB2M4B subsystem boundaries."""


class Epub2M4BError(Exception):
    """Base error suitable for friendly CLI/TUI rendering."""


class ConfigurationError(Epub2M4BError):
    """Configuration is invalid or cannot be loaded."""


class CredentialError(Epub2M4BError):
    """A provider credential could not be safely read or changed."""


class EpubError(Epub2M4BError):
    """An EPUB is malformed, unsafe, or unsupported."""


class LibraryError(Epub2M4BError):
    """A configured book library cannot be scanned safely."""


class ManifestError(Epub2M4BError):
    """Persistent job state is missing, corrupt, or incompatible."""


class UnsupportedManifestVersionError(ManifestError):
    """A manifest was written by an unsupported schema version."""


class ProviderError(Epub2M4BError):
    """Base failure returned by a TTS provider."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class GenerationError(Epub2M4BError):
    """A narration job could not safely make further progress."""


class DuplicatePreparationError(GenerationError):
    """An equivalent job already exists and must not be silently replaced."""

    def __init__(self, existing_job_id: str) -> None:
        super().__init__(
            "an equivalent audiobook job already exists; open it in Jobs instead"
        )
        self.existing_job_id = existing_job_id


class AudioValidationError(Epub2M4BError):
    """Generated or assembled audio did not pass validation."""


class ExternalToolError(Epub2M4BError):
    """FFmpeg, FFprobe, or another required executable failed."""
