from epub2m4b.providers.base import SynthesisRequest, SynthesisResult, TTSProvider
from epub2m4b.providers.elevenlabs_catalog import (
    ElevenLabsCatalog,
    ElevenLabsModel,
    ElevenLabsVoice,
    ElevenLabsVoicePage,
)
from epub2m4b.providers.elevenlabs_tts import ElevenLabsTTSProvider
from epub2m4b.providers.fake import FakeTTSProvider
from epub2m4b.providers.openai_tts import OpenAITTSProvider
from epub2m4b.providers.registry import (
    TEXT_TO_SPEECH,
    ProviderMetadata,
    ProviderRegistry,
    ProviderRegistryError,
    default_provider_registry,
)

__all__ = [
    "FakeTTSProvider",
    "ElevenLabsCatalog",
    "ElevenLabsModel",
    "ElevenLabsTTSProvider",
    "ElevenLabsVoice",
    "ElevenLabsVoicePage",
    "OpenAITTSProvider",
    "SynthesisRequest",
    "SynthesisResult",
    "TTSProvider",
    "TEXT_TO_SPEECH",
    "ProviderMetadata",
    "ProviderRegistry",
    "ProviderRegistryError",
    "default_provider_registry",
]
