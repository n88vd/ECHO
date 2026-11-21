from dataclasses import dataclass, field
from typing import Any, Protocol


class ProviderError(Exception):
    def __init__(self, msg: str, retryable: bool = True):
        super().__init__(msg)
        self.retryable = retryable


@dataclass
class SttChunk:
    text: str
    start_s: float
    end_s: float
    speaker: str | None = None


@dataclass
class SttResult:
    transcript: str
    language_code: str | None
    language_prob: float | None
    chunks: list[SttChunk] = field(default_factory=list)
    request_id: str | None = None


@dataclass
class BatchStatus:
    state: str
    outputs: dict[str, str] = field(default_factory=dict)
    error: str | None = None


class STTProvider(Protocol):
    async def transcribe(
        self, audio: bytes, filename: str, language: str = "unknown", keyterms: list[str] | None = None
    ) -> SttResult: ...

    async def submit_batch(
        self, files: list[tuple[str, bytes]], language: str, keyterms: list[str] | None, callback_url: str | None
    ) -> str: ...

    async def batch_status(self, job_id: str) -> BatchStatus: ...

    async def batch_results(self, job_id: str, output_files: list[str]) -> dict[str, SttResult]: ...


class LLMProvider(Protocol):
    async def json(
        self, system: str, user: str, schema: dict[str, Any], name: str, tier: str = "reasoning", max_tokens: int = 4000
    ) -> tuple[dict[str, Any], int]: ...

    async def text(self, system: str, user: str, tier: str = "reasoning", max_tokens: int = 1200) -> tuple[str, int]: ...


class EmbeddingProvider(Protocol):
    model_id: str

    async def embed(self, texts: list[str]) -> tuple[list[list[float]], int]: ...


class TTSProvider(Protocol):
    async def synthesize(self, text: str, language: str) -> tuple[bytes, str]: ...
