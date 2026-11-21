"""Audio retention: delete raw audio per the user's setting (pinned audio kept >= pinned_audio_min_days)."""

from app.core.db import pool
from app.core.storage import storage


async def purge_conversation_audio(conversation_id: str) -> int:
    rows = await pool().fetch(
        """select s.id, s.storage_path, s.speech_path from echo.audio_segments s
           join echo.user_settings us on us.user_id = s.user_id
           where s.conversation_id = $1 and s.audio_deleted_at is null and s.storage_path is not null
             and (not s.pinned or s.started_at < now() - make_interval(days => us.pinned_audio_min_days))""",
        conversation_id,
    )
    return await _delete(rows)


async def purge_expired(limit: int = 500) -> int:
    rows = await pool().fetch(
        """select s.id, s.storage_path, s.speech_path from echo.audio_segments s
           join echo.user_settings us on us.user_id = s.user_id
           left join echo.conversations c on c.id = s.conversation_id
           where s.audio_deleted_at is null and s.storage_path is not null and us.audio_retention_days is not null
             and (c.status is null or c.status = 'understood' or s.status like 'discarded%')
             and s.started_at < now() - make_interval(days => us.audio_retention_days)
             and (not s.pinned or s.started_at < now() - make_interval(days => greatest(us.audio_retention_days, us.pinned_audio_min_days)))
           limit $1""",
        limit,
    )
    return await _delete(rows)


async def _delete(rows) -> int:
    if not rows:
        return 0
    paths = [r["storage_path"] for r in rows] + [r["speech_path"] for r in rows if r["speech_path"]]
    await storage().delete(paths)
    await pool().execute(
        "update echo.audio_segments set audio_deleted_at = now(), speech_path = null where id = any($1::uuid[])",
        [r["id"] for r in rows],
    )
    return len(rows)
