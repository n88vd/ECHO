#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
: "${DATABASE_URL:?DATABASE_URL missing in backend/.env}"

PSQL=(psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -X -q)

"${PSQL[@]}" -c "create schema if not exists echo;
create table if not exists echo.schema_migrations (
  version text primary key,
  applied_at timestamptz not null default now()
);
revoke all on echo.schema_migrations from public;"

for f in supabase/migrations/*.sql; do
  v=$(basename "$f" .sql)
  applied=$("${PSQL[@]}" -tA -c "select 1 from echo.schema_migrations where version = '$v'")
  if [[ "$applied" == "1" ]]; then
    echo "skip   $v"
    continue
  fi
  echo "apply  $v"
  { cat "$f"; echo; echo "insert into echo.schema_migrations(version) values ('$v');"; } \
    | "${PSQL[@]}" --single-transaction -f -
done
echo "done"
