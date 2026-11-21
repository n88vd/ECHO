# ECHO — System Architecture (v0.1, MVP)

> **MVP job:** Capture a memory today and retrieve it accurately tomorrow — or immediately when asked.
> Status: DRAFT for review. No code is written until this document is approved.

---

## 0. Decision log

| # | Decision | Choice |
|---|----------|--------|
| D1 | Deliverable this phase | Architecture doc first |
| D2 | Capture mode | **Hybrid**: continuous mic + on-device VAD, with Private-mode toggle and scheduled Quiet Hours |
| D3 | Other people's voices | **Diarize and keep all**; label "You" vs "Speaker N"; user can name speakers (e.g. "Rahul") |
| D4 | Raw audio retention | **User-configurable** (delete after processing / 7 / 30 / 90 days / forever) |
| D5 | LLM | **Azure AI Foundry** deployment `gpt-6.1-sol` (resource `imperium-foundry`, eastus2, GlobalStandard); fast tier `gpt-5.4-mini` (already deployed) |
| D6 | Scale target | MVP, < 1k users (with documented seams to scale) |
| D7 | Hosting | **Local full testing first (Docker Compose), then Hostinger VPS** (§10) |
| D12 | Sarvam plan | Pay-as-you-go, 1000 starting credits → strict cost guardrails (§12.7) |
| D13 | Market | **India only** (DPDP Act 2023; Supabase in Mumbai) |
| D14 | Min Android | **Android 10 (API 29)** |
| D15 | Location | **Yes**: place context attached to conversations (§3.5, §5.11) |
| D16 | Phone calls | **Never captured** |
| D17 | "Remember this" | **Yes**: notification action, Quick Settings tile, in-app button, spoken phrase (§3.6) |
| D18 | Embeddings | **`text-embedding-3-large`**, deployed on `imperium-foundry` (GlobalStandard, 150 capacity), used at **1536 dims** (§5.9) |
| D19 | LLM data residency | Keep `gpt-6.1-sol` on **GlobalStandard** |
| D20 | Infra split | **Managed Supabase (Mumbai)** for DB/Auth/Storage + **Hostinger VPS** for api/worker |
| D21 | Push notifications | **No Firebase/FCM.** Reminders are scheduled locally on the device (§5.10) |
| D22 | API domain | **`echo.nmrlabs.space`** (Caddy auto-TLS) |
| D23 | App UI language | **English only** (memories/answers stay multilingual) |
| D8 | Language strategy | **Original transcript + English pivot**; search in English, answer in user's language |
| D9 | Proactive features (MVP) | Promise/task reminders, Daily digest, People profiles |
| D10 | Auth | Supabase Auth — Google sign-in |
| D11 | Ask ECHO | Voice in + voice out (Sarvam STT/TTS), text + sources always shown |

## 0.1 Corrections & risks found in the original spec

1. **Model / provider.** The PDF says "OpenAI GPT Sol 6.2"; the real model is the Azure AI Foundry deployment
   `gpt-6.1-sol` (verified via `az`: model version 2026-09-29, GlobalStandard, capacity 125). It is called with the
   OpenAI SDK pointed at the Foundry OpenAI-compatible endpoint (`.../openai/v1/`, `model=<deployment name>`).
   Deployment names are config values and checked at startup so a wrong name fails fast.
   - **No embedding deployment exists yet** on `imperium-foundry`; one must be created (§5.9, Q8).
   - **GlobalStandard** means prompts may be processed in any Azure region. For India-only users that is allowed
     under DPDP today (no blanket localisation rule), but a *DataZone/Regional* deployment in Central/South India is the
     safer choice for privacy positioning (Q9).
2. **"24x7" contradicts "things you choose to share".** Resolved by D2 (Hybrid) plus a visible always-on indicator,
   one-tap Private mode, Quiet Hours, and per-memory delete.
3. **Bluetooth earbud mic is not free.** On most Android devices the earbud mic is only reachable through the
   HFP/SCO "call" profile. That (a) drops audio to 8–16 kHz narrowband, (b) **pauses/degrades music playback (A2DP)**
   while the mic is open, and (c) drains earbud battery fast. LE Audio (LC3, Android 13+, supported earbuds only)
   fixes this partly. **Recommendation:** use the earbud mic only when the user is *not* playing media, or when the
   phone is in a pocket/bag (proximity + screen off). Phone mic is the default.
4. **Android background mic restrictions.** Android 14+ needs a foreground service with `foregroundServiceType="microphone"`
   and `FOREGROUND_SERVICE_MICROPHONE`. A mic FGS generally cannot be started from the background, and Android 15
   blocks starting it from `BOOT_COMPLETED`. After a reboot, the user must open the app (we send a notification) before
   capture resumes. Mic is also silenced during phone calls and by other apps holding the mic.
5. **Legal.** Recording other people triggers consent rules (India DPDP Act 2023; two-party-consent jurisdictions
   abroad) and Google Play's sensitive-permission review. Needs a privacy policy, in-app disclosure, data export
   and deletion (= "Memory ownership"). Not legal advice — please get a review before public launch.
6. **Sarvam diarization is Batch-API only (beta).** The real-time REST endpoint (< 30 s audio) has no speaker labels.
   This drives the two-path design in §5.4.

---

## 1. Goals, non-goals, SLOs

**Goals**
- Turn noisy, multilingual, often-silent audio into **structured, evidence-linked memories**.
- Answer natural-language questions with **citations back to the exact utterance + audio timestamp**.
- Never lose captured audio (at-least-once delivery, idempotent processing).

**Non-goals (MVP)**
- Real-time live transcription UI, multi-device sync beyond one phone, external sources (email/calendar/docs),
  web app, on-device LLM.

