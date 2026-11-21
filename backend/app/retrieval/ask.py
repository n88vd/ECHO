"""Ask ECHO: query understanding -> hybrid retrieval -> RRF -> rescoring -> LLM rerank -> cited answer -> verify."""

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.core import costs
from app.core.db import pool, vec
from app.pipeline.common import user_tz
from app.prompts import schemas
from app.prompts.text import ANSWER_SYSTEM, QUERY_SYSTEM, RERANK_SYSTEM
from app.providers import embeddings, llm
from app.retrieval.fusion import recency, rescore, rrf

CITE = re.compile(r"\[(m|u):([0-9a-f\-]{8,36})\]")


@dataclass
class Candidate:
    id: str
    kind: str
    content: str
    native: str | None
    captured_at: datetime
    mtype: str
    importance: float = 0.5
    quality: float = 0.7
    superseded: bool = False
    pinned: bool = False
    conversation_id: str | None = None
    entity_match: bool = False
    score: float = 0.0
    evidence: list[dict] = field(default_factory=list)


def _ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    except ValueError:
        return None


async def parse_query(user_id: str, query: str, language: str | None) -> dict:
    tz = await user_tz(user_id)
    payload = {"query": query, "language": language, "now": datetime.now(tz).isoformat(), "timezone": str(tz)}
    q, tokens = await llm().json(QUERY_SYSTEM, json.dumps(payload, ensure_ascii=False), schemas.QUERY_PARSE, "query_parse", tier="fast", max_tokens=500)
    await costs.record("azure_llm", tokens, "tokens", user_id)
    lang = (q.get("language") or "").strip()
    q["language"] = f"{lang.split('-')[0].lower()}-IN" if lang and len(lang.split("-")[0]) in (2, 3) else (language or "en-IN")
    if "object_location" in (q.get("memory_types") or []):
        q["wants_latest"] = True
    return q


async def _fetch(sql: str, *args, hnsw: bool = False):
    async with pool().acquire() as conn:
        return await conn.fetch(sql, *args)


async def _none():
    return []


BASE_FILTER = """m.user_id = $1 and m.deleted_at is null
                 and ($2::timestamptz is null or coalesce(m.time_start, m.captured_at) >= $2)
                 and ($3::timestamptz is null or coalesce(m.time_start, m.captured_at) <= $3)"""


