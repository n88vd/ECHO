from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CurrentUser, CurrentUserDep, not_found
from app.api.schemas import CommitmentPatch, MemoryPatch, SpeakerLabelIn
from app.core import costs
from app.core.config import get_settings
from app.core.db import pool, user_conn, vec
from app.core.storage import storage
from app.pipeline.entities import resolve_entity
from app.pipeline.understand import refresh_people
from app.providers import embeddings

router = APIRouter(prefix="/v1", tags=["memories"])


def _iso(d):
    return d.isoformat() if d else None


@router.get("/timeline")
async def timeline(before: datetime | None = None, limit: int = Query(20, ge=1, le=100), q: str | None = None,
                   user: CurrentUser = CurrentUserDep):
    async with user_conn(user.id) as conn:
        convs = await conn.fetch(
            """select c.id, c.started_at, c.ended_at, c.status, c.title_en, c.summary_en, c.languages, c.pinned, c.in_transit,
                      c.speaker_count, e.canonical_name as place
               from echo.conversations c left join echo.entities e on e.id = c.place_id
               where c.user_id = $1 and ($2::timestamptz is null or c.started_at < $2)
                 and ($4::text is null or c.title_en ilike '%' || $4 || '%' or c.summary_en ilike '%' || $4 || '%')
                 and exists (select 1 from echo.utterances u where u.conversation_id = c.id)
               order by c.started_at desc limit $3""",
            user.id, before, limit, q,
        )
        ids = [c["id"] for c in convs]
        mems = await conn.fetch(
            """select id, conversation_id, type, content_en, importance, pinned from echo.memories
               where conversation_id = any($1::uuid[]) and deleted_at is null order by importance desc""",
            ids,
        ) if ids else []
        people = await conn.fetch(
            """select distinct m.conversation_id, e.id, e.canonical_name from echo.memory_entities me
               join echo.memories m on m.id = me.memory_id join echo.entities e on e.id = me.entity_id
               where m.conversation_id = any($1::uuid[]) and e.kind = 'person'""",
            ids,
        ) if ids else []
    by_conv: dict = {}
    for m in mems:
        by_conv.setdefault(m["conversation_id"], []).append(
            {"id": str(m["id"]), "type": m["type"], "content": m["content_en"], "importance": m["importance"], "pinned": m["pinned"]}
        )
    ppl: dict = {}
    for p in people:
        ppl.setdefault(p["conversation_id"], []).append({"id": str(p["id"]), "name": p["canonical_name"]})
    items = [
        {"id": str(c["id"]), "started_at": _iso(c["started_at"]), "ended_at": _iso(c["ended_at"]), "status": c["status"],
         "title": c["title_en"] or ("Processing…" if c["status"] != "understood" else "Conversation"),
         "summary": c["summary_en"], "languages": c["languages"], "pinned": c["pinned"], "in_transit": c["in_transit"],
         "speaker_count": c["speaker_count"], "place": c["place"], "people": ppl.get(c["id"], []),
         "memories": by_conv.get(c["id"], [])[:5], "memory_count": len(by_conv.get(c["id"], []))}
        for c in convs
    ]
    return {"items": items, "next_before": items[-1]["started_at"] if len(items) == limit else None}


async def _clip_url(segment_id, storage_path, deleted_at) -> str | None:
    if not storage_path or deleted_at:
        return None
    try:
        return await storage().signed_download_url(storage_path, 900)
    except Exception:
        return None