**SLOs (MVP)**
| Metric | Target |
|---|---|
| Segment loss (captured → stored) | < 0.1 % |
| "Freshness": speech → searchable memory (p95, online) | ≤ 5 min (fast path ≤ 60 s) |
| Ask ECHO text answer latency (p95) | ≤ 6 s; first TTS audio ≤ 8 s |
| Recall accuracy on golden set (§12.4) | ≥ 85 % answerable questions correct with valid citation |
| API availability | 99.5 % |

---

## 2. High-level architecture

```
┌──────────────────────── Android (Kotlin + Compose) ────────────────────────┐
│ AudioSourceManager (phone mic ⇄ BT SCO/LE Audio)                           │
│   → CaptureService (FGS, type=microphone)                                  │
│   → On-device VAD (Silero VAD, ONNX) → Segmenter → Opus 16 kHz mono        │
│   → Room "outbox" (encrypted) → WorkManager uploader (resumable, idempotent)│
│ UI: Home · Ask ECHO · Timeline · Memory Detail · Settings                  │
└───────────────┬────────────────────────────────────────────────────────────┘
                │ HTTPS (Supabase JWT)
┌───────────────▼──────────── FastAPI "api" service ─────────────────────────┐
│ /v1/segments (signed-upload + commit) · /v1/ask · /v1/memories · /v1/...   │
│ Auth (Supabase JWKS) · rate-limit · idempotency · enqueue jobs              │
└───────┬─────────────────────────────┬──────────────────────────────────────┘
        │ enqueue (pgmq)              │ read (RLS)
┌───────▼──────────────── Supabase ────────────────────────────────────────────┐
│ Postgres 16 + pgvector (HNSW) + pg_trgm + pgmq + pg_cron                    │
│ Storage (private bucket: raw audio, per-user prefix)  · Auth (Google)       │
└───────▲─────────────────────────────▲──────────────────────────────────────┘
        │ dequeue / write             │
┌───────┴──────────── Python "worker" service (asyncio) ───────────────────────┐
│ Pipeline stages (§5): AudioQA → Stitch → STT → TranscriptQA → Speakers →     │
│ Understand(LLM) → EntityResolve → Embed/Index → Proactive                    │
│ Schedulers: reminders, daily digest, retention purge, people-profile refresh │
└───────┬─────────────┬──────────────────────┬────────────────────────────────┘
        │             │                      │
   Sarvam STT    Sarvam TTS     Azure AI Foundry (gpt-6.1-sol, gpt-5.4-mini, embeddings)
 (REST + Batch)   (Bulbul)
                                  (no push service: device pulls reminders on sync)
```

Design principles: **one database as the system of record** (Postgres holds data, queue, schedules, vectors);
**every stage idempotent and re-runnable**; **providers behind interfaces** (STT, LLM, Embeddings, TTS) so they can be swapped.

---

## 3. Android capture layer (the input quality decides everything)

### 3.1 Audio source management
- `AudioSourceManager` watches `AudioDeviceCallback` + Bluetooth profile state.
- Priority policy (configurable): `LE Audio earbuds` > `phone mic` > `SCO earbuds (only if no media playing)`.
- Switch **at a VAD silence boundary**, never mid-utterance; every segment records `source` (`phone|bt_sco|bt_le`)
  and `sample_rate`, which the server uses for quality gates and STT routing.
- API 31+: `AudioManager.setCommunicationDevice()`; API 29–30: `startBluetoothSco()`.
- **Android 10 baseline:** LE Audio is only available on Android 13+, so on 10–12 earbuds always mean SCO
  (narrowband, interrupts music). On those versions the default earbud policy is *off unless no media is playing*.
- Never capture during phone calls (D16): listen to `AudioManager` mode / `TelephonyCallback` and pause capture
  while `MODE_IN_CALL` / `MODE_IN_COMMUNICATION`. That also covers WhatsApp/Meet calls.

### 3.2 On-device VAD + segmentation (fixes "blank audio" at source)
- 16 kHz mono PCM frames (30 ms) → **Silero VAD** (≈2 MB ONNX, fast enough on CPU).
- Hysteresis: speech starts at p>0.6 for ≥ 250 ms; ends after ≥ 800 ms below 0.35. Pre-roll 300 ms, post-roll 500 ms.
- Segment = one speech run; max 25 s (fits Sarvam REST < 30 s); runs longer than that are split at the lowest-energy frame.
- Segments carry `session_hint` = id of the current "conversation window" (gap < 90 s keeps the same window).
- Encode **Opus @ 16 kHz, ~24 kbps** (~180 KB/min) in an OGG container. Sarvam accepts OGG/OPUS.
- Drop segments with < 400 ms of speech. Server re-validates (defence in depth).

### 3.3 Reliable delivery
- Room `outbox` table (SQLCipher-encrypted): `segment_id (UUIDv7)`, `sha256`, `started_at` (device monotonic + wall clock),
  `duration_ms`, `source`, `speech_ratio`, `upload_state`.
- WorkManager (network-constrained, exponential backoff) uploads in order: `POST /v1/segments:init` → PUT to signed URL →
  `POST /v1/segments/{id}:commit`. **Idempotency key = segment_id**, so retries never create duplicates.
- Local quota: if the outbox exceeds N MB (e.g. 500 MB / ~45 h speech), the oldest uploaded segments are pruned first,
  never un-uploaded ones; the user is warned.

### 3.4 Privacy controls on device
- Persistent notification + in-app orb shows state: *Listening · Paused · Private · Quiet hours · No mic*.
- Private mode (tile in Quick Settings), Quiet Hours schedule, geofenced "never record here" (post-MVP).
- Everything is processed **only after upload**; nothing leaves the device while Private mode is on.

