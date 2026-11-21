import asyncpg

KIND_THRESHOLD = {"person": 0.5, "place": 0.55, "object": 0.6, "organization": 0.55, "topic": 0.7}


async def resolve_entity(conn: asyncpg.Connection, user_id, kind: str, name: str) -> str | None:
    name = " ".join((name or "").split()).strip(" .,'\"")
    if len(name) < 2 or name.lower() in {"you", "me", "i", "user", "unknown"}:
        return None
    row = await conn.fetchrow(
        """select id from echo.entities where user_id = $1 and kind = $2
             and (lower(canonical_name) = lower($3) or exists (select 1 from unnest(aliases) a where lower(a) = lower($3)))
           limit 1""",
        user_id, kind, name,
    )
    if row:
        await conn.execute("update echo.entities set updated_at = now() where id = $1", row["id"])
        return str(row["id"])
    cands = await conn.fetch(
        """select id, canonical_name, similarity(lower(canonical_name), lower($3)) as sim from echo.entities
           where user_id = $1 and kind = $2 order by sim desc limit 5""",
        user_id, kind, name,
    )
    match = None
    for c in cands:
        a, b = c["canonical_name"].lower().split(), name.lower().split()
        prefix = kind == "person" and (a[0] == b[0]) and (len(a) == 1 or len(b) == 1)
        if c["sim"] >= KIND_THRESHOLD.get(kind, 0.6) or prefix:
            match = c
            break
    if match:
        longer = name if len(name) > len(match["canonical_name"]) and kind == "person" else match["canonical_name"]
        await conn.execute(
            """update echo.entities set canonical_name = $2,
               aliases = (select array(select distinct unnest(aliases || array[$3, $4]::text[]))), updated_at = now()
               where id = $1""",
            match["id"], longer, name, match["canonical_name"],
        )
        return str(match["id"])
    return str(
        await conn.fetchval(
            "insert into echo.entities(user_id, kind, canonical_name, aliases) values ($1, $2, $3, array[$3]) returning id",
            user_id, kind, name,
        )
    )
