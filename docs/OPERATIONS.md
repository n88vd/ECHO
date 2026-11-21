# ECHO — the external memory for humanity

> This document is written in ASD-STE100 Simplified Technical English.
> Sentences are short. Each procedure step gives one instruction.

## 1. Description

ECHO is a personal memory system. It has two parts:

- An Android app. The app records speech through the phone microphone or the earbud microphone. The user must give permission first.
- A server. The server changes the speech into text. Then it makes memories from the text.

You can ask ECHO a question by voice or by text. ECHO finds the related memories. Then it gives an answer and shows the source of each fact.

ECHO operates with English and 22 Indian languages.

## 2. Main data

| Item | Value |
|---|---|
| Production API | https://echo.nmrlabs.space (VPS, Mumbai) |
| Health check | https://echo.nmrlabs.space/readyz |
| Database | Supabase Postgres, schema `echo` (Mumbai) |
| Speech to text | Sarvam `saaras:v4` (REST and Batch with speaker separation) |
| Text to speech | Sarvam `bulbul:v3` |
| Language models | Azure AI Foundry `gpt-6.1-sol` and `gpt-5.4-mini` |
| Embeddings | `text-embedding-3-large`, 1536 dimensions |
| Typeface | Overused Grotesk v0.5-alpha.2 by RandomMaerks (SIL OFL 1.1) |
| Android package | `space.nmrlabs.echo` (debug: `space.nmrlabs.echo.debug`) |

Refer to [docs/ARCHITECTURE.md](ARCHITECTURE.md) for the design and the decision log.
Refer to [AGENTS.md](../AGENTS.md) for the commands and the known problems.

## 3. Repository layout

| Directory | Contents |
|---|---|
| `backend/` | FastAPI API and asyncio worker. Python 3.12, `uv`. |
| `backend/supabase/migrations/` | Database migrations for the `echo` schema. |
| `backend/deploy/` | Deploy script and nginx configuration. |
| `android/` | Kotlin and Jetpack Compose app. minSdk 29. |
| `docs/` | Architecture document. |
| `UI Inspiration/` | Design reference images. |
| `.github/workflows/` | CI. CI does a lint, the unit tests and a debug build. |

## 4. How the system operates

### 4.1 Capture and memory

1. The phone finds speech with a voice activity detector (Silero). The phone does not send silence.
2. The phone encodes the speech as Opus. It keeps each clip in an outbox until the upload is complete.
3. The server examines the audio. It rejects blank audio, noise and hum.
4. The server joins related clips into one conversation. It removes the parts that have no speech.
5. Sarvam changes the speech into text. The server finds the language automatically.
6. The server examines the text. It removes passwords and other credentials.
7. The server identifies the speakers by their voiceprints.
8. A language model makes memories from the text. The server makes sure that each memory agrees with the text.
9. The server links people, places and things. It replaces old facts with new facts.
10. The server makes embeddings, reminders, digests and people profiles.

### 4.2 Ask ECHO

1. The server reads the question.
2. The server does five searches: two vector searches, one full-text search, one trigram search and one entity graph search.
3. The server combines the results and puts them in order.
4. A language model selects the best results.
5. The language model writes an answer. Each fact in the answer has a source.
6. The server makes sure that each source supports its fact.
7. Sarvam changes the answer into speech.

If ECHO has no related memory, it says: "I don't have a memory of that".

## 5. Backend procedures

Do these procedures in the `backend/` directory.

### 5.1 Install

1. Install `uv`.
2. Run `uv sync`.
3. Copy `.env.example` to `.env`. Then write your values in `.env`.
4. Download the two models into `backend/models/`. Refer to the `Dockerfile` for the URLs and the SHA-256 values.

> CAUTION: Do not commit the `.env` file. It contains secret keys.

### 5.2 Test

1. Do the lint check: `uv run ruff check app tests`
2. Do the unit tests. These tests do not use the network: `uv run pytest -q`
3. Do the database test with fake AI: `ECHO_DB_TESTS=1 uv run pytest tests/test_e2e_db.py -q`
4. Do the live test only when necessary: `ECHO_LIVE_TESTS=1 PROVIDERS=live uv run pytest tests/test_live.py -s`

