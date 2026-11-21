"""Conversation understanding: speakers -> LLM extraction -> grounding -> graph -> embeddings -> proactive hooks."""

import json
import logging
import re
from datetime import datetime, timedelta

from app.audio.speakers import agglomerative, centroid, cosine
from app.core import costs, queue
from app.core.config import get_settings
from app.core.db import parse_vec, pool, vec
from app.pipeline.common import user_tz, voiceprint
from app.pipeline.entities import resolve_entity
from app.pipeline.events import stage_event
from app.pipeline.places import haversine_m, max_speed_kmh
from app.pipeline.text_qa import redact
from app.prompts import schemas
from app.prompts.text import COMMITMENT_CHECK_SYSTEM, UNDERSTAND_SYSTEM
from app.providers import embeddings, llm

logger = logging.getLogger("echo.understand")
_WORD = re.compile(r"[\w\u0900-\u0DFF]+")
_STOP = {"you", "your", "the", "a", "an", "to", "of", "and", "is", "was", "that", "this", "in", "on", "at", "for", "with",
         "will", "would", "said", "told", "by", "it", "be", "are", "were", "has", "have", "had", "about", "from"}


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else None
    except ValueError:
        return None


def grounding_score(content_en: str, evidence_texts: list[str], people: list[str]) -> float:
    words = {w for w in _WORD.findall(content_en.lower()) if w not in _STOP and len(w) > 2}
    if not words:
        return 1.0
    ev = " ".join(evidence_texts).lower()
    ev_words = set(_WORD.findall(ev))
    hits = sum(1 for w in words if w in ev_words or any(e.startswith(w[:5]) for e in ev_words if len(w) >= 5))
    names_ok = all(p.lower().split()[0] in ev for p in people if p) if people else True
    return (hits / len(words)) * (1.0 if names_ok else 0.6)


async def _assign_speakers(conv, utts, uid) -> dict[str, dict]:
    """Returns utterance_id -> {speaker_id, label}. Persists echo.speakers rows."""
    s = get_settings()
    vp = await voiceprint(uid)
    batch_labels = [u["batch_speaker"] for u in utts]
    use_batch = any(batch_labels)
    with_emb = [(i, parse_vec(u["emb"])) for i, u in enumerate(utts) if u["emb"]]
    labels: list[int | None] = [None] * len(utts)
    if use_batch:
        names = sorted({b for b in batch_labels if b})
        for i, b in enumerate(batch_labels):
            labels[i] = names.index(b) if b else None
    elif with_emb:
        cl, _conf = agglomerative([e for _, e in with_emb], s.speaker_cluster_threshold)
        for (i, _), lab in zip(with_emb, cl, strict=True):
            labels[i] = lab
    for i in range(len(utts)):
        if labels[i] is None:
            same_seg = [j for j in range(len(utts)) if labels[j] is not None and utts[j]["segment_id"] == utts[i]["segment_id"]]
            pool_ = same_seg or [j for j in range(len(utts)) if labels[j] is not None]
            if pool_:
                labels[i] = labels[min(pool_, key=lambda j: abs(j - i))]

    groups: dict[int, list[int]] = {}
    for i, lab in enumerate(labels):
        if lab is not None:
            groups.setdefault(lab, []).append(i)
    info: dict[int, dict] = {}
    for lab, idxs in groups.items():
        embs = [parse_vec(utts[i]["emb"]) for i in idxs if utts[i]["emb"]]
        c = centroid(embs) if embs else None
        info[lab] = {"centroid": c, "you": cosine(c, vp) if (c and vp) else None, "speech": sum(utts[i]["end_ms"] - utts[i]["start_ms"] for i in idxs)}

    you_lab = None
    if vp:
        cands = [(v["you"], lab) for lab, v in info.items() if v["you"] is not None and v["you"] >= s.voiceprint_threshold]
        you_lab = max(cands)[1] if cands else None
    elif len(info) == 1:
        you_lab = next(iter(info))

    async with pool().acquire() as conn, conn.transaction():
        await conn.execute("update echo.utterances set speaker_id = null where conversation_id = $1", conv["id"])
        await conn.execute("delete from echo.speakers where conversation_id = $1", conv["id"])
        n = 1
        result: dict[str, dict] = {}
        for lab in sorted(info, key=lambda k: -info[k]["speech"]):
            v = info[lab]
            person_id, person_name, score = None, None, v["you"]
            if lab == you_lab:
                label = "you"
            else:
                n += 1
                label = f"speaker_{n}"
                if v["centroid"]:
                    row = await conn.fetchrow(
                        """select vp.person_id, e.canonical_name, 1 - (vp.embedding <=> $2::extensions.vector) as sim
                           from echo.voice_profiles vp join echo.entities e on e.id = vp.person_id
                           where vp.user_id = $1 order by vp.embedding <=> $2::extensions.vector limit 1""",
                        conv["user_id"], vec(v["centroid"]),
                    )
                    if row and row["sim"] >= s.person_voice_threshold:
                        person_id, person_name, score = row["person_id"], row["canonical_name"], float(row["sim"])
            sid = await conn.fetchval(
                """insert into echo.speakers(user_id, conversation_id, label, is_user, person_id, embedding, match_score, source)
                   values ($1,$2,$3,$4,$5,$6::extensions.vector,$7,$8) returning id""",
                conv["user_id"], conv["id"], label, lab == you_lab, person_id, vec(v["centroid"]), score,
                "batch" if use_batch else "cluster",
            )
            display = "you" if lab == you_lab else (person_name or label)
            for i in groups[lab]:
                result[str(utts[i]["id"])] = {"speaker_id": sid, "label": display}
        for uid_, r in result.items():
            await conn.execute("update echo.utterances set speaker_id = $2 where id = $1", uid_, r["speaker_id"])
    return result


