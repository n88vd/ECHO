"""End-to-end over real Supabase (auth, storage, Postgres, pgmq) with fake AI providers. Opt-in: ECHO_DB_TESTS=1."""

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.core import queue
from app.core.db import close_pool, init_pool, pool
from app.main import app
from app.providers import fake
from app.providers.base import SttChunk, SttResult
from app.workers.runtime import drain_once
from tests.helpers import create_test_user, delete_test_user

pytestmark = pytest.mark.skipif(os.getenv("ECHO_DB_TESTS") != "1", reason="set ECHO_DB_TESTS=1")

TRANSCRIPTS = {
    "en_promise.ogg": ("en-IN", "Rahul, I promise I will send you the project report by Friday evening."),
    "hinglish_remember.ogg": ("hi-IN", "Echo, yaad rakhna, maine Priya ko bola hai ki main Sunday ko uski party mein zaroor aaunga."),
    "hi_passport.ogg": ("hi-IN", "I kept my passport in the blue bag in the bedroom cupboard."),
    "silence.ogg": (None, ""),
}


async def _drain_all(max_rounds: int = 10) -> None:
    for _ in range(max_rounds):
        n = 0
        for q in (queue.AUDIO_QA, queue.STT_FAST, queue.UNDERSTAND, queue.PURGE):
            n += await drain_once(q, 10)
        if not n:
            return


