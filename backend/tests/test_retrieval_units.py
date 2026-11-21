from datetime import UTC, datetime, timedelta

from app.retrieval.ask import Candidate, verify_citations
from app.retrieval.fusion import recency, rescore, rrf


def test_rrf_prefers_consensus():
    s = rrf({"a": ["x", "y", "z"], "b": ["y", "x"], "c": ["y"]})
    assert max(s, key=s.get) == "y"


def test_recency_and_supersession():
    now = datetime.now(UTC)
    assert recency(now, "object_location") > recency(now - timedelta(days=60), "object_location")
    fresh = rescore(0.03, 0.8, 1.0, 0.9, False, True, False, True, False)
    stale = rescore(0.03, 0.8, 0.5, 0.9, True, True, False, True, False)
    assert fresh > stale


def test_verify_citations_strips_unknown():
    c = Candidate(id="11111111-2222-3333-4444-555555555555", kind="m", content="x", native=None,
                  captured_at=datetime.now(UTC), mtype="fact")
    text, used = verify_citations(
        "You kept it in the bag [m:11111111-2222-3333-4444-555555555555] and [m:99999999-0000-0000-0000-000000000000].",
        {c.id: c},
    )
    assert "[m:11111111-2222-3333-4444-555555555555]" in text and "9999" not in text and used == [c]
