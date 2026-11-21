import math
from collections import defaultdict
from datetime import UTC, datetime

DECAY_DAYS = {"object_location": 30, "commitment": 21, "event": 14, "question": 14, "decision": 120, "fact": 180,
              "person_info": 365, "learning": 365, "idea": 180, "digest": 30, "utterance": 7}


def rrf(rankings: dict[str, list[str]], k: int = 60, weights: dict[str, float] | None = None) -> dict[str, float]:
    scores: dict[str, float] = defaultdict(float)
    for name, ids in rankings.items():
        w = (weights or {}).get(name, 1.0)
        for rank, cid in enumerate(ids):
            scores[cid] += w / (k + rank + 1)
    return dict(scores)


def recency(captured_at: datetime, mtype: str, now: datetime | None = None) -> float:
    now = now or datetime.now(UTC)
    days = max(0.0, (now - captured_at).total_seconds() / 86400)
    return math.exp(-days / DECAY_DAYS.get(mtype, 90))


def rescore(base: float, importance: float, rec: float, quality: float, superseded: bool, wants_latest: bool,
            pinned: bool, type_match: bool, entity_match: bool) -> float:
    s = base * 60
    s += 0.25 * importance + (0.35 if wants_latest else 0.15) * rec + 0.1 * quality
    s += 0.2 if pinned else 0.0
    s += 0.25 if type_match else 0.0
    s += 0.3 if entity_match else 0.0
    if superseded:
        s -= 0.6 if wants_latest else 0.2
    return s