async def test_full_pipeline(fixture_bytes):
    await init_pool()
    uid, token, _ = await create_test_user()
    h = {"Authorization": f"Bearer {token}"}
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60) as c:
            assert (await c.get("/v1/status")).status_code == 401
            import numpy as np

            from app.audio.decode import decode, to_wav
            voice = decode(fixture_bytes("en_promise.ogg"))
            enroll = await c.post("/v1/voiceprint", headers=h, files={"file": ("enroll.wav", to_wav(np.concatenate([voice] * 4)), "audio/wav")})
            assert enroll.status_code == 200, enroll.text
            dev = (await c.post("/v1/devices", headers=h, json={"model": "Pixel", "os_version": "14", "app_version": "0.1.0"})).json()
            t0 = datetime.now(UTC) - timedelta(minutes=30)
            plan = [("en_promise.ogg", t0), ("hinglish_remember.ogg", t0 + timedelta(seconds=12)),
                    ("silence.ogg", t0 + timedelta(seconds=25)), ("hi_passport.ogg", t0 + timedelta(minutes=10))]
            seg_ids = {}
            for name, started in plan:
                data = fixture_bytes(name)
                lang, text = TRANSCRIPTS[name]
                fake.FAKE_DEFAULT[:] = [SttResult(text, lang, 0.95, [SttChunk(text, 0.0, 3.0)] if text else [], "fake")]
                sid = str(uuid.uuid4())
                seg_ids[name] = sid
                meta = {"segment_id": sid, "sha256": hashlib.sha256(data).hexdigest(), "duration_ms": 5000,
                        "started_at": started.isoformat(), "source": "phone", "device_id": dev["device_id"],
                        "lat": 12.9716, "lng": 77.5946, "locality": "MG Road, Bengaluru"}
                if name == "hi_passport.ogg":
                    r = (await c.post("/v1/segments/init", headers=h, json=meta)).json()
                    async with httpx.AsyncClient(timeout=60) as raw:
                        put = await raw.put(r["upload_url"], content=data, headers={"Content-Type": "audio/ogg"})
                        assert put.status_code < 300, put.text
                    assert (await c.post(f"/v1/segments/{sid}/commit", headers=h)).json()["status"] == "received"
                else:
                    r = await c.post("/v1/segments", headers=h, data={"meta": json.dumps(meta)},
                                     files={"file": (f"{sid}.ogg", data, "audio/ogg")})
                    assert r.status_code == 200, r.text
                again = await c.post("/v1/segments", headers=h, data={"meta": json.dumps(meta)},
                                     files={"file": (f"{sid}.ogg", data, "audio/ogg")})
                assert again.json()["status"] != "pending_upload"
                await drain_once(queue.AUDIO_QA, 10)
                await drain_once(queue.STT_FAST, 10)

            statuses = {r["id"]: r["status"] for r in await pool().fetch(
                "select id::text, status from echo.audio_segments where user_id = $1", uid)}
            assert statuses[seg_ids["silence.ogg"]] == "discarded_blank"
            assert statuses[seg_ids["en_promise.ogg"]] == "transcript_ok"
            convs = await pool().fetch("select id, pinned from echo.conversations where user_id = $1 order by started_at", uid)
            assert len(convs) == 2 and convs[0]["pinned"] is True

            await pool().execute("update echo.conversations set last_activity_at = now() - interval '10 minutes' where user_id = $1", uid)
            await pool().fetchval("select echo.close_stale_conversations()")
            await _drain_all()

            mems = await pool().fetch("select type, content_en, pinned, embedding is not null as has_emb from echo.memories where user_id = $1", uid)
            types = {m["type"] for m in mems}
            assert {"commitment", "object_location"} <= types
            assert all(m["has_emb"] for m in mems)
            assert any(m["pinned"] for m in mems)
            assert await pool().fetchval("select count(*) from echo.reminders where user_id = $1", uid) >= 1

            ask = (await c.post("/v1/ask", headers=h, json={"query": "What did I promise Rahul?", "speak": True})).json()
            assert "Rahul" in ask["answer"] and ask["citations"], ask
            assert ask["citations"][0]["evidence"], ask
            assert ask["tts_url"]
            where = (await c.post("/v1/ask", headers=h, json={"query": "Where did I keep my passport?"})).json()
            assert "passport" in where["answer"].lower() and where["citations"][0]["type"] == "object_location"

            tl = (await c.get("/v1/timeline", headers=h)).json()
            assert len(tl["items"]) == 2 and tl["items"][0]["memories"]
            mid = ask["citations"][0]["id"]
            detail = (await c.get(f"/v1/memories/{mid}", headers=h)).json()
            assert detail["evidence"][0]["quote_native"] and detail["evidence"][0]["audio_url"]
            conv = (await c.get(f"/v1/conversations/{detail['conversation']['id']}", headers=h)).json()
            spk = conv["speakers"][0]["id"]
            lab = (await c.post(f"/v1/speakers/{spk}/label", headers=h, json={"name": "Rahul Sharma"})).json()
            assert lab["ok"]
            people = (await c.get("/v1/people", headers=h)).json()["items"]
            assert any(p["name"].startswith("Rahul") for p in people)
            sync = (await c.get("/v1/sync", headers=h)).json()
            assert sync["reminders"]
            commits = (await c.get("/v1/commitments", headers=h)).json()["items"]
            assert commits
            assert (await c.patch(f"/v1/commitments/{commits[0]['memory_id']}", headers=h, json={"status": "done"})).json()["ok"]
            st = (await c.patch("/v1/settings", headers=h, json={"audio_retention_days": 0, "timezone": "Asia/Kolkata"})).json()
            assert st["audio_retention_days"] == 0
            status = (await c.get("/v1/status", headers=h)).json()
            assert status["memories"] >= 2
            export = await c.get("/v1/export", headers=h)
            assert export.status_code == 200 and json.loads(export.text)["memories"]

            other_uid, other_token, _ = await create_test_user()
            try:
                forbidden = await c.get(f"/v1/memories/{mid}", headers={"Authorization": f"Bearer {other_token}"})
                assert forbidden.status_code == 404
            finally:
                await c.delete("/v1/account", headers={"Authorization": f"Bearer {other_token}"})
                await delete_test_user(other_uid)

            gone = (await c.delete("/v1/account", headers=h)).json()
            assert gone["deleted"] and gone["files"] >= 3
            assert await pool().fetchval("select count(*) from echo.memories where user_id = $1", uid) == 0
    finally:
        await pool().execute("delete from echo.profiles where user_id = $1", uid)
        await delete_test_user(uid)
        fake.FAKE_DEFAULT.clear()
        await close_pool()
