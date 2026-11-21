from functools import lru_cache

from app.core.config import get_settings
from app.providers.base import EmbeddingProvider, LLMProvider, STTProvider, TTSProvider


@lru_cache
def stt() -> STTProvider:
    if get_settings().providers == "live":
        from app.providers.sarvam import SarvamSTT

        return SarvamSTT()
    from app.providers.fake import FakeSTT

    return FakeSTT()


@lru_cache
def tts() -> TTSProvider:
    if get_settings().providers == "live":
        from app.providers.sarvam import SarvamTTS

        return SarvamTTS()
    from app.providers.fake import FakeTTS

    return FakeTTS()


@lru_cache
def llm() -> LLMProvider:
    if get_settings().providers == "live":
        from app.providers.azure import AzureLLM

        return AzureLLM()
    from app.providers.fake import FakeLLM

    return FakeLLM()


@lru_cache
def embeddings() -> EmbeddingProvider:
    if get_settings().providers == "live":
        from app.providers.azure import AzureEmbeddings

        return AzureEmbeddings()
    from app.providers.fake import FakeEmbeddings

    return FakeEmbeddings()
