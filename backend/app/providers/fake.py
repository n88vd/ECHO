"""Deterministic providers for tests and offline development (0 credits)."""

import hashlib
import io
import json
import re
import uuid
import wave
from typing import Any

import numpy as np

from app.core.config import get_settings
from app.providers.base import BatchStatus, SttChunk, SttResult

FAKE_TRANSCRIPTS: dict[str, SttResult] = {}
FAKE_DEFAULT: list[SttResult] = []
_BATCH: dict[str, dict[str, SttResult]] = {}

_STOP = {"the", "a", "an", "i", "my", "to", "of", "and", "is", "was", "what", "did", "do", "where", "who", "me", "you", "it", "in", "on", "at", "for", "that", "this", "about"}


def tokens(text: str) -> list[str]:
    out = []
    for t in re.findall(r"\w+", text.lower()):
        if t in _STOP:
            continue
        out.append(t[:-1] if len(t) > 4 and t.endswith("s") else t)
    return out


class FakeSTT:
    async def transcribe(self, audio: bytes, filename: str, language: str = "unknown", keyterms: list[str] | None = None) -> SttResult:
        key = hashlib.sha256(audio).hexdigest()
        if key in FAKE_TRANSCRIPTS:
            return FAKE_TRANSCRIPTS[key]
        if FAKE_DEFAULT:
            return FAKE_DEFAULT[-1]
        return SttResult(transcript="", language_code=None, language_prob=None, chunks=[], request_id="fake")

    async def submit_batch(self, files, language, keyterms, callback_url) -> str:
        job = str(uuid.uuid4())
        res = {}
        for name, data in files:
            base = await self.transcribe(data, name, language, keyterms)
            res[name] = SttResult(
                transcript=base.transcript,
                language_code=base.language_code,
                language_prob=base.language_prob,
                chunks=[SttChunk(c.text, c.start_s, c.end_s, speaker=f"SPEAKER_0{i % 2}") for i, c in enumerate(base.chunks)],
            )
        _BATCH[job] = res
        return job

    async def batch_status(self, job_id: str) -> BatchStatus:
        return BatchStatus(state="Completed", outputs={n: n + ".json" for n in _BATCH.get(job_id, {})})

    async def batch_results(self, job_id: str, output_files: list[str]) -> dict[str, SttResult]:
        return {n + ".json": r for n, r in _BATCH.get(job_id, {}).items() if n + ".json" in output_files}


class FakeEmbeddings:
    model_id = "fake-hash@1536"

    async def embed(self, texts: list[str]) -> tuple[list[list[float]], int]:
        dims = get_settings().embedding_dimensions
        out = []
        for t in texts:
            v = np.zeros(dims, dtype=np.float32)
            for tok in tokens(t):
                h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
                v[h % dims] += 1.0 if (h >> 64) & 1 else -1.0
            n = np.linalg.norm(v)
            out.append((v / n if n else v).tolist())
        return out, sum(len(t) // 4 for t in texts)


class FakeTTS:
    async def synthesize(self, text: str, language: str) -> tuple[bytes, str]:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x00\x00" * 1600)
        return buf.getvalue(), "audio/wav"


_PROMISE = re.compile(r"\b(i will|i'll|promise[d]?|i shall|will send|will call)\b", re.I)
_LOCATION = re.compile(r"\b(kept|put|left|placed)\b.*\b(in|on|under|inside|at)\b", re.I)
_DECISION = re.compile(r"\b(decided|rejected|chose|choose|going with)\b", re.I)


class FakeLLM:
    async def json(self, system: str, user: str, schema: dict[str, Any], name: str, tier: str = "reasoning", max_tokens: int = 4000):
        payload = json.loads(user)
        fn = getattr(self, f"_{name}", None)
        if fn is None:
            raise ValueError(f"FakeLLM has no handler for {name}")
        return fn(payload), 100

    async def text(self, system: str, user: str, tier: str = "reasoning", max_tokens: int = 1200):
        payload = json.loads(user)
        mems = payload.get("memories") or []
        if "digest" in system.lower():
            return "Today: " + "; ".join(m["content"] for m in mems[:5]), 50
        if not mems:
            return "I don't have a memory of that.", 20
        top = mems[0]
        return f"{top['content']} [m:{top['id']}]", 40

    def _understand(self, p: dict) -> dict:
        memories = []
        utts = p["utterances"]
        for u in utts:
            text = u["text"]
            people = re.findall(r"\b([A-Z][a-z]{2,})\b", text)
            people = [x for x in people if x not in {"I", "The", "Echo", "Remember"}]
            mtype, commitment, decision = "fact", None, None
            if _PROMISE.search(text):
                mtype = "commitment"
                commitment = {"owner": "user" if u["speaker"] in ("you", "unknown") else "other", "counterparty": people[0] if people else "", "action": text, "due": ""}
            elif _LOCATION.search(text):
                mtype = "object_location"
            elif _DECISION.search(text):
                mtype = "decision"
                decision = {"choice": text, "rationale": text, "alternatives": []}
            objs = re.findall(r"\b(passport|keys?|wallet|charger|laptop|phone)\b", text, re.I)
            memories.append({
                "type": mtype,
                "content_en": text,
                "content_native": text,
                "evidence_utterance_ids": [u["id"]],
                "subject": u["speaker"],
                "people": people,
                "places": [],
                "objects": [o.lower() for o in objs],
                "topics": [],
                "time_ref_text": "",
                "resolved_start": "",
                "resolved_end": "",
                "commitment": commitment,
                "decision": decision,
                "importance": 0.6,
                "confidence": 0.8,
                "sensitivity": [],
            })
        title = utts[0]["text"][:60] if utts else "Conversation"
        return {
            "title_en": title,
            "summary_en": " ".join(u["text"] for u in utts)[:400],
            "topics": [],
            "utterances_en": [{"id": u["id"], "text_en": u["text"]} for u in utts],
            "remember_this": any("remember this" in u["text"].lower() for u in utts),
            "memories": memories,
        }

    def _query_parse(self, p: dict) -> dict:
        q = p["query"]
        return {
            "query_en": q,
            "language": p.get("language") or "en-IN",
            "intent": "recall",
            "people": [x for x in re.findall(r"\b([A-Z][a-z]{2,})\b", q) if x not in {"What", "Where", "Who", "When", "Why", "How", "Remind", "Did"}],
            "objects": re.findall(r"\b(passport|keys?|wallet|charger|laptop|phone)\b", q, re.I),
            "memory_types": [],
            "time_from": "",
            "time_to": "",
            "wants_latest": bool(re.search(r"\bwhere\b", q, re.I)),
        }

    def _rerank(self, p: dict) -> dict:
        return {"ranked_ids": [c["id"] for c in p["candidates"]][:8]}

    def _commitment_check(self, p: dict) -> dict:
        return {"resolved": [], }
