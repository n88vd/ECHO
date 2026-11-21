# ECHO — agent notes

## Layout
- `backend/` FastAPI API + asyncio worker (Python 3.12, uv). Supabase Postgres (`echo` schema), pgvector, pgmq, pg_cron.
- `android/` Kotlin + Jetpack Compose app (minSdk 29, AGP 9.5.1, Gradle 9.9.1, Kotlin 2.4.21).
- `docs/ARCHITECTURE.md` design + decision log.

## Backend commands (run in `backend/`)
- Install: `uv sync` (models: see Dockerfile; local copies live in `backend/models/`, gitignored)
- Lint: `uv run ruff check app tests`
- Unit tests (no network): `uv run pytest -q`
- E2E on real Supabase with fake AI: `ECHO_DB_TESTS=1 uv run pytest tests/test_e2e_db.py -q`
- Live E2E (spends Sarvam/Azure credits): `ECHO_LIVE_TESTS=1 PROVIDERS=live uv run pytest tests/test_live.py -s`
- Run locally: `PROVIDERS=live uv run uvicorn app.main:app --port 8000` and `PROVIDERS=live uv run python -m app.workers.runtime`
  (stop any local worker while production runs — both consume the same pgmq queues)
- Migrations: `./scripts/db_migrate.sh` (uses `DATABASE_URL` = postgres role, session pooler aws-1-ap-south-1)
- Deploy: `./deploy/deploy.sh` (add `SYNC_ENV=1` to push `.env`). VPS: root@72.60.99.53, `/opt/echo`, port 127.0.0.1:8070,
  host nginx site `echo.nmrlabs.space` (certbot). Health: `https://echo.nmrlabs.space/readyz`.

## Android commands (run in `android/`, JAVA_HOME = Android Studio JBR)
- The wrapper download is blocked on this Mac; use `~/.gradle/dists/gradle-9.9.1/bin/gradle` locally (`./gradlew` in CI).
- Debug build against prod: `gradle assembleDebug`; against local API on a USB phone: `gradle assembleDebug -PECHO_DEBUG_API_BASE_URL=http://localhost:8000` + `adb reverse tcp:8000 tcp:8000`
- Release: `gradle bundleRelease` with `ECHO_KEYSTORE`, `ECHO_KEYSTORE_PASSWORD`, `ECHO_KEY_ALIAS`, `ECHO_KEY_PASSWORD`, `ECHO_GOOGLE_WEB_CLIENT_ID` in `local.properties`.

## Gotchas
- pgmq 1.5 has overloaded functions: always cast args (`pgmq.send($1::text, $2::jsonb, $3::integer)`).
- asyncpg `RESET ALL` on release wipes `search_path`; the pool `setup` hook re-sets it on every checkout.
- Android MediaMuxer OGG/Opus is rejected by libsndfile; `app/audio/decode.py` falls back to PyAV.
- Sarvam keyterms must not contain commas.
- Supabase project is shared with another app: never touch non-`echo` schemas; `DELETE /v1/account` keeps the auth identity.
