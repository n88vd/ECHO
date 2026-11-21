import asyncio
import base64
import json
import random
from typing import Any

import httpx
from sarvamai import AsyncSarvamAI

from app.core.config import get_settings
from app.providers.base import BatchStatus, ProviderError, SttChunk, SttResult

TTS_LANGS = {"bn-IN", "en-IN", "gu-IN", "hi-IN", "kn-IN", "ml-IN", "mr-IN", "od-IN", "pa-IN", "ta-IN", "te-IN"}


def _parse_stt(data: dict[str, Any]) -> SttResult:
    chunks: list[SttChunk] = []
    diar = (data.get("diarized_transcript") or {}).get("entries") or []
    if diar:
        for e in diar:
            chunks.append(
                SttChunk(
                    text=(e.get("transcript") or "").strip(),
                    start_s=float(e.get("start_time_seconds") or 0),
                    end_s=float(e.get("end_time_seconds") or 0),
                    speaker=str(e.get("speaker_id")) if e.get("speaker_id") is not None else None,
                )
            )
    else:
        ts = data.get("timestamps") or {}
        for text, st, en in zip(
            ts.get("words") or [], ts.get("start_time_seconds") or [], ts.get("end_time_seconds") or [], strict=False
        ):
            chunks.append(SttChunk(text=(text or "").strip(), start_s=float(st), end_s=float(en)))
    transcript = (data.get("transcript") or "").strip()
    if not chunks and transcript:
        chunks = [SttChunk(text=transcript, start_s=0.0, end_s=0.0)]
    return SttResult(
        transcript=transcript,
        language_code=data.get("language_code"),
        language_prob=data.get("language_probability"),
        chunks=[c for c in chunks if c.text],
        request_id=data.get("request_id"),
    )


class SarvamSTT:
    def __init__(self) -> None:
        s = get_settings()
        self.s = s
        self.http = httpx.AsyncClient(
            base_url=s.sarvam_base_url, headers={"api-subscription-key": s.sarvam_api_key}, timeout=httpx.Timeout(90, connect=10)
        )
        self.blob = httpx.AsyncClient(timeout=httpx.Timeout(120, connect=10))
        self.sdk = AsyncSarvamAI(api_subscription_key=s.sarvam_api_key)
        self.sem = asyncio.Semaphore(4)

    async def _post(self, path: str, **kw) -> dict[str, Any]:
        for attempt in range(5):
            async with self.sem:
                try:
                    r = await self.http.post(path, **kw)
                except httpx.TransportError as e:
                    err: Exception = e
                else:
                    if r.status_code < 400:
                        return r.json()
                    if r.status_code in (429, 500, 502, 503, 504):
                        err = ProviderError(f"sarvam {r.status_code}: {r.text[:200]}")
                    else:
                        raise ProviderError(f"sarvam {r.status_code}: {r.text[:300]}", retryable=False)
            await asyncio.sleep(min(30, 2**attempt + random.random()))
        raise ProviderError(f"sarvam retries exhausted: {err}")

    async def transcribe(self, audio: bytes, filename: str, language: str = "unknown", keyterms: list[str] | None = None) -> SttResult:
        data = {"model": self.s.sarvam_stt_model, "mode": "transcribe", "language_code": language, "with_timestamps": "true"}
        if keyterms:
            data["keyterms"] = json.dumps(keyterms[:50])
        ctype = "audio/ogg" if filename.endswith((".ogg", ".opus")) else "audio/wav"
        res = await self._post("/speech-to-text", data=data, files={"file": (filename, audio, ctype)})
        return _parse_stt(res)

    async def submit_batch(
        self, files: list[tuple[str, bytes]], language: str, keyterms: list[str] | None, callback_url: str | None
    ) -> str:
        params: dict[str, Any] = {
            "model": self.s.sarvam_stt_model,
            "mode": "transcribe",
            "language_code": language,
            "with_diarization": True,
            "with_timestamps": True,
        }
        if keyterms:
            params["keyterms"] = keyterms[:50]
        body: dict[str, Any] = {"job_parameters": params}
        if callback_url:
            body["callback"] = {"url": callback_url, "auth_token": self.s.sarvam_callback_token or None}
        job = await self._post("/speech-to-text/job/v1", json=body)
        job_id = job["job_id"]
        links = await self._post("/speech-to-text/job/v1/upload-files", json={"job_id": job_id, "files": [n for n, _ in files]})
        for name, data in files:
            url = links["upload_urls"][name]["file_url"]
            r = await self.blob.put(url, content=data, headers={"x-ms-blob-type": "BlockBlob", "Content-Type": "audio/wav"})
            if r.status_code >= 300:
                raise ProviderError(f"batch upload failed {r.status_code}")
        await self._post(f"/speech-to-text/job/v1/{job_id}/start")
        return job_id

    async def batch_status(self, job_id: str) -> BatchStatus:
        r = await self.http.get(f"/speech-to-text/job/v1/{job_id}/status")
        if r.status_code >= 400:
            raise ProviderError(f"status {r.status_code}", retryable=r.status_code >= 500 or r.status_code == 429)
        d = r.json()
        outputs = {}
        for det in d.get("job_details") or []:
            if det.get("inputs") and det.get("outputs") and det.get("state") == "Success":
                outputs[det["inputs"][0]["file_name"]] = det["outputs"][0]["file_name"]
        return BatchStatus(state=d.get("job_state", "Unknown"), outputs=outputs, error=d.get("error_message"))

    async def batch_results(self, job_id: str, output_files: list[str]) -> dict[str, SttResult]:
        links = await self._post("/speech-to-text/job/v1/download-files", json={"job_id": job_id, "files": output_files})
        out = {}
        for name in output_files:
            r = await self.blob.get(links["download_urls"][name]["file_url"])
            r.raise_for_status()
            out[name] = _parse_stt(r.json())
        return out


class SarvamTTS:
    def __init__(self) -> None:
        self.s = get_settings()
        self.stt = SarvamSTT()

    async def synthesize(self, text: str, language: str) -> tuple[bytes, str]:
        lang = language if language in TTS_LANGS else "en-IN"
        body = {
            "text": text[:2500],
            "language_code": lang,
            "model": self.s.sarvam_tts_model,
            "speaker": self.s.sarvam_tts_speaker,
            "output_audio_codec": "mp3",
            "speech_sample_rate": 22050,
        }
        res = await self.stt._post("/text-to-speech", json=body)
        return base64.b64decode("".join(res["audios"])), "audio/mpeg"