### 3.5 Location context (D15)
- The capture FGS is declared `foregroundServiceType="microphone|location"`. Location is therefore sampled only
  **while capture is running**, using the *while-in-use* permission. **No `ACCESS_BACKGROUND_LOCATION`** is needed,
  which avoids the hardest Play Store review.
- Fused Location Provider, balanced power: one fix at each conversation start, plus one every 5 min during long
  conversations. Coarse by default, precise if the user allows it.
- Each segment carries `{lat, lng, accuracy_m, fix_at}`. Reverse geocoding happens **on the device** (Android
  `Geocoder`, free) to give `locality / sublocality / name`. The server never calls a paid geocoding API.
- Places can be turned off in Settings; existing coordinates can be wiped.

### 3.6 "Remember this" (D17)
Four triggers, one meaning: *the next ~60 s (and the previous 30 s) are important*.
1. A notification action on the always-on capture notification.
2. A Quick Settings tile.
3. A big button on Home.
4. A spoken phrase: "**ECHO, remember this**" / "ECHO, yaad rakhna" / regional variants. This is detected
   **server-side in the transcript**, not with an on-device wake word, so there's no extra battery or model cost.
   Button presses mark segments immediately on the device (`pin=true`). The phrase works retroactively on the
   surrounding utterances.

Effects: the conversation closes early and gets **priority processing** (skips the 3-min wait). Memories get
`importance=1.0` and `pinned=true`. Pinned segments always go through the accurate STT path, and their audio is
kept for at least 30 days regardless of the retention setting (the user can opt out).

---

## 4. Ingestion API

```
POST /v1/segments:init      {segment_id, sha256, duration_ms, started_at, source, sample_rate, speech_ratio, session_hint}
  → 201 {upload_url (Supabase Storage signed, 15 min), path}     | 200 if already exists (idempotent)
PUT  <upload_url>           (binary OGG/Opus)
POST /v1/segments/{id}:commit
  → verifies object exists + sha256 + size, sets status=RECEIVED, enqueues `audio_qa`
```
- Storage path: `audio/{user_id}/{yyyy}/{mm}/{dd}/{segment_id}.ogg` (private bucket, RLS by prefix).
- Per-user guardrails: max speech minutes/day (cost cap, default 6 h), max segment size, clock-skew correction
  (server records `received_at`; uses device `started_at` corrected by the skew measured at upload).

---

## 5. Processing pipeline (the "complex backend")

Each stage is a **pure, idempotent function** `stage(input_ids) → outputs` that writes results plus a row in
`processing_events`. A segment/conversation moves through a state machine:

```
RECEIVED → AUDIO_OK | DISCARDED_BLANK
AUDIO_OK → (stitched into conversation) → TRANSCRIBED → TRANSCRIPT_OK | DISCARDED_NOISE
TRANSCRIPT_OK → SPEAKERS_RESOLVED → UNDERSTOOD → INDEXED → (proactive hooks)
any → FAILED_RETRYABLE (backoff) → DEAD (after N attempts, alert)
```