async def _place_for(conn, conv, segs) -> tuple[str | None, bool]:
    fixes = sorted(
        [(s["started_at"].timestamp(), s["lat"], s["lng"]) for s in segs if s["lat"] is not None and s["lng"] is not None]
    )
    if not fixes:
        return None, False
    in_transit = max_speed_kmh(fixes) > 25
    lats, lngs = sorted(f[1] for f in fixes), sorted(f[2] for f in fixes)
    lat, lng = lats[len(lats) // 2], lngs[len(lngs) // 2]
    if in_transit:
        return None, True
    places = await conn.fetch(
        "select id, lat, lng from echo.entities where user_id = $1 and kind = 'place' and lat is not null", conv["user_id"]
    )
    best = min(places, key=lambda p: haversine_m((lat, lng), (p["lat"], p["lng"])), default=None)
    if best and haversine_m((lat, lng), (best["lat"], best["lng"])) <= 150:
        return str(best["id"]), False
    locality = next((s["locality"] for s in segs if s["locality"]), None) or f"Place near {lat:.3f}, {lng:.3f}"
    pid = await conn.fetchval(
        """insert into echo.entities(user_id, kind, canonical_name, aliases, lat, lng, attributes)
           values ($1, 'place', $2, array[$2], $3, $4, '{"auto": true}') returning id""",
        conv["user_id"], locality, lat, lng,
    )
    return str(pid), False


async def run_understand(conversation_id: str, attempt: int = 1) -> None:
    s = get_settings()
    conv = await pool().fetchrow("select * from echo.conversations where id = $1", conversation_id)
    if conv is None or conv["status"] not in ("closed", "failed"):
        return
    uid = str(conv["user_id"])

    if s.providers == "live" and conv["pinned"] and not conv["batch_requested"]:
        await pool().execute("update echo.conversations set batch_requested = true where id = $1", conversation_id)
        await queue.send(queue.STT_BATCH_SUBMIT, {"conversation_id": conversation_id, "user_id": uid})
        return
    if conv["batch_requested"]:
        state = await pool().fetchval(
            "select state from echo.stt_jobs where conversation_id = $1 order by created_at desc limit 1", conversation_id
        )
        if state not in ("completed", "failed"):
            return

    async with stage_event("understand", "conversation", conversation_id, uid, attempt) as meta:
        utts = await pool().fetch(
            """select u.id, u.segment_id, u.start_ms, u.end_ms, u.text_native, u.language, u.batch_speaker,
                      u.speaker_embedding::text as emb, coalesce(sg.started_at, c.started_at) as seg_started
               from echo.utterances u join echo.conversations c on c.id = u.conversation_id
               left join echo.audio_segments sg on sg.id = u.segment_id
               where u.conversation_id = $1
               order by coalesce(sg.started_at, c.started_at) + u.start_ms * interval '1 millisecond'""",
            conversation_id,
        )
        if not utts:
            await pool().execute("update echo.conversations set status = 'understood' where id = $1", conversation_id)
            meta["_status"] = "skipped"
            return
        speakers = await _assign_speakers(conv, utts, uid)
        tz = await user_tz(uid)
        profile = await pool().fetchrow("select display_name from echo.profiles where user_id = $1", conv["user_id"])
        known_people = await pool().fetch(
            "select canonical_name from echo.entities where user_id = $1 and kind = 'person' order by updated_at desc limit 40",
            conv["user_id"],
        )
        id_map = {f"u{i + 1}": str(u["id"]) for i, u in enumerate(utts)}
        rev = {v: k for k, v in id_map.items()}
        payload = {
            "conversation_start": conv["started_at"].astimezone(tz).isoformat(),
            "timezone": str(tz),
            "user_name": profile["display_name"] if profile else None,
            "languages": conv["languages"],
            "known_people": [r["canonical_name"] for r in known_people],
            "utterances": [
                {
                    "id": rev[str(u["id"])],
                    "speaker": speakers.get(str(u["id"]), {}).get("label", "unknown"),
                    "time": (u["seg_started"] + timedelta(milliseconds=u["start_ms"])).astimezone(tz).strftime("%H:%M:%S"),
                    "text": u["text_native"],
                }
                for u in utts
            ],
        }
        result, tokens = await llm().json(UNDERSTAND_SYSTEM, json.dumps(payload, ensure_ascii=False), schemas.UNDERSTAND, "understand", tier="extract", max_tokens=6000)
        await costs.record("azure_llm", tokens, "tokens", uid, conversation_id)

        def real_id(x: str) -> str | None:
            return id_map.get(x) or (x if x in rev else None)

        text_en = {real_id(t["id"]): t["text_en"] for t in result.get("utterances_en", []) if real_id(t["id"])}
        native = {str(u["id"]): u["text_native"] for u in utts}
        evidence_text = {k: f"{native[k]} {text_en.get(k, '')}" for k in native}

        kept = []
        for m in result.get("memories", []):
            ev = [real_id(e) for e in m.get("evidence_utterance_ids", [])]
            ev = [e for e in ev if e]
            if not ev or not m.get("content_en"):
                continue
            g = grounding_score(m["content_en"], [evidence_text[e] for e in ev], m.get("people") or [])
            conf = float(m.get("confidence") or 0.5)
            if g < 0.2:
                continue
            if g < 0.45:
                conf *= 0.5
            m["content_en"], r1 = redact(m["content_en"])
            m["content_native"], r2 = redact(m.get("content_native") or "")
            if r1 or r2:
                m["sensitivity"] = sorted(set((m.get("sensitivity") or []) + ["credential"]))
            m["_ev"], m["_conf"] = ev, max(0.0, min(1.0, conf))
            kept.append(m)
        meta.update(proposed=len(result.get("memories", [])), kept=len(kept), tokens=tokens)

        remember = bool(result.get("remember_this")) or conv["pinned"]
        segs = await pool().fetch(
            "select started_at, lat, lng, locality from echo.audio_segments where conversation_id = $1 and status = 'transcript_ok'",
            conversation_id,
        )
        new_ids: list[tuple[str, str]] = []
        touched_people: set[str] = set()
        async with pool().acquire() as conn, conn.transaction():
            for k, t in text_en.items():
                await conn.execute("update echo.utterances set text_en = $2, is_provisional = false where id = $1", k, redact(t)[0])
            await conn.execute("delete from echo.memories where conversation_id = $1", conversation_id)
            place_id, in_transit = await _place_for(conn, conv, segs)
            for m in kept:
                importance = float(m.get("importance") or 0.5)
                if remember:
                    importance = max(importance, 0.9)
                ts = _parse_ts(m.get("resolved_start"))
                quote = " / ".join(native[e] for e in m["_ev"])[:500]
                mid = await conn.fetchval(
                    """insert into echo.memories(user_id, conversation_id, type, content_en, content_native, importance,
                       confidence, sensitivity, pinned, place_id, time_start, time_end, captured_at, evidence_quote)
                       values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14) returning id""",
                    conv["user_id"], conversation_id, m["type"], m["content_en"], m["content_native"] or None,
                    max(0.0, min(1.0, importance)), m["_conf"], m.get("sensitivity") or [], remember, place_id, ts,
                    _parse_ts(m.get("resolved_end")), conv["started_at"], quote,
                )
                mid = str(mid)
                new_ids.append((mid, m["content_en"]))
                await conn.executemany(
                    "insert into echo.memory_evidence(user_id, memory_id, utterance_id) values ($1,$2,$3) on conflict do nothing",
                    [(conv["user_id"], mid, e) for e in m["_ev"]],
                )
                roles: list[tuple[str, str]] = []
                for p in m.get("people") or []:
                    eid = await resolve_entity(conn, conv["user_id"], "person", p)
                    if eid:
                        roles.append((eid, "mention"))
                        touched_people.add(eid)
                for p in m.get("places") or []:
                    eid = await resolve_entity(conn, conv["user_id"], "place", p)
                    if eid:
                        roles.append((eid, "place"))
                obj_ids = []
                for o in m.get("objects") or []:
                    eid = await resolve_entity(conn, conv["user_id"], "object", o)
                    if eid:
                        roles.append((eid, "object"))
                        obj_ids.append(eid)
                for t in m.get("topics") or []:
                    eid = await resolve_entity(conn, conv["user_id"], "topic", t)
                    if eid:
                        roles.append((eid, "mention"))
                c = m.get("commitment")
                cp_id = await resolve_entity(conn, conv["user_id"], "person", c["counterparty"]) if c and c.get("counterparty") else None
                if cp_id:
                    roles.append((cp_id, "counterparty"))
                    touched_people.add(cp_id)
                await conn.executemany(
                    "insert into echo.memory_entities(user_id, memory_id, entity_id, role) values ($1,$2,$3,$4) on conflict do nothing",
                    [(conv["user_id"], mid, e, r) for e, r in dict.fromkeys(roles)],
                )
                if m["type"] == "commitment" and c:
                    due = _parse_ts(c.get("due")) or ts
                    await conn.execute(
                        """insert into echo.commitments(memory_id, user_id, owner, counterparty_entity_id, action, due_at)
                           values ($1,$2,$3,$4,$5,$6)""",
                        mid, conv["user_id"], c.get("owner") or "user", cp_id, c.get("action") or m["content_en"], due,
                    )
                    if (c.get("owner") or "user") == "user":
                        now = datetime.now(due.tzinfo) if due else datetime.now().astimezone()
                        fire = max(due - timedelta(hours=2), now + timedelta(minutes=5)) if due and due > now else now + timedelta(hours=24)
                        await conn.execute(
                            """insert into echo.reminders(user_id, commitment_id, kind, title, body, fire_at)
                               values ($1,$2,'commitment',$3,$4,$5)""",
                            conv["user_id"], mid, "Promise reminder", m["content_en"], fire,
                        )
                if m["type"] == "object_location":
                    for oid in obj_ids:
                        old = await conn.fetch(
                            """select me.memory_id from echo.memory_entities me join echo.memories mm on mm.id = me.memory_id
                               where me.entity_id = $1 and me.role = 'object' and mm.type = 'object_location'
                                 and mm.superseded_by is null and mm.id <> $2 and mm.captured_at <= $3""",
                            oid, mid, conv["started_at"],
                        )
                        for o in old:
                            await conn.execute("update echo.memories set superseded_by = $2 where id = $1", o["memory_id"], mid)
                            await conn.execute(
                                """insert into echo.memory_links(user_id, src_memory_id, dst_memory_id, kind, score)
                                   values ($1,$2,$3,'supersedes',1) on conflict do nothing""",
                                conv["user_id"], mid, o["memory_id"],
                            )
            await conn.execute(
                """update echo.conversations set title_en=$2, summary_en=$3, place_id=$4, in_transit=$5, pinned=$6,
                   speaker_count=(select count(*) from echo.speakers where conversation_id=$1), status='understood'
                   where id=$1""",
                conversation_id, (result.get("title_en") or "")[:120] or None, result.get("summary_en") or None,
                place_id, in_transit, remember,
            )

        await embed_conversation(conversation_id, uid, new_ids, result)
        if touched_people:
            await refresh_people(uid, list(touched_people))
            await check_commitments(uid, conversation_id, list(touched_people), text_en)
        retention = await pool().fetchval("select audio_retention_days from echo.user_settings where user_id = $1", conv["user_id"])
        if retention == 0:
            await queue.send(queue.PURGE, {"conversation_id": conversation_id, "user_id": uid})


async def embed_conversation(conversation_id: str, uid: str, new_ids: list[tuple[str, str]], result: dict) -> None:
    emb = embeddings()
    texts = [t for _, t in new_ids]
    summary = f"{result.get('title_en') or ''}. {result.get('summary_en') or ''}".strip(". ")
    if summary:
        texts.append(summary)
    if not texts:
        return
    vectors, tokens = await emb.embed(texts)
    await costs.record("azure_embed", tokens, "tokens", uid, conversation_id)
    async with pool().acquire() as conn, conn.transaction():
        for (mid, _), v in zip(new_ids, vectors, strict=False):
            await conn.execute(
                "update echo.memories set embedding = $2::extensions.vector, embedding_model = $3 where id = $1",
                mid, vec(v), emb.model_id,
            )
            rows = await conn.fetch(
                """select id, 1 - (embedding <=> $2::extensions.vector) as sim from echo.memories
                   where user_id = $3 and id <> $1 and embedding is not null and embedding_model = $4 and deleted_at is null
                   order by embedding <=> $2::extensions.vector limit 3""",
                mid, vec(v), uid, emb.model_id,
            )
            for r in rows:
                if r["sim"] >= 0.85:
                    await conn.execute(
                        """insert into echo.memory_links(user_id, src_memory_id, dst_memory_id, kind, score)
                           values ($1,$2,$3,'same_topic',$4) on conflict do nothing""",
                        uid, mid, r["id"], float(r["sim"]),
                    )
        if summary:
            await conn.execute(
                "update echo.conversations set summary_embedding = $2::extensions.vector, embedding_model = $3 where id = $1",
                conversation_id, vec(vectors[-1]), emb.model_id,
            )


async def refresh_people(uid: str, person_ids: list[str]) -> None:
    await pool().execute(
        """insert into echo.person_profiles(entity_id, user_id, summary, facts, last_interaction_at, interaction_count, open_commitments, refreshed_at)
           select e.id, e.user_id,
                  (select string_agg(content_en, ' ' order by captured_at desc) from (
                      select m.content_en, m.captured_at from echo.memory_entities me join echo.memories m on m.id = me.memory_id
                      where me.entity_id = e.id and m.deleted_at is null and m.type in ('person_info', 'fact', 'event')
                      order by m.captured_at desc limit 3) t),
                  coalesce((select jsonb_agg(jsonb_build_object('memory_id', id, 'content', content_en, 'at', captured_at)) from (
                      select m.id, m.content_en, m.captured_at from echo.memory_entities me join echo.memories m on m.id = me.memory_id
                      where me.entity_id = e.id and m.deleted_at is null order by m.captured_at desc limit 10) f), '[]'::jsonb),
                  (select max(m.captured_at) from echo.memory_entities me join echo.memories m on m.id = me.memory_id where me.entity_id = e.id),
                  (select count(distinct m.conversation_id) from echo.memory_entities me join echo.memories m on m.id = me.memory_id where me.entity_id = e.id),
                  (select count(*) from echo.commitments c where c.counterparty_entity_id = e.id and c.status = 'open'),
                  now()
           from echo.entities e where e.user_id = $1 and e.id = any($2::uuid[]) and e.kind = 'person'
           on conflict (entity_id) do update set summary = excluded.summary, facts = excluded.facts,
             last_interaction_at = excluded.last_interaction_at, interaction_count = excluded.interaction_count,
             open_commitments = excluded.open_commitments, refreshed_at = now()""",
        uid, person_ids,
    )


async def check_commitments(uid: str, conversation_id: str, person_ids: list[str], text_en: dict[str, str]) -> None:
    open_c = await pool().fetch(
        """select c.memory_id, c.action, c.owner, m.conversation_id from echo.commitments c join echo.memories m on m.id = c.memory_id
           where c.user_id = $1 and c.status = 'open' and c.counterparty_entity_id = any($2::uuid[]) and m.conversation_id <> $3
           order by c.created_at desc limit 20""",
        uid, person_ids, conversation_id,
    )
    if not open_c or not text_en:
        return
    payload = {
        "open_commitments": [{"commitment_id": str(c["memory_id"]), "owner": c["owner"], "action": c["action"]} for c in open_c],
        "conversation": [{"id": k, "text": v} for k, v in text_en.items()],
    }
    res, tokens = await llm().json(COMMITMENT_CHECK_SYSTEM, json.dumps(payload, ensure_ascii=False), schemas.COMMITMENT_CHECK, "commitment_check", tier="fast", max_tokens=800)
    await costs.record("azure_llm", tokens, "tokens", uid, conversation_id)
    valid = {str(c["memory_id"]) for c in open_c}
    for r in res.get("resolved", []):
        if r.get("commitment_id") in valid and r.get("evidence_utterance_id") in text_en:
            await pool().execute("update echo.commitments set status = 'done' where memory_id = $1", r["commitment_id"])
            await pool().execute(
                "update echo.reminders set status = 'cancelled' where commitment_id = $1 and status = 'scheduled'", r["commitment_id"]
            )
