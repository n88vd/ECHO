alter table echo.audio_segments add column if not exists speech_path text;
alter table echo.audio_segments add column if not exists speech_map jsonb;
alter table echo.audio_segments add column if not exists qa_reason text;
alter table echo.conversations add column if not exists last_activity_at timestamptz not null default now();
alter table echo.speakers add column if not exists source text not null default 'cluster';
alter table echo.speakers alter column label set data type text;
alter table echo.utterances add column if not exists batch_speaker text;
create index if not exists utterances_segment on echo.utterances (segment_id);

create or replace function echo.close_stale_conversations(idle interval default interval '3 minutes')
returns int
language plpgsql
security definer
set search_path = echo, pg_temp
as $$
declare
  r record;
  n int := 0;
begin
  for r in
    update echo.conversations c
       set status = 'closed', ended_at = c.last_segment_at,
           close_reason = case when c.pinned then 'pinned_idle' else 'idle' end
     where c.status = 'open'
       and (c.last_activity_at < now() - idle
            or (c.pinned and c.last_activity_at < now() - interval '60 seconds'))
       and not exists (
         select 1 from echo.audio_segments s
          where s.conversation_id = c.id and s.status in ('received', 'audio_ok', 'failed_retryable'))
    returning c.id, c.user_id
  loop
    perform pgmq.send('echo_understand', jsonb_build_object('conversation_id', r.id, 'user_id', r.user_id));
    n := n + 1;
  end loop;
  return n;
end $$;
revoke all on function echo.close_stale_conversations(interval) from public;
grant execute on function echo.close_stale_conversations(interval) to echo_service;
