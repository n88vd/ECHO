#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
: "${DATABASE_URL:?DATABASE_URL missing in backend/.env}"

PW=$(openssl rand -hex 32)
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -X -q -v pw="$PW" <<'SQL'
alter role echo_service with password :'pw';
SQL

URL=$(python3 - "$DATABASE_URL" "$PW" <<'PY'
import sys
from urllib.parse import urlsplit, urlunsplit
u = urlsplit(sys.argv[1])
user = u.username or ""
ref = user.split(".", 1)[1] if "." in user else ""
new_user = f"echo_service.{ref}" if ref else "echo_service"
netloc = f"{new_user}:{sys.argv[2]}@{u.hostname}:{u.port or 5432}"
print(urlunsplit((u.scheme, netloc, u.path, u.query, u.fragment)))
PY
)
python3 - "$URL" <<'PY'
import re, sys, pathlib
p = pathlib.Path(".env"); s = p.read_text()
line = f"ECHO_DATABASE_URL={sys.argv[1]}"
s = re.sub(r"^ECHO_DATABASE_URL=.*$", lambda _: line, s, flags=re.M) if re.search(r"^ECHO_DATABASE_URL=", s, re.M) else s + "\n" + line + "\n"
p.write_text(s)
PY
psql "$URL" -X -q -tA -c "select 'connected as ' || current_user" 
