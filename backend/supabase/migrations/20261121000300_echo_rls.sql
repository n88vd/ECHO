do $$
declare t text;
begin
  for t in select tablename from pg_tables where schemaname = 'echo' and tablename <> 'schema_migrations' loop
    execute format('alter table echo.%I enable row level security', t);
    execute format('create policy echo_service_all on echo.%I for all to echo_service using (true) with check (true)', t);
    execute format('create policy echo_owner_select on echo.%I for select to authenticated using (user_id = auth.uid())', t);
    execute format('grant select on echo.%I to authenticated', t);
  end loop;
end $$;

do $$
declare t text;
begin
  foreach t in array array['profiles', 'user_settings', 'memories', 'commitments', 'reminders', 'speakers', 'entities', 'ask_log'] loop
    execute format('create policy echo_owner_update on echo.%I for update to authenticated
                    using (user_id = auth.uid()) with check (user_id = auth.uid())', t);
    execute format('grant update on echo.%I to authenticated', t);
  end loop;
  foreach t in array array['memories', 'conversations', 'entities'] loop
    execute format('create policy echo_owner_delete on echo.%I for delete to authenticated using (user_id = auth.uid())', t);
    execute format('grant delete on echo.%I to authenticated', t);
  end loop;
end $$;

grant select, insert, update, delete on all tables in schema echo to echo_service;
grant usage, select on all sequences in schema echo to echo_service;
grant execute on all functions in schema echo to echo_service;
