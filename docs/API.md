# ECHO API reference

Base URL (production): `https://echo.nmrlabs.space`
Local: `http://localhost:8000`. Interactive OpenAPI docs: `/docs`. Schema: `/openapi.json`.

## Conventions

- **Auth.** Every `/v1/*` endpoint except `/v1/auth/*` needs `Authorization: Bearer <access_token>`. The token is a Supabase JWT from `/v1/auth/google`, `/v1/auth/refresh` or `/v1/auth/password`. The server takes `user_id` from the verified token only.
- **IDs** are UUIDs (UUIDv7 for client-made segment IDs). **Times** are ISO 8601 with a time zone.
- **Errors** use FastAPI's shape: `{"detail": "..."}`. Common codes: `401` bad or missing token, `404` not found, `409` conflict, `413` too large, `422` validation, `429` daily limit, `502`/`503` upstream provider error.
- Every response has an `x-request-id` header. You can send your own `x-request-id`.

---

## Health

| Method | Path | Description |
|---|---|---|
| `GET` | `/healthz` | Process is alive. |
| `GET` | `/readyz` | API can reach the database. Also returns the queue depths. |

---

## Auth — `/v1/auth`

### `POST /v1/auth/google`
Exchanges a Google ID token (from Android Credential Manager) for a Supabase session.

```json
{ "id_token": "eyJhbGciOi...", "nonce": "optional-raw-nonce" }
```

**Response**
```json
{
  "access_token": "eyJ...", "refresh_token": "v1.abc...", "expires_at": 1795000000, "expires_in": 3600,
  "user": { "id": "uuid", "email": "you@example.com", "name": "Your Name" }
}
```

### `POST /v1/auth/refresh`
`{ "refresh_token": "..." }` → same response as above.

### `POST /v1/auth/password`
`{ "email": "...", "password": "..." }` → same response. Enabled only when `ALLOW_PASSWORD_LOGIN=true` (for demo and review accounts). Otherwise it returns `404`.

---

## Ingest

### `POST /v1/devices`
Registers or updates the device.
```json
{ "device_id": "uuid|null", "model": "HONOR X9b", "os_version": "15", "app_version": "0.1.0" }
```
→ `{ "device_id": "uuid" }`

### Segment metadata (`SegmentMeta`)

| Field | Type | Notes |
|---|---|---|
| `segment_id` | uuid | Client-generated. This is the idempotency key. |
| `sha256` | hex string | 64 lowercase hex characters, for the audio bytes. |
| `duration_ms` | int | 1 to 60000. |
| `started_at` | datetime | Device wall clock. |
| `source` | `phone` \| `bt_sco` \| `bt_le` \| `wired` | Default `phone`. |
| `sample_rate` | int | Default 16000. |
| `speech_ratio` | float? | From the on-device VAD. |
| `session_hint` | uuid? | Conversation window from the device. |
| `pinned` | bool | `true` for "Remember this". |
| `device_id` | uuid? | |
| `lat`, `lng`, `accuracy_m`, `locality` | ? | Only when location is on. `locality` is geocoded on the device. |
| `content_type` | `audio/ogg` \| `audio/wav` | Default `audio/ogg` (Opus). |

### `POST /v1/segments` — single-call upload
Multipart form: `meta` (`SegmentMeta` as JSON) and `file` (audio).
The server checks the size and the SHA-256, then stores the audio and queues it.
→ `{ "segment_id": "uuid", "status": "received" }`. If you send the same segment again, you get its current status and nothing is duplicated.

### `POST /v1/segments/init` + `POST /v1/segments/{id}/commit` — two-step upload
1. `init` with a `SegmentMeta` JSON body → `{ "segment_id", "status": "pending_upload", "path", "upload_url" }`.
2. `PUT` the audio bytes to `upload_url` (a signed Supabase Storage URL).
3. `commit` → `{ "segment_id", "status": "received" }`. Returns `409` if the object has not been uploaded yet.

