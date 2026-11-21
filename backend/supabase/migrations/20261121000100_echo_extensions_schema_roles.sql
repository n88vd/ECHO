create extension if not exists vector with schema extensions;
create extension if not exists pg_trgm with schema extensions;
create extension if not exists pgmq;
create extension if not exists pg_cron;

create schema if not exists echo;

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'echo_service') then
    create role echo_service login noinherit;
  end if;
end $$;

grant authenticated to echo_service;

revoke all on schema echo from public, anon;
grant usage on schema echo to authenticated, echo_service;
grant usage on schema extensions to echo_service;

alter default privileges in schema echo revoke all on tables from public, anon;
alter default privileges in schema echo grant select, insert, update, delete on tables to echo_service;
alter default privileges in schema echo grant usage, select on sequences to echo_service;
alter default privileges in schema echo grant execute on functions to echo_service;

create or replace function echo.touch_updated_at() returns trigger
language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end $$;