@router.get("/memories/{memory_id}")
async def memory_detail(memory_id: str, user: CurrentUser = CurrentUserDep):
    async with user_conn(user.id) as conn:
        m = await conn.fetchrow(
            """select m.*, c.title_en as conversation_title, c.started_at as conversation_started, e.canonical_name as place
               from echo.memories m left join echo.conversations c on c.id = m.conversation_id
               left join echo.entities e on e.id = m.place_id where m.id = $1 and m.deleted_at is null""",
            memory_id,
        )
        if m is None:
            raise not_found("memory not found")
        ev = await conn.fetch(
            """select u.id, u.text_native, u.text_en, u.start_ms, u.end_ms, u.language, sg.id as segment_id, sg.started_at,
                      sg.storage_path, sg.audio_deleted_at, sp.id as speaker_id, sp.label, sp.is_user, pe.canonical_name as person
               from echo.memory_evidence me join echo.utterances u on u.id = me.utterance_id
               left join echo.audio_segments sg on sg.id = u.segment_id
               left join echo.speakers sp on sp.id = u.speaker_id left join echo.entities pe on pe.id = sp.person_id
               where me.memory_id = $1 order by sg.started_at, u.start_ms""",
            memory_id,
        )
        ents = await conn.fetch(
            """select e.id, e.kind, e.canonical_name, me.role from echo.memory_entities me join echo.entities e on e.id = me.entity_id
               where me.memory_id = $1""",
            memory_id,
        )
        links = await conn.fetch(
            """select l.kind, l.score, l.dst_memory_id as other, 'out' as dir, o.content_en, o.captured_at
               from echo.memory_links l join echo.memories o on o.id = l.dst_memory_id where l.src_memory_id = $1 and o.deleted_at is null
               union all
               select l.kind, l.score, l.src_memory_id, 'in', o.content_en, o.captured_at
               from echo.memory_links l join echo.memories o on o.id = l.src_memory_id where l.dst_memory_id = $1 and o.deleted_at is null""",
            memory_id,
        )
        commitment = await conn.fetchrow("select * from echo.commitments where memory_id = $1", memory_id)
    return {
        "id": str(m["id"]), "type": m["type"], "content": m["content_en"], "content_native": m["content_native"],
        "importance": m["importance"], "confidence": m["confidence"], "pinned": m["pinned"], "sensitivity": m["sensitivity"],
        "captured_at": _iso(m["captured_at"]), "time_start": _iso(m["time_start"]), "time_end": _iso(m["time_end"]),
        "place": m["place"], "superseded_by": str(m["superseded_by"]) if m["superseded_by"] else None,
        "conversation": {"id": str(m["conversation_id"]) if m["conversation_id"] else None, "title": m["conversation_title"],
                         "started_at": _iso(m["conversation_started"])},
        "evidence": [
            {"utterance_id": str(e["id"]), "quote_native": e["text_native"], "quote_en": e["text_en"], "language": e["language"],
             "speaker": {"id": str(e["speaker_id"]) if e["speaker_id"] else None, "label": e["person"] or e["label"], "is_user": e["is_user"]},
             "spoken_at": _iso(e["started_at"]), "start_ms": e["start_ms"], "end_ms": e["end_ms"],
             "audio_url": await _clip_url(e["segment_id"], e["storage_path"], e["audio_deleted_at"])}
            for e in ev
        ],
        "entities": [{"id": str(e["id"]), "kind": e["kind"], "name": e["canonical_name"], "role": e["role"]} for e in ents],
        "links": [{"kind": lk["kind"], "direction": lk["dir"], "memory_id": str(lk["other"]), "content": lk["content_en"],
                   "captured_at": _iso(lk["captured_at"])} for lk in links],
        "commitment": {"owner": commitment["owner"], "action": commitment["action"], "due_at": _iso(commitment["due_at"]),
                       "status": commitment["status"]} if commitment else None,
    }


@router.patch("/memories/{memory_id}")
async def patch_memory(memory_id: str, body: MemoryPatch, user: CurrentUser = CurrentUserDep):
    async with user_conn(user.id) as conn:
        row = await conn.fetchrow(
            """update echo.memories set content_en = coalesce($2, content_en), importance = coalesce($3, importance),
               pinned = coalesce($4, pinned) where id = $1 and deleted_at is null returning id""",
            memory_id, body.content_en, body.importance, body.pinned,
        )
    if row is None:
        raise not_found("memory not found")
    if body.content_en:
        emb = embeddings()
        (v,), tokens = await emb.embed([body.content_en])
        await costs.record("azure_embed", tokens, "tokens", user.id, memory_id)
        await pool().execute(
            "update echo.memories set embedding = $2::extensions.vector, embedding_model = $3 where id = $1 and user_id = $4",
            memory_id, vec(v), emb.model_id, user.id,
        )
    return {"ok": True}