### 5.1 Stage A — Audio QA (server-side "is this blank?")
Decode with `ffmpeg`/`soundfile` and compute:
| Feature | Use |
|---|---|
| duration, RMS dBFS, peak, clipping % | reject < −55 dBFS mean, or > 5 % clipped (flag, don't reject) |
| Silero VAD speech ratio + total speech ms | **reject if speech < 400 ms or ratio < 0.15** → `DISCARDED_BLANK` |
| SNR estimate (WADA-SNR) | low SNR → route to Batch STT (better on noisy audio) and lower confidence |
| music/TV detector (YAMNet class scores, optional) | flag `media_audio` so TV/radio speech isn't stored as "someone told me" |

Rejected audio is deleted immediately (no cost, no privacy risk); only metrics are kept.

### 5.2 Stage B — Conversation stitching
- Group AUDIO_OK segments into **conversations** by `session_hint` and time gap (< 90 s), same user.
- A conversation is **closed** after 3 min without new segments (or on Private-mode toggle).
- Open conversations get the **fast path**; closed ones get the **accurate path** (§5.4).

### 5.3 Stage C — Language identification
- Use Sarvam's built-in detection (`language_code="unknown"` → returns `language_code` + `language_probability`).
- Keep a per-user **language prior** (distribution of the last 30 days); if probability < 0.6, re-run with the
  top-prior language and keep the higher-confidence result.
- Code-mixed speech (Hinglish/Tanglish…) is normal. Store both `transcribe` output (native script) and use
  `codemix` only for display preference (setting).

### 5.4 Stage D — Speech-to-text (two paths)
| Path | When | API | Output |
|---|---|---|---|
| **Fast** | each segment as it arrives (≤ 25 s) | Sarvam REST `POST /speech-to-text`, `model=saaras:v4`, `mode=transcribe`, `with_timestamps=true` | provisional transcript, searchable within ~60 s |
| **Accurate** | conversation closed and has ≥ 2 voices *or* ≥ 60 s speech | Sarvam **Batch** job, `with_diarization=true`, `with_timestamps=true`, callback URL | diarized utterances; **replaces** the provisional transcript |

- **Keyterm biasing:** pass up to 50 `keyterms` per request, made from the user's known people, places and frequent
  entities (from the graph). That greatly improves names like "Rahul", "Koramangala".
- **English pivot:** generated in Stage G by the LLM (one call does translation + extraction, cheaper than a second STT
  pass). Fallback: Sarvam `mode=translate` when the LLM flags the source text as low confidence.
- **Budget mode (default while on pay-as-you-go credits, D12).** Running both paths would transcribe every
  second of audio **twice**, so in budget mode:
  - every segment is transcribed **once** (REST, with `with_timestamps=true`);
  - "who spoke" is worked out **locally** instead of with Sarvam Batch. Each timestamped chunk gets an ECAPA speaker
    embedding (the same model as §5.6), and the chunks of a conversation are clustered (agglomerative, cosine
    threshold tuned on the golden set). This is good at turn level; it misses overlapping speech, which is
    acceptable for the MVP;
  - the Sarvam Batch diarized path runs **only for pinned ("Remember this") conversations**, or when local clustering
    confidence is low *and* the conversation contains a commitment/decision.
  - Switching to *quality mode* (both paths for every multi-speaker conversation) is a single config flag once
    credits allow.
- Provider adapter handles 429/503 with exponential backoff + jitter, a per-provider concurrency limit, and a circuit
  breaker. Batch jobs are tracked in `stt_jobs`; callback + fallback polling (no faster than plan limits).

### 5.5 Stage E — Transcript QA ("is this valuable?")
Reject or down-weight when:
- empty / only fillers ("hmm", "haan", "okay") after normalisation;
- **ASR hallucination patterns**: repeated n-grams (repetition ratio > 0.5), characters-per-second outside
  [2, 30] for the language, a known hallucination phrase list;
- `language_probability` < 0.4 and SNR low;
- `media_audio` flag from Stage A (kept but marked `source_kind=media`, excluded from "who told me" answers).

Output: `quality_score ∈ [0,1]` per utterance; < 0.3 → `DISCARDED_NOISE`.

### 5.6 Stage F — Speaker resolution
1. **Enrolment:** onboarding records ~20 s of the user reading a prompt → speaker embedding (ECAPA-TDNN via
   SpeechBrain, CPU, self-hosted in the worker) stored as `user_voiceprint` (encrypted, deletable).
2. For each diarized speaker cluster, compute its embedding; cosine ≥ 0.7 with the voiceprint → **"You"**.
3. Other clusters are matched against `voice_profiles` of previously named people (≥ 0.75 → auto-label, else
   "Speaker 2"). The user can name a speaker in Memory Detail ("This is Rahul"), which back-fills past matches.
4. Fast-path (non-diarized) segments: whole-segment embedding vs voiceprint gives "You / not you / unknown".

### 5.7 Stage G — Understanding (LLM, structured output)
One LLM call per conversation (chunked at ~6k tokens with overlap), using a **strict JSON schema**:
```
{
  "summary_en": str, "title_en": str, "language": "hi-IN", "topics": [str],
  "utterances_en": [{"utterance_id", "text_en"}],                    // English pivot
  "memories": [{
     "type": "fact|event|commitment|decision|idea|learning|object_location|person_info|question",
     "content_en": str, "content_native": str,
     "evidence_utterance_ids": [uuid],                                 // REQUIRED, else dropped
     "subject_speaker": "you|speaker_2|...", "people": [str], "places": [str], "objects": [str],
     "time_ref": {"text": "next Friday", "resolved_start": iso, "resolved_end": iso} | null,
     "commitment": {"owner": "you|speaker_x", "counterparty": str, "action": str, "due": iso|null} | null,
     "decision": {"choice": str, "rationale": str, "alternatives": [str]} | null,
     "importance": 0..1, "confidence": 0..1,
     "sensitivity": ["none|pii|financial|health|credential"]
  }]
}
```
- The prompt includes the conversation's absolute start time + user time zone, so "tomorrow" resolves correctly.
- **Grounding check (deterministic):** every memory must cite existing utterance IDs, and key nouns in `content_en`
  must appear in the cited utterances' English text (fuzzy match). Failures → dropped or `confidence *= 0.5`.
- **Credential redaction:** OTPs, card numbers, passwords and Aadhaar-like patterns are regex + LLM detected and
  masked *before* storage and embedding.
- Models (Azure AI Foundry deployments, config values):
  `LLM_DEPLOYMENT_REASONING=gpt-6.1-sol` for understanding and answering;
  `LLM_DEPLOYMENT_FAST=gpt-5.4-mini` for query parsing, titles, transcript-QA tie-breaks, and "remember this" phrase
  confirmation.
- Client: `openai.OpenAI(base_url=AZURE_OPENAI_BASE_URL, api_key=AZURE_OPENAI_API_KEY)` with
  `AZURE_OPENAI_BASE_URL=https://imperium-foundry.services.ai.azure.com/api/projects/imperium-1/openai/v1/`
  (or the resource-level `/openai/v1/` endpoint). Wrapped in our `LLMProvider` interface, so other deployments
  on the same resource can be swapped in for evaluation.
- Rate limits: the deployment's TPM/RPM quota is enforced client-side with a token bucket shared by all workers
  (stored in Postgres), so bursts queue up instead of hitting 429s.

### 5.8 Stage H — Entity resolution & memory graph
- Entities: `person`, `place`, `object`, `organization`, `topic`.
- Resolution: normalise (case, script transliteration via Sarvam/ICU so "राहुल" = "Rahul") → exact alias match →
  trigram + embedding candidate search → LLM adjudication only for ambiguous cases → merge or create.
- Links (`memory_links`): `same_topic`, `follow_up_of`, `contradicts`, **`supersedes`**.
  *Supersession matters for "Where did I keep my passport?"*: a new `object_location` for the same object
  supersedes the old one; retrieval prefers the latest non-superseded memory but can show history.
- People profiles (D9): materialised per person — last interaction, topics, open commitments both ways,
  facts ("Rahul's sister is getting married in March"). Refreshed incrementally on new memories.

### 5.9 Stage I — Embedding & indexing
- Embed `content_en` (+ title/people context) for memories, and `summary_en` for conversations.
  `EMBEDDING_DEPLOYMENT=text-embedding-3-large` (deployed and verified: returns 1536 and 3072 dims).
- **Why 1536 and not 3072 dims:** pgvector's HNSW index supports at most **2000 dims for `vector`**, so native 3072-d
  vectors can't be indexed as `vector`. text-embedding-3 models support the `dimensions` parameter (truncated
  Matryoshka embeddings). `-large@1536` keeps nearly all of the quality, beats `-small` on multilingual retrieval,
  and halves storage and index size.
  Alternative, if the golden set shows a measurable gain: store `halfvec(3072)` (HNSW supports halfvec up to
  4000 dims). This is a config + migration change, not a redesign.
