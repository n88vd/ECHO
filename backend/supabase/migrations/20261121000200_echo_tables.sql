set local search_path = echo, extensions, public;

create table echo.profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  display_name text,
  timezone text not null default 'Asia/Kolkata',
  primary_language text not null default 'en-IN',
  answer_language text not null default 'en-IN',
  onboarded_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table echo.user_settings (
  user_id uuid primary key references echo.profiles(user_id) on delete cascade,
  audio_retention_days int check (audio_retention_days is null or audio_retention_days >= 0),
  quiet_hours jsonb not null default '[]'::jsonb,
  earbud_policy text not null default 'when_no_media' check (earbud_policy in ('never', 'when_no_media', 'always')),
  location_enabled boolean not null default true,
  daily_digest_time time not null default '21:00',
  speech_cap_min_per_day int not null default 360 check (speech_cap_min_per_day > 0),
  ask_cap_per_day int not null default 100 check (ask_cap_per_day > 0),
  pinned_audio_min_days int not null default 30,
  updated_at timestamptz not null default now()
);

create table echo.devices (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references echo.profiles(user_id) on delete cascade,
  model text,
  os_version text,
  app_version text,
  sync_cursor bigint not null default 0,
  last_sync_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index on echo.devices (user_id);

create table echo.voiceprints (
  user_id uuid primary key references echo.profiles(user_id) on delete cascade,
  embedding vector(192) not null,
  model text not null,
  created_at timestamptz not null default now()
);

create table echo.entities (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references echo.profiles(user_id) on delete cascade,
  kind text not null check (kind in ('person', 'place', 'object', 'organization', 'topic')),
  canonical_name text not null,
  aliases text[] not null default '{}',
  attributes jsonb not null default '{}'::jsonb,
  lat double precision,
  lng double precision,
  embedding vector(1536),
  embedding_model text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index on echo.entities (user_id, kind);
create index entities_aliases on echo.entities using gin (aliases);
create index entities_name_trgm on echo.entities using gin (canonical_name gin_trgm_ops);
create index entities_embedding_hnsw on echo.entities using hnsw (embedding vector_cosine_ops);

create table echo.voice_profiles (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references echo.profiles(user_id) on delete cascade,
  person_id uuid not null references echo.entities(id) on delete cascade,
  embedding vector(192) not null,
  model text not null,
  created_at timestamptz not null default now()
);
create index on echo.voice_profiles (user_id);

create table echo.conversations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references echo.profiles(user_id) on delete cascade,
  session_hint uuid,
  started_at timestamptz not null,
  ended_at timestamptz,
  last_segment_at timestamptz not null,
  status text not null default 'open' check (status in ('open', 'closed', 'understood', 'failed')),
  languages text[] not null default '{}',
  title_en text,
  summary_en text,
  summary_embedding vector(1536),
  embedding_model text,
  place_id uuid references echo.entities(id) on delete set null,
  in_transit boolean not null default false,
  pinned boolean not null default false,
  speaker_count int,
  quality_score real,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index on echo.conversations (user_id, started_at desc);
create index conversations_open on echo.conversations (last_segment_at) where status = 'open';
create index conversations_summary_hnsw on echo.conversations using hnsw (summary_embedding vector_cosine_ops);

create table echo.audio_segments (
  id uuid primary key,
  user_id uuid not null references echo.profiles(user_id) on delete cascade,
  device_id uuid references echo.devices(id) on delete set null,
  conversation_id uuid references echo.conversations(id) on delete set null,
  session_hint uuid,
  storage_path text,
  sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  size_bytes int,
  started_at timestamptz not null,
  received_at timestamptz not null default now(),
  duration_ms int not null check (duration_ms > 0 and duration_ms <= 60000),
  source text not null check (source in ('phone', 'bt_sco', 'bt_le', 'wired')),
  sample_rate int not null,
  device_speech_ratio real,
  snr_db real,
  speech_ms int,
  speech_ratio real,
  rms_dbfs real,
  clipping_ratio real,
  media_flag boolean not null default false,
  pinned boolean not null default false,
  lat double precision,
  lng double precision,
  accuracy_m real,
  locality text,
  status text not null default 'pending_upload' check (status in (
    'pending_upload', 'received', 'audio_ok', 'discarded_blank', 'transcribed',
    'transcript_ok', 'discarded_noise', 'failed_retryable', 'dead')),
  attempt int not null default 0,
  error text,
  audio_deleted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index on echo.audio_segments (user_id, started_at desc);
create index on echo.audio_segments (conversation_id);
create index audio_segments_active on echo.audio_segments (status, updated_at)
  where status in ('pending_upload', 'received', 'audio_ok', 'transcribed', 'failed_retryable');
create index audio_segments_retention on echo.audio_segments (user_id, started_at)
  where storage_path is not null and audio_deleted_at is null;

create table echo.speakers (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references echo.profiles(user_id) on delete cascade,
  conversation_id uuid not null references echo.conversations(id) on delete cascade,
  label text not null,
  is_user boolean not null default false,
  person_id uuid references echo.entities(id) on delete set null,
  embedding vector(192),
  match_score real,
  created_at timestamptz not null default now(),
  unique (conversation_id, label)
);
create index on echo.speakers (user_id, person_id);

create table echo.utterances (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references echo.profiles(user_id) on delete cascade,
  conversation_id uuid not null references echo.conversations(id) on delete cascade,
  segment_id uuid references echo.audio_segments(id) on delete set null,
  speaker_id uuid references echo.speakers(id) on delete set null,
  start_ms int not null,
  end_ms int not null check (end_ms >= start_ms),
  text_native text not null,
  text_en text,
  language text,
  lang_prob real,
  quality_score real,
  is_provisional boolean not null default true,
  stt_path text not null check (stt_path in ('fast', 'batch')),
  stt_request_id text,
  created_at timestamptz not null default now()
);
create index on echo.utterances (conversation_id, start_ms);
create index on echo.utterances (user_id, created_at desc);
create index utterances_native_trgm on echo.utterances using gin (text_native gin_trgm_ops);
create index utterances_en_fts on echo.utterances using gin (to_tsvector('english', coalesce(text_en, '')));

create table echo.memories (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references echo.profiles(user_id) on delete cascade,
  conversation_id uuid references echo.conversations(id) on delete cascade,
  type text not null check (type in (
    'fact', 'event', 'commitment', 'decision', 'idea', 'learning',
    'object_location', 'person_info', 'question', 'digest')),
  content_en text not null,
  content_native text,
  importance real not null default 0.5 check (importance between 0 and 1),
  confidence real not null default 0.5 check (confidence between 0 and 1),
  sensitivity text[] not null default '{}',
  pinned boolean not null default false,
  place_id uuid references echo.entities(id) on delete set null,
  time_start timestamptz,
  time_end timestamptz,
  captured_at timestamptz not null,
  superseded_by uuid references echo.memories(id) on delete set null,
  embedding vector(1536),
  embedding_model text,
  stage_version int not null default 1,
  fts tsvector generated always as (to_tsvector('english', coalesce(content_en, ''))) stored,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);
create index on echo.memories (user_id, captured_at desc) where deleted_at is null;
create index on echo.memories (user_id, type) where deleted_at is null;
create index on echo.memories (conversation_id);
create index memories_fts on echo.memories using gin (fts);
create index memories_native_trgm on echo.memories using gin (coalesce(content_native, '') gin_trgm_ops);
create index memories_embedding_hnsw on echo.memories using hnsw (embedding vector_cosine_ops);

create table echo.memory_evidence (
  user_id uuid not null references echo.profiles(user_id) on delete cascade,
  memory_id uuid not null references echo.memories(id) on delete cascade,
  utterance_id uuid not null references echo.utterances(id) on delete cascade,
  primary key (memory_id, utterance_id)
);
create index on echo.memory_evidence (utterance_id);

create table echo.memory_entities (
  user_id uuid not null references echo.profiles(user_id) on delete cascade,
  memory_id uuid not null references echo.memories(id) on delete cascade,
  entity_id uuid not null references echo.entities(id) on delete cascade,
  role text not null check (role in ('subject', 'counterparty', 'object', 'place', 'mention')),
  primary key (memory_id, entity_id, role)
);
create index on echo.memory_entities (entity_id);

create table echo.memory_links (
  user_id uuid not null references echo.profiles(user_id) on delete cascade,
  src_memory_id uuid not null references echo.memories(id) on delete cascade,
  dst_memory_id uuid not null references echo.memories(id) on delete cascade,
  kind text not null check (kind in ('same_topic', 'follow_up_of', 'contradicts', 'supersedes')),
  score real,
  created_at timestamptz not null default now(),
  primary key (src_memory_id, dst_memory_id, kind),
  check (src_memory_id <> dst_memory_id)
);
create index on echo.memory_links (dst_memory_id);

create table echo.commitments (
  memory_id uuid primary key references echo.memories(id) on delete cascade,
  user_id uuid not null references echo.profiles(user_id) on delete cascade,
  owner text not null check (owner in ('user', 'other')),
  owner_entity_id uuid references echo.entities(id) on delete set null,
  counterparty_entity_id uuid references echo.entities(id) on delete set null,
  action text not null,
  due_at timestamptz,
  status text not null default 'open' check (status in ('open', 'done', 'dismissed')),
  resolved_by_memory_id uuid references echo.memories(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index commitments_open on echo.commitments (user_id, due_at) where status = 'open';

create table echo.reminders (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references echo.profiles(user_id) on delete cascade,
  commitment_id uuid references echo.commitments(memory_id) on delete cascade,
  kind text not null default 'commitment' check (kind in ('commitment', 'digest')),
  title text not null,
  body text,
  fire_at timestamptz not null,
  status text not null default 'scheduled' check (status in ('scheduled', 'delivered', 'dismissed', 'cancelled')),
  sync_seq bigint generated always as identity,
  delivered_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index on echo.reminders (user_id, sync_seq);
create index reminders_due on echo.reminders (fire_at) where status = 'scheduled';

create table echo.digests (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references echo.profiles(user_id) on delete cascade,
  day date not null,
  content text not null,
  citations jsonb not null default '[]'::jsonb,
  tts_path text,
  created_at timestamptz not null default now(),
  unique (user_id, day)
);

create table echo.person_profiles (
  entity_id uuid primary key references echo.entities(id) on delete cascade,
  user_id uuid not null references echo.profiles(user_id) on delete cascade,
  summary text,
  facts jsonb not null default '[]'::jsonb,
  last_interaction_at timestamptz,
  interaction_count int not null default 0,
  open_commitments int not null default 0,
  refreshed_at timestamptz not null default now()
);
create index on echo.person_profiles (user_id, last_interaction_at desc);

create table echo.stt_jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references echo.profiles(user_id) on delete cascade,
  conversation_id uuid not null references echo.conversations(id) on delete cascade,
  provider text not null default 'sarvam',
  provider_job_id text unique,
  state text not null default 'created' check (state in ('created', 'submitted', 'running', 'completed', 'failed')),
  params jsonb not null default '{}'::jsonb,
  error text,
  submitted_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index stt_jobs_active on echo.stt_jobs (state, submitted_at) where state in ('submitted', 'running');

create table echo.processing_events (
  id bigint generated always as identity primary key,
  user_id uuid references echo.profiles(user_id) on delete cascade,
  subject_type text not null,
  subject_id uuid not null,
  stage text not null,
  stage_version int not null default 1,
  status text not null check (status in ('started', 'succeeded', 'skipped', 'failed')),
  attempt int not null default 1,
  duration_ms int,
  error text,
  meta jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index on echo.processing_events (subject_id, stage);
create index on echo.processing_events (created_at desc);

create table echo.cost_ledger (
  id bigint generated always as identity primary key,
  user_id uuid references echo.profiles(user_id) on delete set null,
  provider text not null check (provider in ('sarvam_stt', 'sarvam_stt_batch', 'sarvam_tts', 'azure_llm', 'azure_embed')),
  units numeric not null,
  unit_kind text not null check (unit_kind in ('audio_seconds', 'characters', 'input_tokens', 'output_tokens', 'tokens')),
  est_cost_inr numeric(12, 4),
  subject_id uuid,
  created_at timestamptz not null default now()
);
create index on echo.cost_ledger (created_at);
create index on echo.cost_ledger (user_id, created_at);

create table echo.usage_daily (
  user_id uuid not null references echo.profiles(user_id) on delete cascade,
  day date not null,
  speech_seconds int not null default 0,
  asks int not null default 0,
  est_cost_inr numeric(12, 4) not null default 0,
  primary key (user_id, day)
);

create table echo.ask_log (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references echo.profiles(user_id) on delete cascade,
  query_native text,
  query_en text,
  query_language text,
  answer_text text,
  citations jsonb not null default '[]'::jsonb,
  latency_ms int,
  feedback text check (feedback in ('up', 'down')),
  created_at timestamptz not null default now()
);
create index on echo.ask_log (user_id, created_at desc);

do $$
declare t text;
begin
  foreach t in array array[
    'profiles', 'user_settings', 'devices', 'entities', 'conversations', 'audio_segments',
    'memories', 'commitments', 'reminders', 'stt_jobs'] loop
    execute format('create trigger touch_updated_at before update on echo.%I
                    for each row execute function echo.touch_updated_at()', t);
  end loop;
end $$;
