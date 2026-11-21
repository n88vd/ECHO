import hashlib

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.api.deps import CurrentUser, CurrentUserDep
from app.api.schemas import AskIn, FeedbackIn
from app.core import costs
from app.core.db import pool
from app.core.storage import storage
from app.providers import stt, tts
from app.retrieval.ask import CITE, answer

router = APIRouter(prefix="/v1", tags=["ask"])


async def _speak(user_id: str, text: str, language: str) -> str | None:
    spoken = CITE.sub("", text).strip()
    if not spoken:
        return None
    est = costs.estimate_inr("sarvam_tts", len(spoken), "characters")
    if not await costs.sarvam_budget_ok(est):
        return None
    key = hashlib.sha256(f"{language}|{spoken}".encode()).hexdigest()[:32]
    path = f"{user_id}/tts/{key}.mp3"
    if await storage().info(path) is None:
        audio, ctype = await tts().synthesize(spoken, language)
        await costs.record("sarvam_tts", len(spoken), "characters", user_id)
        await storage().upload(path, audio, ctype)
    return await storage().signed_download_url(path, 3600)


async def _ask(user_id: str, query: str, language: str | None, speak: bool) -> dict:
    if not await costs.ask_cap_ok(user_id):
        raise HTTPException(429, "daily ask limit reached")
    res = await answer(user_id, query, language)
    res["tts_url"] = await _speak(user_id, res["answer"], res["answer_language"]) if speak else None
    return res


@router.post("/ask")
async def ask(body: AskIn, user: CurrentUser = CurrentUserDep):
    return await _ask(user.id, body.query, body.language, body.speak)


@router.post("/ask/voice")
async def ask_voice(file: UploadFile = File(...), speak: bool = Form(True), user: CurrentUser = CurrentUserDep):
    data = await file.read(5 * 1024 * 1024 + 1)
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, "audio too large")
    if not await costs.sarvam_budget_ok():
        raise HTTPException(503, "voice temporarily unavailable (budget)")
    res = await stt().transcribe(data, file.filename or "question.ogg", "unknown", None)
    await costs.record("sarvam_stt", max(1, len(data) // 4000), "audio_seconds", user.id)
    query = res.transcript.strip()
    if not query:
        raise HTTPException(422, "could not understand the question")
    out = await _ask(user.id, query, res.language_code, speak)
    out["transcript"] = query
    return out


@router.post("/ask/{ask_id}/feedback")
async def feedback(ask_id: str, body: FeedbackIn, user: CurrentUser = CurrentUserDep):
    await pool().execute("update echo.ask_log set feedback = $3 where id = $1 and user_id = $2", ask_id, user.id, body.feedback)
    return {"ok": True}