### `POST /v1/remember`
Pins the audio around a moment ("Remember this").
```json
{ "at": "2026-11-22T01:12:00+05:30", "before_s": 30, "after_s": 60 }
```
→ `{ "pinned_segments": 3, "window": { "from": "...", "to": "..." } }`

---

## Status and sync

### `GET /v1/status`
Data for the Home screen.
```json
{
  "speech_minutes_today": 59.3, "asks_today": 4, "segments_pending": 0, "conversations_processing": 1,
  "last_upload_at": "...", "memories": 128, "open_commitments": 2, "people": 9,
  "voice_enrolled": true, "server_time": "..."
}
```

### `GET /v1/sync?since=<datetime>&device_id=<uuid>`
Delta feed that replaces push notifications. The device schedules the reminders locally.
```json
{
  "cursor": "...", "server_time": "...",
  "reminders": [{ "id": "uuid", "kind": "commitment", "title": "...", "body": "...", "fire_at": "...", "status": "scheduled", "commitment_id": "uuid" }],
  "latest_digest": { "id": "uuid", "day": "2026-11-21" }
}
```

### `POST /v1/reminders/{reminder_id}/delivered`
Marks a reminder as shown on the device. → `{ "ok": true }`

---

## Ask ECHO

### `POST /v1/ask`
```json
{ "query": "When is my report for Rahul due?", "language": "en-IN", "speak": true }
```
- `query`: 1 to 1000 characters, in any supported language.
- `language`: optional answer language. The default comes from your profile or the question.
- `speak`: if `true`, the response has a `tts_url` (signed MP3, valid for 1 h).

**Response**
```json
{
  "ask_id": "uuid",
  "answer": "Your project report for Rahul is due by Friday evening, 27 November 2026. [m:uuid]",
  "answer_language": "en-IN",
  "citations": [{
    "id": "uuid", "kind": "memory", "type": "commitment",
    "content": "You promised Rahul you would send him the project report by Friday evening, 27 November 2026.",
    "content_native": "...", "captured_at": "...", "conversation_id": "uuid", "superseded": false,
    "evidence": [{ "utterance_id": "uuid", "quote_native": "...", "quote_en": "...", "speaker": "You", "segment_id": "uuid" }]
  }],
  "query": { "en": "When is my report for Rahul due?", "intent": "..." },
  "latency_ms": 7840, "timings": { "parse+embed": 0, "retrieve": 0, "rerank": 0, "answer": 0 },
  "tts_url": "https://..."
}
```
The `[m:<id>]` markers in `answer` map to `citations[].id`. If ECHO has no supporting memory, `answer` is "I don't have a memory of that yet." and `citations` is empty. Returns `429` after the daily Ask limit.

### `POST /v1/ask/voice`
Multipart form: `file` (audio, up to 5 MB) and `speak` (bool, default `true`). The server transcribes the question with Sarvam (language detected automatically) and answers in the same language. The response is the same as `/v1/ask`, plus `"transcript"`.

### `POST /v1/ask/{ask_id}/feedback`
`{ "feedback": "up" | "down" }` → `{ "ok": true }`

---

## Timeline, memories and conversations

### `GET /v1/timeline?before=<datetime>&limit=20&q=<text>`
Conversations, newest first. `q` searches titles and summaries. Use `next_before` to get the next page.
```json
{
  "items": [{
    "id": "uuid", "started_at": "...", "ended_at": "...", "status": "understood",
    "title": "Memory Retrieval Demo and Software Discussion", "summary": "...",
    "languages": ["en", "ml"], "pinned": false, "in_transit": false, "speaker_count": 2,
    "place": "Finishing Point, Alappuzha",
    "people": [{ "id": "uuid", "name": "Rahul" }],
    "memories": [{ "id": "uuid", "type": "learning", "content": "...", "importance": 0.6, "pinned": false }],
    "memory_count": 3
  }],
  "next_before": "..."
}
```

