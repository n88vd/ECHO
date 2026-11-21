"""Auth proxy: the app exchanges a Google ID token (Credential Manager) for a Supabase session via the backend."""

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.config import get_settings

router = APIRouter(prefix="/v1/auth", tags=["auth"])
_http = httpx.AsyncClient(timeout=20)


class GoogleIn(BaseModel):
    id_token: str = Field(min_length=20)
    nonce: str | None = None


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=8)


class PasswordIn(BaseModel):
    email: str
    password: str


async def _token(grant: str, body: dict) -> dict:
    s = get_settings()
    r = await _http.post(
        f"{s.supabase_url.rstrip('/')}/auth/v1/token?grant_type={grant}",
        headers={"apikey": s.supabase_service_role_key, "Content-Type": "application/json"},
        json=body,
    )
    if r.status_code >= 400:
        detail = r.json().get("error_description") or r.json().get("msg") or "authentication failed"
        raise HTTPException(401, detail)
    d = r.json()
    return {
        "access_token": d["access_token"],
        "refresh_token": d["refresh_token"],
        "expires_at": d.get("expires_at"),
        "expires_in": d.get("expires_in"),
        "user": {"id": d["user"]["id"], "email": d["user"].get("email"),
                 "name": (d["user"].get("user_metadata") or {}).get("full_name")},
    }


@router.post("/google")
async def google(body: GoogleIn):
    payload = {"provider": "google", "id_token": body.id_token}
    if body.nonce:
        payload["nonce"] = body.nonce
    return await _token("id_token", payload)


@router.post("/refresh")
async def refresh(body: RefreshIn):
    return await _token("refresh_token", {"refresh_token": body.refresh_token})


@router.post("/password")
async def password(body: PasswordIn):
    if not get_settings().allow_password_login:
        raise HTTPException(404, "not found")
    return await _token("password", {"email": body.email, "password": body.password})