- `EMBEDDING_DIMENSIONS=1536` is sent on every call. Queries and documents **must** use the same model + dims; this is
  enforced via the `embedding_model` column (`text-embedding-3-large@1536`).
- Indexes: pgvector **HNSW** (cosine), Postgres `tsvector` (English) for keyword search, `pg_trgm` on native text and
  entity aliases for names/transliterations.
- Re-embedding is versioned (`embedding_model` column), so we can migrate models without downtime.

### 5.10 Stage J — Proactive hooks
- **Commitments** → `reminders` (due time, or a default nudge after 24 h if no date). Marked done via the app, or
  automatically when a later conversation shows completion (LLM check).
- **Delivery without FCM (D21):** the capture foreground service keeps the app process alive, and the app already
  talks to the API on every upload cycle. Each sync response includes `GET /v1/sync` deltas (new/changed
  reminders, digest ready). The app schedules them **locally** with WorkManager/`AlarmManager.setWindow`
  (±5 min accuracy; avoids the `SCHEDULE_EXACT_ALARM` permission on Android 12+), and shows local notifications.
  Reminders survive reboot (rescheduled on `BOOT_COMPLETED`; showing a notification there is allowed, unlike
  starting the mic).
  Limitation: if the app is force-stopped or not opened for days, reminders created by the server in that time are
  only delivered on the next app open. Acceptable for the MVP.