async def retrieve(user_id: str, query: str, q: dict, vectors: list[list[float]], limit: int = 40) -> list[Candidate]:
    emb = embeddings()
    qtext = q.get("query_en") or query
    t_from, t_to = _ts(q.get("time_from")), _ts(q.get("time_to"))
    names = [n.lower() for n in (q.get("people") or []) + (q.get("objects") or []) if n]
    or_q = " OR ".join(re.findall(r"\w{3,}", qtext))
    vec_sql = f"""select m.id from echo.memories m where {BASE_FILTER} and m.embedding is not null and m.embedding_model = $5
                  order by m.embedding <=> $4::extensions.vector limit 50"""
    fts_sql = f"""select m.id from echo.memories m, websearch_to_tsquery('english', $4) tq
                  where {BASE_FILTER} and m.fts @@ tq order by ts_rank_cd(m.fts, tq) desc limit 50"""
    results = await asyncio.gather(
        *[_fetch(vec_sql, user_id, t_from, t_to, vec(v), emb.model_id, hnsw=True) for v in vectors],
        _fetch(fts_sql, user_id, t_from, t_to, qtext),
        _fetch(fts_sql, user_id, t_from, t_to, or_q) if or_q else _none(),
        _fetch(
            f"""select m.id from echo.memories m
                where {BASE_FILTER} and m.content_native is not null and word_similarity($4, m.content_native) > 0.3
                order by word_similarity($4, m.content_native) desc limit 20""",
            user_id, t_from, t_to, query,
        ),
        _fetch(
            f"""select distinct on (m.id) m.id from echo.entities e
                join echo.memory_entities me on me.entity_id = e.id join echo.memories m on m.id = me.memory_id
                where {BASE_FILTER} and e.user_id = $1 and (
                    lower(e.canonical_name) = any($4::text[])
                    or exists (select 1 from unnest(e.aliases) a where lower(a) = any($4::text[]))
                    or exists (select 1 from unnest($4::text[]) n where similarity(lower(e.canonical_name), n) > 0.5))
                limit 50""",
            user_id, t_from, t_to, names,
        ) if names else _none(),
        _fetch(
            """select u.id, coalesce(u.text_en, u.text_native) as content, u.text_native, u.created_at, u.quality_score,
                      u.conversation_id
               from echo.utterances u join echo.conversations c on c.id = u.conversation_id
               where u.user_id = $1 and c.status in ('open','closed') and u.created_at > now() - interval '30 minutes'
               order by u.created_at desc limit 30""",
            user_id,
        ),
    )
    nv = len(vectors)
    vec_lists, (fts_ids, fts_or, trgm_ids, ent_ids, recent_utts) = results[:nv], results[nv:]
    rankings = {f"vector{i}": [str(r["id"]) for r in rows] for i, rows in enumerate(vec_lists)}
    rankings.update({
        "fts": [str(r["id"]) for r in fts_ids],
        "fts_or": [str(r["id"]) for r in fts_or],
        "trgm": [str(r["id"]) for r in trgm_ids],
        "entity": [str(r["id"]) for r in ent_ids],
    })
    weights = {"fts": 1.0, "fts_or": 0.6, "trgm": 0.8, "entity": 1.2} | {f"vector{i}": 1.0 / nv for i in range(nv)}
    fused = rrf(rankings, weights=weights)
    ids = sorted(fused, key=fused.get, reverse=True)[:limit]
    rows, ev_rows = await asyncio.gather(
        _fetch(
            """select id, type, content_en, content_native, captured_at, importance, confidence, superseded_by, pinned, conversation_id
               from echo.memories where id = any($1::uuid[])""",
            ids,
        ) if ids else _none(),
        _fetch(
            """select me.memory_id, u.id as utterance_id, u.text_native, u.text_en, u.start_ms, u.segment_id, sp.label,
                      e.canonical_name as person
               from echo.memory_evidence me join echo.utterances u on u.id = me.utterance_id
               left join echo.speakers sp on sp.id = u.speaker_id left join echo.entities e on e.id = sp.person_id
               where me.memory_id = any($1::uuid[])""",
            ids,
        ) if ids else _none(),
    )
    ent_set = set(rankings["entity"])
    wanted_types = set(q.get("memory_types") or [])
    evidence: dict[str, list[dict]] = {}
    for e in ev_rows:
        evidence.setdefault(str(e["memory_id"]), []).append({
            "utterance_id": str(e["utterance_id"]), "quote_native": e["text_native"], "quote_en": e["text_en"],
            "speaker": e["person"] or e["label"], "segment_id": str(e["segment_id"]) if e["segment_id"] else None,
            "start_ms": e["start_ms"],
        })
    cands = []
    for r in rows:
        mid = str(r["id"])
        c = Candidate(
            id=mid, kind="m", content=r["content_en"], native=r["content_native"], captured_at=r["captured_at"],
            mtype=r["type"], importance=r["importance"], quality=r["confidence"], superseded=r["superseded_by"] is not None,
            pinned=r["pinned"], conversation_id=str(r["conversation_id"]) if r["conversation_id"] else None,
            entity_match=mid in ent_set, evidence=evidence.get(mid, []),
        )
        c.score = rescore(fused[mid], c.importance, recency(c.captured_at, c.mtype), c.quality, c.superseded,
                          bool(q.get("wants_latest")), c.pinned, c.mtype in wanted_types, c.entity_match)
        cands.append(c)
    for u in recent_utts:
        c = Candidate(id=str(u["id"]), kind="u", content=u["content"], native=u["text_native"], captured_at=u["created_at"],
                      mtype="utterance", quality=u["quality_score"] or 0.5, conversation_id=str(u["conversation_id"]))
        c.score = 0.25 + 0.3 * recency(c.captured_at, "utterance")
        cands.append(c)
    cands.sort(key=lambda c: c.score, reverse=True)
    return cands