### `GET /v1/memories/{id}`
Full memory detail: `content`, `content_native`, `type`, `importance`, `confidence`, `sensitivity`, `captured_at`, `time_start`/`time_end`, `place`, `superseded_by`, `conversation`, `evidence[]` (quote, speaker, `spoken_at`, `start_ms`/`end_ms`, `audio_url` if the audio is kept), `entities[]`, `links[]` and `commitment`.

### `PATCH /v1/memories/{id}`
`{ "content_en": "...", "importance": 0.8, "pinned": true }` (all fields optional). If you edit the text, the embedding is made again. → `{ "ok": true }`

### `DELETE /v1/memories/{id}` → `{ "deleted": true }`

### `GET /v1/conversations/{id}`
`title`, `summary`, `status`, `languages`, `place`, `speakers[]`, `utterances[]` (native and English text, speaker, timing, `provisional`), `segments[]` (with signed `audio_url` if the audio is kept) and `memories[]`.

### `DELETE /v1/conversations/{id}`
Deletes the audio files, segments, utterances, memories and links. → `{ "deleted": true }`

### `POST /v1/speakers/{speaker_id}/label`
- `{ "is_me": true }`: marks this speaker as you and seeds your voiceprint.
- `{ "name": "Priya" }`: links the speaker to a person and adds a voice profile. Matching speakers in past conversations get the same label.

→ `{ "ok": true, "person_id": "uuid", "backfilled_speakers": 4 }`

---

## People, promises and digests

| Method | Path | Response |
|---|---|---|
| `GET` | `/v1/people` | `{ items: [{ id, name, aliases, summary, last_interaction_at, interactions, open_commitments }] }` |
| `GET` | `/v1/people/{id}` | Profile plus `commitments[]` and recent `memories[]` |
| `GET` | `/v1/commitments?status=open` | `{ items: [{ memory_id, owner, action, content, counterparty, due_at, status, captured_at }] }` |
| `PATCH` | `/v1/commitments/{memory_id}` | Body `{ "status": "open" \| "done" \| "dismissed" }`. Closing a commitment cancels its reminders. |
| `GET` | `/v1/digests/latest` | `{ digest: { id, day, content, citations } \| null }` |
| `GET` | `/v1/digests/{YYYY-MM-DD}` | Same shape. `404` if there is no digest. |

---

## Account and privacy

### `GET /v1/settings` / `PATCH /v1/settings`
| Field | Type |
|---|---|
| `display_name` | string |
| `timezone` | IANA name, for example `Asia/Kolkata` |
| `answer_language` | for example `hi-IN` |
| `audio_retention_days` | 0 (delete after processing) to 3650 |
| `retention_forever` | bool |
| `quiet_hours` | list |
| `earbud_policy` | `never` \| `when_no_media` \| `always` |
| `location_enabled` | bool. Setting it to `false` also wipes the stored coordinates. |
| `daily_digest_time` | `HH:MM` |
| `speech_cap_min_per_day` | 10 to 1440 |

`PATCH` returns the updated settings.

### `POST /v1/voiceprint`
Multipart `file`: at least 8 s of clear speech. → `{ "enrolled": true, "speech_seconds": 18.4 }`

### `DELETE /v1/voiceprint` → `{ "deleted": true }`

### `GET /v1/export`
Streams `echo-export.json`. It contains your profile, settings, conversations, utterances, speakers, memories, evidence, entities, commitments, reminders, digests, segment metadata and Ask history.

### `DELETE /v1/account`
Deletes all ECHO data and audio files. → `{ "deleted": true, "files": 312 }`. The shared Supabase auth identity is kept.

---

## Internal

### `POST /v1/internal/sarvam/callback`
Completion webhook for Sarvam Batch STT jobs. It is checked with a shared callback token. It is not for clients.