> CAUTION: The live test uses Sarvam and Azure credits.

### 5.3 Run on your computer

1. Start the API: `PROVIDERS=live uv run uvicorn app.main:app --port 8000`
2. Start the worker: `PROVIDERS=live uv run python -m app.workers.runtime`

> CAUTION: The local worker and the production worker use the same queues. Stop the local worker when you do not use it.

### 5.4 Apply database migrations

1. Set `DATABASE_URL` to the `postgres` role connection (session pooler, `aws-1-ap-south-1`).
2. Run `./scripts/db_migrate.sh`.

> WARNING: The Supabase project is shared with a different app. Do not change schemas other than `echo`.

### 5.5 Deploy

1. Run `./deploy/deploy.sh`.
2. To send the `.env` file to the server also, run `SYNC_ENV=1 ./deploy/deploy.sh`.
3. Make sure that https://echo.nmrlabs.space/readyz gives a good result.

The server is `root@72.60.99.53`, directory `/opt/echo`. The containers listen on `127.0.0.1:8070`. The host nginx site is `echo.nmrlabs.space`. Certbot supplies the TLS certificate.

## 6. Android procedures

Do these procedures in the `android/` directory. Set `JAVA_HOME` to the Android Studio JBR.

On the development Mac, the Gradle wrapper cannot download Gradle. Use `~/.gradle/dists/gradle-9.9.1/bin/gradle` there. CI uses `./gradlew`.

### 6.1 Make a debug build

- For the production API: `gradle assembleDebug`
- For a local API on a USB phone:
  1. Run `gradle assembleDebug -PECHO_DEBUG_API_BASE_URL=http://localhost:8000`.
  2. Run `adb reverse tcp:8000 tcp:8000`.

### 6.2 Make a release build

1. Write these properties in `local.properties`: `ECHO_KEYSTORE`, `ECHO_KEYSTORE_PASSWORD`, `ECHO_KEY_ALIAS`, `ECHO_KEY_PASSWORD`, `ECHO_GOOGLE_WEB_CLIENT_ID`.
2. Run `gradle bundleRelease`.

> CAUTION: Do not commit `local.properties` or the keystore file.

## 7. Launch checklist

The owner must do these tasks before the Play Store launch.

1. **Google sign-in.**
   1. In Google Cloud, make an OAuth *Web* client.
   2. Write its ID and secret in Supabase → Auth → Google. Also write the ID in "Client IDs".
   3. Make an OAuth *Android* client for package `space.nmrlabs.echo`. Use the SHA-1 of the release key.
   4. Write the Web client ID in `android/local.properties` as `ECHO_GOOGLE_WEB_CLIENT_ID`.
2. **Release key.**
   1. Make an upload keystore: `keytool -genkeypair -v -keystore echo-upload.jks -alias echo -keyalg RSA -keysize 4096 -validity 10000`
   2. Set the `ECHO_KEYSTORE*` properties.
   3. Run `gradle bundleRelease`.
3. **Play Console.**
   1. Supply a privacy policy URL.
   2. Complete the Data safety form: audio, approximate and precise location, email. Data is encrypted in transit. Users can delete their data.
   3. Declare the foreground service for *microphone* and *location*. Supply a demo video.
   4. Supply the demo account for the review.
4. **Supabase.** The shared project "Microservice" is on Nano compute and shows *Unhealthy*. Upgrade it to Micro or Small.
5. **Budget.** Sarvam is pay-as-you-go. The daily limit is `SARVAM_DAILY_BUDGET_INR` (default ₹150). Per-user limits are in the `user_settings` table.

## 8. Important notes

- Password login is enabled on the server (`ALLOW_PASSWORD_LOGIN=true`). There is no sign-up. Only accounts that an administrator makes can use it. It is for the demo account and the Play review.
- `DELETE /v1/account` deletes the ECHO data. It keeps the Supabase auth identity, because the project is shared.
- The api and worker use a database role with limited permissions. They do not use the `postgres` role.
- An answer from Ask ECHO takes approximately 8 seconds. Most of this time is three calls to Azure (US East). An Azure region in India or a streamed answer can decrease this time.