@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: str, user: CurrentUser = CurrentUserDep):
    async with user_conn(user.id) as conn:
        n = await conn.fetchval("with d as (delete from echo.memories where id = $1 returning 1) select count(*) from d", memory_id)
    if not n:
        raise not_found("memory not found")
    return {"deleted": True}


@router.get("/conversations/{conversation_id}")
async def conversation_detail(conversation_id: str, user: CurrentUser = CurrentUserDep):
    async with user_conn(user.id) as conn:
        c = await conn.fetchrow(
            """select c.*, e.canonical_name as place from echo.conversations c left join echo.entities e on e.id = c.place_id
               where c.id = $1""",
            conversation_id,
        )
        if c is None:
            raise not_found("conversation not found")
        utts = await conn.fetch(
            """select u.id, u.text_native, u.text_en, u.language, u.start_ms, u.end_ms, u.quality_score, u.is_provisional,
                      sg.started_at as seg_started, sg.id as segment_id, sp.id as speaker_id, sp.label, sp.is_user,
                      pe.canonical_name as person
               from echo.utterances u left join echo.audio_segments sg on sg.id = u.segment_id
               left join echo.speakers sp on sp.id = u.speaker_id left join echo.entities pe on pe.id = sp.person_id
               where u.conversation_id = $1 order by sg.started_at, u.start_ms""",
            conversation_id,
        )
        segs = await conn.fetch(
            """select id, started_at, duration_ms, storage_path, audio_deleted_at from echo.audio_segments
               where conversation_id = $1 and status = 'transcript_ok' order by started_at""",
            conversation_id,
        )
        speakers = await conn.fetch(
            """select sp.id, sp.label, sp.is_user, sp.person_id, e.canonical_name from echo.speakers sp
               left join echo.entities e on e.id = sp.person_id where sp.conversation_id = $1""",
            conversation_id,
        )
        mems = await conn.fetch(
            "select id, type, content_en, importance from echo.memories where conversation_id = $1 and deleted_at is null order by importance desc",
            conversation_id,
        )
    return {
        "id": str(c["id"]), "title": c["title_en"], "summary": c["summary_en"], "status": c["status"],
        "started_at": _iso(c["started_at"]), "ended_at": _iso(c["ended_at"]), "languages": c["languages"], "place": c["place"],
        "pinned": c["pinned"], "in_transit": c["in_transit"],
        "speakers": [{"id": str(s["id"]), "label": s["canonical_name"] or s["label"], "is_user": s["is_user"],
                      "person_id": str(s["person_id"]) if s["person_id"] else None} for s in speakers],
        "utterances": [
            {"id": str(u["id"]), "text_native": u["text_native"], "text_en": u["text_en"], "language": u["language"],
             "speaker": {"id": str(u["speaker_id"]) if u["speaker_id"] else None, "label": u["person"] or u["label"], "is_user": u["is_user"]},
             "segment_id": str(u["segment_id"]) if u["segment_id"] else None, "start_ms": u["start_ms"], "end_ms": u["end_ms"],
             "spoken_at": _iso(u["seg_started"]), "provisional": u["is_provisional"]}
            for u in utts
        ],
        "segments": [{"id": str(s["id"]), "started_at": _iso(s["started_at"]), "duration_ms": s["duration_ms"],
                      "audio_url": await _clip_url(s["id"], s["storage_path"], s["audio_deleted_at"])} for s in segs],
        "memories": [{"id": str(m["id"]), "type": m["type"], "content": m["content_en"], "importance": m["importance"]} for m in mems],
    }


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, user: CurrentUser = CurrentUserDep):
    paths = await pool().fetch(
        "select storage_path, speech_path from echo.audio_segments where conversation_id = $1 and user_id = $2",
        conversation_id, user.id,
    )
    files = [p["storage_path"] for p in paths if p["storage_path"]] + [p["speech_path"] for p in paths if p["speech_path"]]
    if files:
        await storage().delete(files)
    async with pool().acquire() as conn, conn.transaction():
        await conn.execute("delete from echo.audio_segments where conversation_id = $1 and user_id = $2", conversation_id, user.id)
        n = await conn.fetchval(
            "with d as (delete from echo.conversations where id = $1 and user_id = $2 returning 1) select count(*) from d",
            conversation_id, user.id,
        )
    if not n:
        raise not_found("conversation not found")
    return {"deleted": True}


