import asyncio
import json
from typing import Any

from openai import APIConnectionError, APIStatusError, AsyncOpenAI, RateLimitError

from app.core.config import get_settings
from app.providers.base import ProviderError


def _client() -> AsyncOpenAI:
    s = get_settings()
    return AsyncOpenAI(base_url=s.azure_openai_base_url, api_key=s.azure_openai_api_key, max_retries=4, timeout=120)


async def _with_retry(fn):
    for attempt in range(4):
        try:
            return await fn()
        except (RateLimitError, APIConnectionError) as e:
            err: Exception = e
        except APIStatusError as e:
            if e.status_code < 500:
                raise ProviderError(f"azure {e.status_code}: {str(e)[:300]}", retryable=False) from e
            err = e
        await asyncio.sleep(2 ** (attempt + 1))
    raise ProviderError(f"azure retries exhausted: {err}")


class AzureLLM:
    def __init__(self) -> None:
        self.s = get_settings()
        self.client = _client()

    def _model(self, tier: str) -> str:
        return self.s.llm_deployment_fast if tier == "fast" else self.s.llm_deployment_reasoning

    def _extra(self, tier: str) -> dict:
        if tier == "extract":
            return {}
        effort = self.s.llm_reasoning_effort if tier == "reasoning" else self.s.llm_fast_reasoning_effort
        return {"reasoning_effort": effort} if effort else {}

    async def json(
        self, system: str, user: str, schema: dict[str, Any], name: str, tier: str = "reasoning", max_tokens: int = 4000
    ) -> tuple[dict[str, Any], int]:
        async def call():
            return await self.client.chat.completions.create(
                model=self._model(tier),
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format={"type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": True}},
                max_completion_tokens=max_tokens,
                **self._extra(tier),
            )

        resp = await _with_retry(call)
        content = resp.choices[0].message.content or "{}"
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ProviderError(f"invalid JSON from LLM: {content[:200]}") from e
        return data, (resp.usage.total_tokens if resp.usage else 0)

    async def text(self, system: str, user: str, tier: str = "reasoning", max_tokens: int = 1200) -> tuple[str, int]:
        async def call():
            return await self.client.chat.completions.create(
                model=self._model(tier),
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                max_completion_tokens=max_tokens,
                **self._extra(tier),
            )

        resp = await _with_retry(call)
        return (resp.choices[0].message.content or "").strip(), (resp.usage.total_tokens if resp.usage else 0)


class AzureEmbeddings:
    def __init__(self) -> None:
        self.s = get_settings()
        self.client = _client()
        self.model_id = f"{self.s.embedding_deployment}@{self.s.embedding_dimensions}"

    async def embed(self, texts: list[str]) -> tuple[list[list[float]], int]:
        out: list[list[float]] = []
        tokens = 0
        for i in range(0, len(texts), 64):
            batch = [t[:8000] or " " for t in texts[i : i + 64]]

            async def call(batch=batch):
                return await self.client.embeddings.create(
                    model=self.s.embedding_deployment, input=batch, dimensions=self.s.embedding_dimensions
                )

            resp = await _with_retry(call)
            out.extend(d.embedding for d in sorted(resp.data, key=lambda d: d.index))
            tokens += resp.usage.total_tokens if resp.usage else 0
        return out, tokens
