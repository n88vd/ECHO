import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np

from app.audio.decode import TARGET_SR, to_wav
from app.core.db import parse_vec, pool


class Retry(Exception):
    """Raise to re-schedule the message after `delay_s` without counting as a failure."""

    def __init__(self, delay_s: int, reason: str):
        super().__init__(reason)
        self.delay_s = delay_s


def segment_path(user_id: str, started_at: datetime, segment_id: str, ext: str = "ogg") -> str:
    return f"{user_id}/{started_at:%Y/%m/%d}/{segment_id}.{ext}"


async def keyterms(user_id: str, limit: int = 50) -> list[str]:
    rows = await pool().fetch(
        """select canonical_name from echo.entities
           where user_id = $1 and kind in ('person', 'place', 'organization') and length(canonical_name) between 2 and 64
           order by updated_at desc limit $2""",
        user_id, limit,
    )
    out: list[str] = []
    for r in rows:
        for part in re.split(r"[,;]", r["canonical_name"]):
            term = " ".join(part.split())[:64]
            if len(term) >= 2 and term.lower() not in {t.lower() for t in out}:
                out.append(term)
    return out[:limit]


async def language_prior(user_id: str) -> str | None:
    return await pool().fetchval(
        """select language from echo.utterances
           where user_id = $1 and language is not null and created_at > now() - interval '30 days'
           group by language order by count(*) desc limit 1""",
        user_id,
    )


async def voiceprint(user_id: str) -> list[float] | None:
    return parse_vec(await pool().fetchval("select embedding::text from echo.voiceprints where user_id = $1", user_id))


async def user_tz(user_id: str) -> ZoneInfo:
    tz = await pool().fetchval("select timezone from echo.profiles where user_id = $1", user_id)
    try:
        return ZoneInfo(tz or "Asia/Kolkata")
    except Exception:
        return ZoneInfo("Asia/Kolkata")


def compact_speech(samples: np.ndarray, regions: list[tuple[int, int]], pad_s: float = 0.25) -> tuple[bytes, list[list[int]]]:
    """Concatenate speech regions (with padding) to save STT seconds.

    Returns wav bytes and a map of [compact_start_ms, orig_start_ms, length_ms]."""
    pad = int(pad_s * TARGET_SR)
    merged: list[list[int]] = []
    for s, e in regions:
        s, e = max(0, s - pad), min(len(samples), e + pad)
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    parts, mapping, cursor = [], [], 0
    for s, e in merged:
        parts.append(samples[s:e])
        mapping.append([int(cursor / TARGET_SR * 1000), int(s / TARGET_SR * 1000), int((e - s) / TARGET_SR * 1000)])
        cursor += e - s
    return to_wav(np.concatenate(parts) if parts else samples[:0]), mapping


def map_ms(compact_ms: float, mapping: list[list[int]] | None) -> int:
    if not mapping:
        return int(compact_ms)
    for c_start, o_start, length in mapping:
        if compact_ms < c_start + length:
            return int(o_start + max(0, compact_ms - c_start))
    c_start, o_start, length = mapping[-1]
    return int(o_start + length)


def next_ist_midnight_delay(now: datetime | None = None) -> int:
    ist = ZoneInfo("Asia/Kolkata")
    now = now or datetime.now(ist)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
    return int(min((tomorrow - now).total_seconds(), 6 * 3600))