@router.post("/speakers/{speaker_id}/label")
async def label_speaker(speaker_id: str, body: SpeakerLabelIn, user: CurrentUser = CurrentUserDep):
    s = get_settings()
    sp = await pool().fetchrow(
        "select id, embedding::text as emb, conversation_id from echo.speakers where id = $1 and user_id = $2", speaker_id, user.id
    )
    if sp is None:
        raise not_found("speaker not found")
    if body.is_me:
        async with pool().acquire() as conn, conn.transaction():
            await conn.execute("update echo.speakers set is_user = false, label = 'speaker_x' where conversation_id = $1 and is_user", sp["conversation_id"])
            await conn.execute("update echo.speakers set is_user = true, label = 'you', person_id = null where id = $1", speaker_id)
            if sp["emb"]:
                await conn.execute(
                    """insert into echo.voiceprints(user_id, embedding, model) values ($1, $2::extensions.vector, 'campplus-from-label')
                       on conflict (user_id) do nothing""",
                    user.id, sp["emb"],
                )
        return {"ok": True, "label": "you"}
    if not body.name:
        raise HTTPException(422, "name or is_me required")
    async with pool().acquire() as conn, conn.transaction():
        pid = await resolve_entity(conn, user.id, "person", body.name)
        await conn.execute("update echo.speakers set person_id = $2, is_user = false where id = $1", speaker_id, pid)
        backfilled = 0
        if sp["emb"]:
            await conn.execute(
                "insert into echo.voice_profiles(user_id, person_id, embedding, model) values ($1,$2,$3::extensions.vector,'campplus')",
                user.id, pid, sp["emb"],
            )
            backfilled = await conn.fetchval(
                """with u as (update echo.speakers set person_id = $3 where user_id = $1 and id <> $2 and person_id is null
                     and not is_user and embedding is not null and 1 - (embedding <=> $4::extensions.vector) >= $5 returning 1)
                   select count(*) from u""",
                user.id, speaker_id, pid, sp["emb"], s.person_voice_threshold,
            )
        mem_ids = await conn.fetch(
            """select distinct me.memory_id from echo.memory_evidence me join echo.utterances u on u.id = me.utterance_id
               where u.speaker_id = $1""",
            speaker_id,
        )
        await conn.executemany(
            "insert into echo.memory_entities(user_id, memory_id, entity_id, role) values ($1,$2,$3,'subject') on conflict do nothing",
            [(user.id, r["memory_id"], pid) for r in mem_ids],
        )
    await refresh_people(user.id, [pid])
    return {"ok": True, "person_id": pid, "backfilled_speakers": backfilled}


@router.get("/people")
async def people(user: CurrentUser = CurrentUserDep):
    async with user_conn(user.id) as conn:
        rows = await conn.fetch(
            """select e.id, e.canonical_name, e.aliases, p.summary, p.last_interaction_at, p.interaction_count, p.open_commitments
               from echo.entities e left join echo.person_profiles p on p.entity_id = e.id
               where e.user_id = $1 and e.kind = 'person'
               order by p.last_interaction_at desc nulls last, e.updated_at desc limit 200""",
            user.id,
        )
    return {"items": [{"id": str(r["id"]), "name": r["canonical_name"], "aliases": r["aliases"], "summary": r["summary"],
                       "last_interaction_at": _iso(r["last_interaction_at"]), "interactions": r["interaction_count"] or 0,
                       "open_commitments": r["open_commitments"] or 0} for r in rows]}


