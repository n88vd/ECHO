alter table echo.voiceprints alter column embedding type extensions.vector(512) using null;
alter table echo.voice_profiles alter column embedding type extensions.vector(512) using null;
alter table echo.speakers alter column embedding type extensions.vector(512) using null;
alter table echo.utterances add column if not exists speaker_embedding extensions.vector(512);
alter table echo.conversations add column if not exists close_reason text;
alter table echo.conversations add column if not exists batch_requested boolean not null default false;
alter table echo.memories add column if not exists evidence_quote text;

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
       and (c.last_segment_at < now() - idle
            or (c.pinned and c.last_segment_at < now() - interval '60 seconds'))
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
