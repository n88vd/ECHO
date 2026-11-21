import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

import asyncpg

from app.core.config import get_settings

_pool: asyncpg.Pool | None = None


def _dumps(v) -> str:
    return json.dumps(v, default=str)


async def _setup_conn(conn: asyncpg.Connection) -> None:
    await conn.execute(
        "set search_path = echo, extensions, public; set hnsw.ef_search = 100; set hnsw.iterative_scan = relaxed_order"
    )


async def _init_conn(conn: asyncpg.Connection) -> None:
    for t in ("json", "jsonb"):
        await conn.set_type_codec(t, encoder=_dumps, decoder=json.loads, schema="pg_catalog")


async def init_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        s = get_settings()
        _pool = await asyncpg.create_pool(
            s.echo_database_url,
            min_size=s.db_pool_min,
            max_size=s.db_pool_max,
            init=_init_conn,
            setup=_setup_conn,
            statement_cache_size=get_settings().db_statement_cache,
            command_timeout=60,
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialised")
    return _pool


@asynccontextmanager
async def user_conn(user_id: str) -> AsyncIterator[asyncpg.Connection]:
    """Connection running as the `authenticated` role with RLS scoped to user_id (defence in depth)."""
    async with pool().acquire() as conn, conn.transaction():
        await conn.execute(
            "select set_config('request.jwt.claims', $1, true)",
            json.dumps({"sub": str(user_id), "role": "authenticated"}),
        )
        await conn.execute("set local role authenticated")
        yield conn


def vec(values: Sequence[float] | None) -> str | None:
    if values is None:
        return None
    return "[" + ",".join(f"{float(v):.6f}" for v in values) + "]"


def parse_vec(text: str | None) -> list[float] | None:
    if text is None:
        return None
    return [float(x) for x in text.strip("[]").split(",") if x]
