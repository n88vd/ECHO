#!/usr/bin/env bash
# Deploy ECHO backend to the VPS: sync code, build image, run migrations, restart with health gate + rollback.
set -euo pipefail
HOST="${ECHO_HOST:-root@72.60.99.53}"
DIR=/opt/echo
cd "$(dirname "$0")/.."
TAG=$(date +%Y%m%d-%H%M%S)

rsync -az --delete --exclude .venv --exclude .env --exclude '.env.*' --exclude models --exclude .ruff_cache \
  --exclude .pytest_cache --exclude __pycache__ --exclude tests/fixtures ./ "$HOST:$DIR/"
if [[ "${SYNC_ENV:-0}" == "1" ]]; then
  scp -q .env "$HOST:$DIR/.env"
  ssh "$HOST" "chmod 600 $DIR/.env"
fi

ssh "$HOST" bash -s <<EOF
set -euo pipefail
cd $DIR
PREV=\$(docker image inspect echo-backend:current --format '{{.Id}}' 2>/dev/null || true)
ECHO_TAG=$TAG docker compose build --pull -q
docker tag echo-backend:$TAG echo-backend:current
ECHO_TAG=$TAG docker compose up -d --remove-orphans
for i in \$(seq 1 30); do
  if curl -fsS http://127.0.0.1:8070/readyz >/dev/null; then echo "healthy: $TAG"; exit 0; fi
  sleep 2
done
echo "health check failed, rolling back" >&2
if [[ -n "\$PREV" ]]; then docker tag "\$PREV" echo-backend:rollback && ECHO_TAG=rollback docker compose up -d; fi
exit 1
EOF