async def rerank(user_id: str, query: str, cands: list[Candidate]) -> list[Candidate]:
    if len(cands) <= 8:
        return cands
    top = cands[:30]
    payload = {"question": query, "candidates": [
        {"id": c.id, "type": c.mtype, "date": c.captured_at.date().isoformat(), "content": c.content, "superseded": c.superseded}
        for c in top
    ]}
    res, tokens = await llm().json(RERANK_SYSTEM, json.dumps(payload, ensure_ascii=False), schemas.RERANK, "rerank", tier="fast", max_tokens=600)
    await costs.record("azure_llm", tokens, "tokens", user_id)
    by_id = {c.id: c for c in top}
    ranked = [by_id[i] for i in res.get("ranked_ids", []) if i in by_id]
    return ranked or top[:8]


def verify_citations(answer: str, allowed: dict[str, Candidate]) -> tuple[str, list[Candidate]]:
    used: list[Candidate] = []

    def repl(m: re.Match) -> str:
        cid = m.group(2)
        hit = allowed.get(cid) or next((c for k, c in allowed.items() if k.startswith(cid)), None)
        if not hit:
            return ""
        if hit not in used:
            used.append(hit)
        return f"[{hit.kind}:{hit.id}]"

    cleaned = CITE.sub(repl, answer)
    return re.sub(r"\s{2,}", " ", cleaned).strip(), used


async def answer(user_id: str, query: str, language: str | None = None) -> dict:
    t0 = time.perf_counter()
    timings: dict[str, int] = {}

    def mark(name: str, since: float) -> float:
        now = time.perf_counter()
        timings[name] = int((now - since) * 1000)
        return now

    emb = embeddings()
    q, (raw_vecs, tok) = await asyncio.gather(parse_query(user_id, query, language), emb.embed([query]))
    t = mark("parse+embed", t0)
    vectors = list(raw_vecs)
    q_en = (q.get("query_en") or "").strip()
    if q_en and q_en.lower() != query.strip().lower():
        more, tok2 = await emb.embed([q_en])
        vectors.append(more[0])
        tok += tok2
        t = mark("embed_en", t)
    await costs.record("azure_embed", tok, "tokens", user_id)
    answer_lang = language or q.get("language") or "en-IN"
    cands = await retrieve(user_id, query, q, vectors)
    t = mark("retrieve", t)
    top = (await rerank(user_id, query, cands))[:8]
    t = mark("rerank", t)
    tz = await user_tz(user_id)
    payload = {
        "question": query,
        "answer_language": answer_lang,
        "now": datetime.now(tz).isoformat(),
        "memories": [
            {"id": f"{c.kind}:{c.id}", "type": c.mtype, "date": c.captured_at.astimezone(tz).strftime("%d %b %Y %H:%M"),
             "content": c.content, "superseded_by_newer": c.superseded,
             "evidence": [{"speaker": e["speaker"], "quote": e["quote_en"] or e["quote_native"]} for e in c.evidence[:3]]}
            for c in top
        ],
    }
    if not top:
        text = "I don't have a memory of that yet."
        used: list[Candidate] = []
    else:
        raw, tokens = await llm().text(ANSWER_SYSTEM, json.dumps(payload, ensure_ascii=False), max_tokens=700)
        await costs.record("azure_llm", tokens, "tokens", user_id)
        text, used = verify_citations(raw.replace("[m:m:", "[m:").replace("[u:u:", "[u:"), {c.id: c for c in top})
        mark("answer", t)
    citations = [
        {"id": c.id, "kind": "memory" if c.kind == "m" else "utterance", "type": c.mtype, "content": c.content,
         "content_native": c.native, "captured_at": c.captured_at.isoformat(), "conversation_id": c.conversation_id,
         "superseded": c.superseded, "evidence": c.evidence[:3]}
        for c in used
    ]
    latency = int((time.perf_counter() - t0) * 1000)
    ask_id = await pool().fetchval(
        """insert into echo.ask_log(user_id, query_native, query_en, query_language, answer_text, citations, latency_ms)
           values ($1,$2,$3,$4,$5,$6,$7) returning id""",
        user_id, query, q.get("query_en"), answer_lang, text, [c["id"] for c in citations], latency,
    )
    await costs.add_ask(user_id)
    return {"ask_id": str(ask_id), "answer": text, "answer_language": answer_lang, "citations": citations,
            "query": {"en": q.get("query_en"), "intent": q.get("intent")}, "latency_ms": latency, "timings": timings}