- **Daily digest** (pg_cron at the user's local 21:00): conversations, decisions, new people, open promises;
  stored as a memory-like `digest` with citations; optional TTS audio.
- **People profiles** refresh (§5.8).

### 5.11 Stage K — Places
- Per-user **place clustering**: DBSCAN over conversation coordinates (eps ≈ 75 m, min 3 visits). Clusters become
  `place` entities, auto-labelled from dwell patterns ("Home" = most nights, "Work" = weekday daytime). The user can
  rename them. The device-geocoded locality is used as a fallback label ("Indiranagar, Bengaluru").
- **Travel detection:** speed between consecutive fixes > 25 km/h → conversation tagged `in_transit`. This answers
  "the idea I had while travelling".
- Memories inherit `place_id` from their conversation. The LLM also extracts *spoken* places ("kept it at mom's
  place"), which are linked as `object_location` targets, separate from where the user physically was.

---

## 6. Retrieval & answering — "Ask ECHO"

```
voice ─► Sarvam STT (REST, language auto) ─► query text (native + English)
      ─► Query understanding (LLM_FAST, JSON): intent, entities, time window, memory types, wants_latest
      ─► Hybrid candidate generation (parallel, all user-scoped):
            a) pgvector ANN on memories (k=50)          b) FTS on content_en (k=50)
            c) trigram on native text/aliases (k=20)    d) graph: memories linked to resolved entities (k=50)
            e) structured filters: type, time window, not superseded (if wants_latest)
      ─► Reciprocal Rank Fusion  ─► feature re-score:
            score = RRF + w1·importance + w2·recency_decay(type) + w3·speaker_match + w4·quality − superseded_penalty
      ─► LLM re-rank top 30 → top 8 with their evidence utterances
      ─► Answer (LLM_REASONING): MUST cite [m:<id>] for every claim; must say "I don't have a memory of that"
         when evidence is insufficient
      ─► Citation verifier (deterministic): drop/flag uncited sentences, verify IDs ∈ provided set
      ─► Output in user's language (LLM writes it directly) ─► Sarvam TTS (Bulbul), streamed
```
- Response = `{answer_text, answer_lang, citations:[{memory_id, conversation_id, utterance_ids, quote_native,
  quote_en, captured_at, audio_offset_ms (if retained)}], tts_url}`.
- Tapping a citation opens **Memory Detail**, with the quote, speaker, time, place (if known) and, when retained,
  the audio clip seeked to the utterance.
- **Freshness:** retrieval also searches provisional (fast-path) transcripts from the last 10 minutes, so "what did
  he just say?" works immediately.

---

## 7. Data model (Supabase Postgres)

All user tables have `user_id uuid not null references auth.users` + **RLS: `user_id = auth.uid()`**. Workers use
the service role. IDs are UUIDv7 (time-ordered → index-friendly).

```sql
profiles(user_id pk, display_name, timezone, primary_language, answer_language, created_at)
user_settings(user_id pk, audio_retention_days int null /* null=forever, 0=delete after processing */,
              quiet_hours jsonb, earbud_policy text, daily_digest_time time, speech_cap_min_per_day int)
devices(id, user_id, model, os_version, app_version, last_sync_at, sync_cursor)
voiceprints(user_id pk, embedding vector(192), model, created_at)

audio_segments(id pk, user_id, device_id, conversation_id null, storage_path null, sha256, started_at, duration_ms,
               source, sample_rate, snr_db, speech_ms, speech_ratio, media_flag bool, pinned bool,
               lat, lng, accuracy_m, locality text,
               status, attempt int, error text, created_at)
conversations(id, user_id, started_at, ended_at, status /* open|closed */, languages text[],
              title_en, summary_en, summary_embedding vector(1536), place_id null -> entities, in_transit bool,
              pinned bool, quality_score)
utterances(id, user_id, conversation_id, segment_id, speaker_id null, start_ms, end_ms,
           text_native, text_en, language, lang_prob, quality_score, is_provisional bool, stt_path)
speakers(id, user_id, conversation_id, label /* you|speaker_2 */, person_id null, embedding vector(192))

entities(id, user_id, kind, canonical_name, aliases text[], attributes jsonb, embedding vector(1536))
voice_profiles(id, user_id, person_id -> entities, embedding vector(192))

memories(id, user_id, conversation_id, type, content_en, content_native, importance, confidence, sensitivity text[],
         pinned bool, place_id null -> entities,
         time_start, time_end, captured_at, superseded_by null, embedding vector(1536), embedding_model,
         fts tsvector generated, created_at, deleted_at null)
memory_evidence(memory_id, utterance_id)                       -- citations
memory_entities(memory_id, entity_id, role /* subject|counterparty|object|place */)
memory_links(src_memory_id, dst_memory_id, kind, score)
commitments(memory_id pk, owner, counterparty_entity_id, action, due_at, status /* open|done|dismissed */)
reminders(id, user_id, commitment_id, fire_at, status, sent_at)
digests(id, user_id, date, content, citations jsonb)
person_profiles(entity_id pk, user_id, summary, last_interaction_at, open_commitments int, refreshed_at)

stt_jobs(id, user_id, conversation_id, provider_job_id, state, submitted_at, completed_at)
processing_events(id, user_id, subject_type, subject_id, stage, status, duration_ms, cost_units, error, created_at)
cost_ledger(id, user_id null, provider /* sarvam_stt|sarvam_tts|azure_llm|azure_embed */, units, unit_kind,
            est_cost_inr, subject_id, created_at)                -- drives budget guardrails (§12.7)
ask_log(id, user_id, query_native, query_en, latency_ms, citations jsonb, feedback /* up|down */, created_at)
```
Indexes: HNSW on `memories.embedding`, `conversations.summary_embedding`; GIN on `memories.fts`;
GIN trigram on `utterances.text_native`, `entities.aliases`; B-tree `(user_id, captured_at desc)` everywhere for the Timeline.

**Scale seams (not built for MVP):** time-partition `utterances`/`audio_segments` by month; move queue to Pub/Sub;
per-user HNSW partial indexes or a dedicated vector store if > ~50M vectors.

---

## 8. Job orchestration

- **Queue:** `pgmq` (Postgres-native queue on Supabase) — visibility timeout, retries, an archive table as the DLQ.
  No Redis needed at MVP scale; queue state is transactional with the data (no "row written but job lost").
- Queues: `audio_qa`, `stt_fast`, `stt_batch_submit`, `stt_batch_collect`, `understand`, `entity_resolve`,
  `embed`, `proactive`, `purge`.
- Worker: one Python asyncio process type, running per-queue consumers with configurable concurrency;
  each handler is idempotent (upserts keyed by subject id + stage version).
- Retry: exponential backoff (2^n · 5 s, max 1 h, 8 attempts) → DLQ + alert. Provider 4xx (bad input) → no retry.
- **Pipeline versioning:** `stage_version` in `processing_events`; bumping a version allows a controlled backfill
  (e.g. re-run Understanding with a better prompt over the last 30 days).
- **Schedules (`pg_cron`):** close stale conversations (1 min), reminder dispatch (1 min), daily digests (15 min sweep
  by timezone), retention purge (hourly), stuck-job sweeper (5 min).

---

## 9. API surface (FastAPI, `/v1`)

| Method & path | Purpose |
|---|---|
| `POST /segments:init`, `POST /segments/{id}:commit` | Ingestion (§4) |
| `GET /status` | Capture/pipeline health for Home (last upload, backlog, today's speech minutes) |
| `POST /ask` (JSON or multipart audio) | Ask ECHO; `?stream=true` → SSE tokens + citations, then TTS URL |
| `GET /timeline?from&to&cursor&type` | Timeline (conversations + key memories, day-grouped) |
| `GET /memories/{id}` · `PATCH` · `DELETE` | Memory Detail, corrections, delete (cascade evidence) |
| `GET /conversations/{id}` | Utterances, speakers, audio clip URLs (if retained) |
| `POST /speakers/{id}:label` | "This is Rahul" → back-fill |
| `GET /people`, `GET /people/{id}` | People profiles |
| `GET/PATCH /commitments`, `GET /digests/{date}` | Proactive |
| `GET/PATCH /settings`, `POST /voiceprint` | Settings + enrolment |
| `POST /export` → async zip; `DELETE /account` | Memory ownership (DPDP) |
| `GET /sync?cursor=` | Delta feed for the device: reminders, digests, processing status (replaces push) |
| `POST /internal/sarvam/callback` (HMAC-verified) | Batch STT completion — `https://echo.nmrlabs.space/v1/internal/sarvam/callback` |

Auth: verify Supabase JWT (JWKS, cached) on every request; `user_id` comes only from the token.

---

## 10. Hosting & environments (D7)

### 10.1 Local (full testing first)
- `supabase start` (Supabase CLI) runs Postgres + pgvector + pgmq + pg_cron, Auth, and Storage in Docker. It uses the
  same migrations as production.
- `docker compose up` runs `api` + `worker` against the local Supabase.
- **Provider modes** via env: `PROVIDERS=fake | record | live`.
  - `fake`: deterministic stubs. Used by unit/integration tests and costs **0 credits**.
  - `record`: calls the live Sarvam/Azure APIs once and saves the responses as fixtures (cassettes).
  - `live`: real calls, behind the budget guardrails (§12.7).
- The Android emulator/phone points at the laptop's LAN IP; Google sign-in goes through the local Supabase Auth with
  a dev OAuth client.

### 10.2 Production — Hostinger VPS
```
Internet ─► Caddy (auto-TLS, HTTP/2, rate-limit) ─► api (uvicorn, 2–4 workers)
                                                  └► /internal/sarvam/callback
            worker (asyncio consumers + CPU pool for VAD / ECAPA)      ─┐
            otel-collector → Grafana Cloud free tier / or Uptime Kuma   │  docker compose,
            restic backups → off-box object storage                    ─┘  restart: unless-stopped
Supabase (managed, Mumbai ap-south-1): Postgres, Storage, Auth          ◄── api / worker over TLS
```
- **Domain:** `echo.nmrlabs.space`. ⚠ It **does not resolve yet** (checked with `dig`; the apex `nmrlabs.space`
  points at `72.60.99.53`). Add an **A record `echo` → <VPS public IP>** before deploying; Caddy then gets the
  Let's Encrypt certificate automatically.
- **Size:** ≥ 4 vCPU / 16 GB RAM (e.g. Hostinger KVM 4 class). ECAPA + Silero on CPU is the main load; at < 1k
  users this has lots of headroom. Pick the India data-centre location if your plan offers it.
- **Keep the database on managed Supabase**, not self-hosted on the VPS. Then the VPS is stateless and can be rebuilt
  from git + secrets in minutes, and backups/PITR, Auth and Storage stay managed. The VPS is a single point of
  failure, but because the phone's outbox (§3.3) buffers uploads, a VPS outage means **delay, not data loss**.
- **Hardening:** SSH keys only, no root login, `ufw` (22/80/443 only), `fail2ban`, unattended security upgrades,
  Docker images pinned by digest, secrets in a root-only `.env` (never in git), non-root containers.
- **Deploy:** GitHub Actions builds images → GHCR → SSH `docker compose pull && up -d` with a health-check gate
  and automatic rollback to the previous tag.
- **Scale seam:** add a second VPS running only `worker` (queue consumers scale horizontally out of the box via
  pgmq), or move to Cloud Run later. No code changes needed.

---

## 11. Security, privacy, memory ownership

- Supabase Auth (Google). Short-lived JWT; refresh on device. FastAPI validates `aud`, `iss`, `exp`.
- RLS on every table; the service role key exists **only** in the worker/API runtime, never on device.
- Storage: private bucket, per-user prefix policies, signed URLs ≤ 15 min.
- Encryption: at rest (Supabase), in transit (TLS 1.2+), device outbox (SQLCipher + Android Keystore).
- Redaction of credentials before storage/embedding (§5.7). Sensitive memories (`health`, `financial`) hidden from the
  digest and notifications unless the user opts in.
- **Retention (D4):** purge job deletes audio objects past `audio_retention_days`; transcripts/memories stay until the
  user deletes them. "Delete conversation" hard-deletes audio, utterances, memories, embeddings and links.
- **Export:** JSON + Markdown + audio (if retained) zip. **Account delete:** full cascade within 24 h, logged.
- No logging of transcript text or audio in application logs (IDs + metrics only).

---

## 12. Reliability & operations

1. **Idempotency everywhere:** client-generated segment IDs; upserts keyed by `(subject_id, stage, stage_version)`.
2. **Backpressure:** per-user speech cap; per-provider concurrency limits; queue-depth alerts.
3. **Degradation:** if Sarvam is down, segments queue (no data loss) and Home shows "Processing delayed";
   if the LLM is down, transcripts are still FTS-searchable (Ask ECHO falls back to "here are matching excerpts").
4. **Evaluation harness (most important for the MVP's one job):**
   - Golden set: ~200 scripted multilingual recordings (Hindi, Tamil, Kannada, Hinglish, noisy café, earbud SCO,
     TV in background, silence) + ~300 questions with expected memory IDs.
   - Metrics: blank-detection precision/recall, WER/CER per language, extraction precision/recall per memory type,
     retrieval Recall@8 / MRR, answer correctness + citation validity, hallucination rate.
   - Runs in CI on every prompt/model/threshold change; results tracked over time.
5. **Observability:** OpenTelemetry traces (segment_id as trace attribute across stages), structured JSON logs,
   Sentry for errors, per-stage latency/cost dashboards, provider error-rate alerts, DLQ alerts.
6. **Cost model (per user/day):** `speech_minutes × (STT_fast + STT_batch_share) + conversations × LLM_tokens +
   memories × embedding + asks × (STT + LLM + TTS)`. On-device VAD typically removes most of the 24 h, leaving
   1–3 h of real speech. Exact prices are filled in from current Sarvam/Azure pricing before launch.
7. **Budget guardrails (§12.7, required while on 1000 Sarvam credits):**
   - Every provider call writes a `cost_ledger` row (audio seconds, characters, tokens).
   - Limits: **global daily Sarvam budget**, **per-user daily speech-minutes cap**, and a **per-user daily Ask cap**.
     At 80 % → alert; at 100 % → new audio keeps queuing (never dropped) and is processed when the budget resets.
     Home shows "Processing paused — daily limit".
   - Cheapest-first ordering: on-device VAD → server blank filter → transcript QA *before* any LLM call. Pinned
     conversations are always processed first.
   - TTS answers are cached by `(text hash, voice, language)`. The daily digest uses TTS only if the user taps play.
   - Development and CI run on `fake`/`record` providers, so tests never spend credits.

---

## 13. Backend repository layout (proposed)

```
backend/
  pyproject.toml            # uv; FastAPI, pydantic v2, asyncpg/SQLAlchemy 2, httpx, tenacity, onnxruntime,
                            # speechbrain (CPU), soundfile, openai, sarvamai, opentelemetry, structlog
  app/
    api/            # routers: segments, ask, timeline, memories, people, settings, internal
    core/           # config (pydantic-settings), auth (JWKS), db, logging, telemetry, errors
    domain/         # pydantic models, enums, state machine
    providers/      # stt/sarvam.py, tts/sarvam.py, llm/openai.py, embeddings/openai.py  (interfaces + adapters)
    pipeline/       # audio_qa, stitch, stt, transcript_qa, speakers, understand, entities, embed, proactive
    retrieval/      # query_parse, candidates, fusion, rerank, answer, citations
    workers/        # queue consumer runtime, schedules
    prompts/        # versioned prompt templates + JSON schemas
  supabase/migrations/      # SQL: tables, RLS, indexes, pgmq queues, pg_cron jobs
  eval/                     # golden dataset manifests + harness
  tests/                    # unit (pure stages), integration (testcontainers Postgres+pgvector), provider fakes
  Dockerfile.api  Dockerfile.worker
```

---

## 14. Android app mapping (UI direction from `UI Inspiration/`)

Style: light, airy glassmorphism; pastel gradient **orb** as ECHO's "presence" (animates with VAD level:
listening / paused / private); rounded pill chips; chat answers with **Sources** cards (see inspiration 5).

| Screen | Content | APIs |
|---|---|---|
| Home | Orb + capture state, today's speech minutes, "Ask anything" bar with mic, recent memories, open promises | `/status`, `/timeline?today`, `/commitments` |
| Ask ECHO | Voice/text input, streaming answer, Sources cards, play TTS | `/ask` |
| Timeline | Day-grouped conversations & key memories, filters (people, type, language) | `/timeline` |
| Memory Detail | Quote (native + English), speaker, time, linked people/memories, audio clip, edit/delete, "this is…" labelling | `/memories/{id}`, `/conversations/{id}`, `/speakers/{id}:label` |
| Settings | Capture source policy, Quiet Hours, Private mode, retention, languages, voice enrolment, export/delete | `/settings`, `/voiceprint`, `/export`, `/account` |

---

## 15. Milestones

1. **M1 — Foundations:** local Supabase + migrations (schema, RLS, pgmq, pg_cron); FastAPI auth; ingestion; worker runtime; fake providers; CI.
2. **M2 — Audio → text:** Audio QA (blank detection), fast-path STT, transcript QA, stitching. Golden-set WER report.
3. **M3 — Understanding:** batch diarized STT, speakers + voiceprint, LLM extraction w/ grounding, entities, embeddings.
4. **M4 — Recall:** hybrid retrieval, fusion, re-rank, cited answers, TTS. Golden-set recall report.
5. **M5 — Proactive & ownership:** reminders, digest, people profiles, retention purge, export/delete.
6. **M6 — Android:** capture service + VAD + outbox + location + "Remember this", 5 screens, local reminders via sync. End-to-end dogfood.
7. **M7 — Production:** Hostinger VPS hardening, Caddy, CI/CD, backups, monitoring; switch providers to `live`.

---

## 16. Resolved questions
Q1 → D5 · Q2 → D12 · Q3 → D13 · Q4 → D14 · Q5 → D15 · Q6 → D16 · Q7 → D17 · hosting → D7.

Round 2: Q8 → D18 · Q9 → D19 · Q10 → D20 · Q11 → D21 · Q12 → D22 · Q13 → D23.

## 17. Remaining items (non-blocking for M1)
- DNS: create the `echo.nmrlabs.space` A record once the VPS IP is known (needed only at M7).
- Supabase project (Mumbai) for staging/prod: needed only after local testing; local dev uses `supabase start`.
- Sarvam API key and Azure key go in the local `.env` (never committed). I won't ask you to paste them into chat.

---

## 18. Implementation notes (v0.2, as built)
- **Hosting:** the VPS is shared (≈30 containers, host nginx on 80/443), so ECHO runs behind the existing nginx
  (`/etc/nginx/sites-available/echo.nmrlabs.space.conf`, certbot TLS) instead of Caddy; containers bind 127.0.0.1:8070.
  VPS↔Supabase pooler latency is ~5 ms (both Mumbai).
- **Lightweight models:** Silero VAD + 3D-Speaker CAM++ speaker embeddings (512-d) via `sherpa-onnx` (no PyTorch);
  worker ≈250 MB RSS.
- **Decoding:** libsndfile first, PyAV/FFmpeg fallback (Android MediaMuxer OGG). Speech is always re-encoded to 16 kHz WAV
  (silence compacted when speech ratio < 0.7) before STT, cutting billed seconds.
- **Auth:** the app never holds a Supabase key: `POST /v1/auth/google` exchanges a Credential-Manager Google ID token for a
  Supabase session; `/v1/auth/refresh` rotates it. Tokens are AES-GCM encrypted with an Android Keystore key.
- **Budget mode:** one REST STT pass per segment; Sarvam Batch diarization only for "Remember this" conversations;
  local speaker clustering otherwise. Cost ledger + global/per-user daily caps; over-budget work is delayed, never dropped.
- **Verified:** 21 unit tests; DB E2E (real Supabase, fake AI); live E2E (real Sarvam/Azure: en/hi/ta/Hinglish, Batch
  diarization, Hindi answer + TTS, "don't know" answer); real capture on an HONOR X9b (Android 15) uploading to production.
- **Measured Ask latency (prod):** ~8 s, mostly the three Azure calls in East US 2 (~2.5 s each). Next: stream the answer,
  skip rerank when the fused top hit is clear, or move to a regional deployment.
