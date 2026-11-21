"""A pinned conversation whose batch request was lost must not wait forever (no network, no DB)."""

import pytest

from app.core import queue
from app.pipeline import understand

CID = "b901e450-2bfe-45f5-bb79-c700ce1ae430"
UID = "9d9cc2cc-b764-4d15-bfb2-d286a5cd9ecb"


class FakePool:
    def __init__(self, job_state):
        self.job_state = job_state

    async def fetchrow(self, sql, *args):
        return {"id": CID, "user_id": UID, "status": "closed", "pinned": True, "batch_requested": True}

    async def fetchval(self, sql, *args):
        assert "stt_jobs" in sql
        return self.job_state


@pytest.fixture
def sent(monkeypatch):
    calls = []

    async def send(q, body, delay_s=0, conn=None):
        calls.append((q, body))
        return 1

    monkeypatch.setattr(queue, "send", send)
    return calls


def _setup(monkeypatch, job_state, pending):
    monkeypatch.setattr(understand, "pool", lambda: FakePool(job_state))

    async def has_pending(q, key, value):
        assert (q, key, value) == (queue.STT_BATCH_SUBMIT, "conversation_id", CID)
        return pending

    monkeypatch.setattr(queue, "has_pending", has_pending)


async def test_lost_batch_request_is_resubmitted(monkeypatch, sent):
    _setup(monkeypatch, job_state=None, pending=False)
    await understand.run_understand(CID)
    assert sent == [(queue.STT_BATCH_SUBMIT, {"conversation_id": CID, "user_id": UID})]


async def test_queued_batch_request_is_not_duplicated(monkeypatch, sent):
    _setup(monkeypatch, job_state=None, pending=True)
    await understand.run_understand(CID)
    assert sent == []


async def test_running_batch_job_is_waited_for(monkeypatch, sent):
    _setup(monkeypatch, job_state="running", pending=False)
    await understand.run_understand(CID)
    assert sent == []