@router.get("/people/{person_id}")
async def person(person_id: str, user: CurrentUser = CurrentUserDep):
    async with user_conn(user.id) as conn:
        e = await conn.fetchrow(
            """select e.*, p.summary, p.facts, p.last_interaction_at, p.interaction_count from echo.entities e
               left join echo.person_profiles p on p.entity_id = e.id where e.id = $1 and e.kind = 'person'""",
            person_id,
        )
        if e is None:
            raise not_found("person not found")
        commitments = await conn.fetch(
            """select c.memory_id, c.owner, c.action, c.due_at, c.status, m.content_en from echo.commitments c
               join echo.memories m on m.id = c.memory_id where c.counterparty_entity_id = $1 order by c.created_at desc limit 20""",
            person_id,
        )
        mems = await conn.fetch(
            """select m.id, m.type, m.content_en, m.captured_at from echo.memory_entities me join echo.memories m on m.id = me.memory_id
               where me.entity_id = $1 and m.deleted_at is null order by m.captured_at desc limit 30""",
            person_id,
        )
    return {
        "id": str(e["id"]), "name": e["canonical_name"], "aliases": e["aliases"], "summary": e["summary"],
        "last_interaction_at": _iso(e["last_interaction_at"]), "interactions": e["interaction_count"] or 0,
        "commitments": [{"memory_id": str(c["memory_id"]), "owner": c["owner"], "action": c["action"], "content": c["content_en"],
                         "due_at": _iso(c["due_at"]), "status": c["status"]} for c in commitments],
        "memories": [{"id": str(m["id"]), "type": m["type"], "content": m["content_en"], "captured_at": _iso(m["captured_at"])} for m in mems],
    }


@router.get("/commitments")
async def commitments(status: str = "open", user: CurrentUser = CurrentUserDep):
    async with user_conn(user.id) as conn:
        rows = await conn.fetch(
            """select c.memory_id, c.owner, c.action, c.due_at, c.status, m.content_en, m.captured_at, e.canonical_name as counterparty
               from echo.commitments c join echo.memories m on m.id = c.memory_id
               left join echo.entities e on e.id = c.counterparty_entity_id
               where c.user_id = $1 and c.status = $2 order by c.due_at nulls last, m.captured_at desc limit 200""",
            user.id, status,
        )
    return {"items": [{"memory_id": str(r["memory_id"]), "owner": r["owner"], "action": r["action"], "content": r["content_en"],
                       "counterparty": r["counterparty"], "due_at": _iso(r["due_at"]), "status": r["status"],
                       "captured_at": _iso(r["captured_at"])} for r in rows]}


@router.patch("/commitments/{memory_id}")
async def patch_commitment(memory_id: str, body: CommitmentPatch, user: CurrentUser = CurrentUserDep):
    async with user_conn(user.id) as conn:
        n = await conn.fetchval(
            "with u as (update echo.commitments set status = $2 where memory_id = $1 returning 1) select count(*) from u",
            memory_id, body.status,
        )
    if not n:
        raise not_found("commitment not found")
    if body.status != "open":
        await pool().execute(
            "update echo.reminders set status = 'cancelled' where commitment_id = $1 and user_id = $2 and status = 'scheduled'",
            memory_id, user.id,
        )
    return {"ok": True}


@router.get("/digests/latest")
async def latest_digest(user: CurrentUser = CurrentUserDep):
    async with user_conn(user.id) as conn:
        d = await conn.fetchrow("select * from echo.digests where user_id = $1 order by day desc limit 1", user.id)
    if d is None:
        return {"digest": None}
    return {"digest": {"id": str(d["id"]), "day": d["day"].isoformat(), "content": d["content"], "citations": d["citations"]}}


@router.get("/digests/{day}")
async def digest(day: str, user: CurrentUser = CurrentUserDep):
    async with user_conn(user.id) as conn:
        d = await conn.fetchrow("select * from echo.digests where user_id = $1 and day = $2::date", user.id, day)
    if d is None:
        raise not_found("digest not found")
    return {"digest": {"id": str(d["id"]), "day": d["day"].isoformat(), "content": d["content"], "citations": d["citations"]}}
