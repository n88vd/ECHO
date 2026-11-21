do $$
declare q text;
begin
  foreach q in array array[
    'echo_audio_qa', 'echo_stt_fast', 'echo_stt_batch_submit', 'echo_stt_batch_collect',
    'echo_understand', 'echo_entity_resolve', 'echo_embed', 'echo_proactive', 'echo_purge'] loop
    if not exists (select 1 from pgmq.list_queues() where queue_name = q) then
      perform pgmq.create(q);
    end if;
    execute format('grant select, insert, update, delete on pgmq.%I, pgmq.%I to echo_service', 'q_' || q, 'a_' || q);
  end loop;
end $$;

grant usage on schema pgmq to echo_service;
grant usage, select on all sequences in schema pgmq to echo_service;
grant execute on all functions in schema pgmq to echo_service;

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
    update echo.conversations
       set status = 'closed', ended_at = last_segment_at
     where status = 'open' and last_segment_at < now() - idle
    returning id, user_id
  loop
    perform pgmq.send('echo_understand', jsonb_build_object('conversation_id', r.id, 'user_id', r.user_id));
    n := n + 1;
  end loop;
  return n;
end $$;
revoke all on function echo.close_stale_conversations(interval) from public;
grant execute on function echo.close_stale_conversations(interval) to echo_service;

select cron.unschedule(jobid) from cron.job where jobname = 'echo_close_stale_conversations';
select cron.schedule('echo_close_stale_conversations', '* * * * *', $$select echo.close_stale_conversations()$$);

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('echo-audio', 'echo-audio', false, 5242880,
        array['audio/ogg', 'audio/opus', 'audio/webm', 'audio/wav', 'audio/x-wav'])
on conflict (id) do update
  set public = excluded.public,
      file_size_limit = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;

create policy echo_audio_owner_insert on storage.objects for insert to authenticated
  with check (bucket_id = 'echo-audio' and (storage.foldername(name))[1] = auth.uid()::text);
create policy echo_audio_owner_select on storage.objects for select to authenticated
  using (bucket_id = 'echo-audio' and (storage.foldername(name))[1] = auth.uid()::text);
create policy echo_audio_owner_delete on storage.objects for delete to authenticated
  using (bucket_id = 'echo-audio' and (storage.foldername(name))[1] = auth.uid()::text);
