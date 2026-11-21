from datetime import date

from app.core.config import get_settings
from app.core.db import pool


def estimate_inr(provider: str, units: float, unit_kind: str) -> float:
    s = get_settings()
    if provider == "sarvam_stt":
        return units / 3600 * s.sarvam_stt_inr_per_hour
    if provider == "sarvam_stt_batch":
        return units / 3600 * s.sarvam_stt_batch_inr_per_hour
    if provider == "sarvam_tts":
        return units / 10_000 * s.sarvam_tts_inr_per_10k_chars
    if provider == "azure_llm":
        return units / 1000 * s.azure_llm_inr_per_1k_tokens
    if provider == "azure_embed":
        return units / 1000 * s.azure_embed_inr_per_1k_tokens
    return 0.0


async def record(provider: str, units: float, unit_kind: str, user_id: str | None, subject_id: str | None = None) -> None:
    if units <= 0:
        return
    cost = estimate_inr(provider, units, unit_kind)
    async with pool().acquire() as conn, conn.transaction():
        await conn.execute(
            """insert into echo.cost_ledger(user_id, provider, units, unit_kind, est_cost_inr, subject_id)
               values ($1, $2, $3, $4, $5, $6)""",
            user_id, provider, units, unit_kind, cost, subject_id,
        )
        if user_id:
            await conn.execute(
                """insert into echo.usage_daily(user_id, day, est_cost_inr) values ($1, current_date, $2)
                   on conflict (user_id, day) do update set est_cost_inr = usage_daily.est_cost_inr + excluded.est_cost_inr""",
                user_id, cost,
            )


async def sarvam_spent_today() -> float:
    return float(
        await pool().fetchval(
            """select coalesce(sum(est_cost_inr), 0) from echo.cost_ledger
               where provider like 'sarvam%' and created_at >= date_trunc('day', now() at time zone 'Asia/Kolkata') at time zone 'Asia/Kolkata'"""
        )
    )


async def sarvam_budget_ok(extra_inr: float = 0.0) -> bool:
    return (await sarvam_spent_today()) + extra_inr <= get_settings().sarvam_daily_budget_inr


async def add_speech_seconds(user_id: str, seconds: int) -> int:
    return await pool().fetchval(
        """insert into echo.usage_daily(user_id, day, speech_seconds) values ($1, $2, $3)
           on conflict (user_id, day) do update set speech_seconds = usage_daily.speech_seconds + excluded.speech_seconds
           returning speech_seconds""",
        user_id, date.today(), seconds,
    )


async def speech_cap_ok(user_id: str, seconds: int) -> bool:
    row = await pool().fetchrow(
        """select coalesce(u.speech_seconds, 0) as used, s.speech_cap_min_per_day as cap
           from echo.user_settings s left join echo.usage_daily u on u.user_id = s.user_id and u.day = current_date
           where s.user_id = $1""",
        user_id,
    )
    return row is None or row["used"] + seconds <= row["cap"] * 60


async def ask_cap_ok(user_id: str) -> bool:
    row = await pool().fetchrow(
        """select coalesce(u.asks, 0) as used, s.ask_cap_per_day as cap
           from echo.user_settings s left join echo.usage_daily u on u.user_id = s.user_id and u.day = current_date
           where s.user_id = $1""",
        user_id,
    )
    return row is None or row["used"] < row["cap"]


async def add_ask(user_id: str) -> None:
    await pool().execute(
        """insert into echo.usage_daily(user_id, day, asks) values ($1, current_date, 1)
           on conflict (user_id, day) do update set asks = usage_daily.asks + 1""",
        user_id,
    )
