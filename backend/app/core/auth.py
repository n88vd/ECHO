import hashlib
import time
from dataclasses import dataclass

import httpx
import jwt
from fastapi import Depends, HTTPException, Request

from app.core.config import get_settings
from app.core.db import pool


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str | None


_cache: dict[str, tuple[CurrentUser, float]] = {}
_known_profiles: set[str] = set()
_http = httpx.AsyncClient(timeout=10)


async def _verify_remote(token: str) -> CurrentUser:
    s = get_settings()
    r = await _http.get(
        s.supabase_url.rstrip("/") + "/auth/v1/user",
        headers={"apikey": s.supabase_service_role_key, "Authorization": f"Bearer {token}"},
    )
    if r.status_code != 200:
        raise HTTPException(401, "invalid token")
    data = r.json()
    return CurrentUser(id=data["id"], email=data.get("email"))


async def verify_token(token: str) -> CurrentUser:
    s = get_settings()
    if s.supabase_jwt_secret:
        try:
            claims = jwt.decode(token, s.supabase_jwt_secret, algorithms=["HS256"], audience="authenticated")
        except jwt.PyJWTError as e:
            raise HTTPException(401, "invalid token") from e
        return CurrentUser(id=claims["sub"], email=claims.get("email"))

    key = hashlib.sha256(token.encode()).hexdigest()
    now = time.time()
    hit = _cache.get(key)
    if hit and hit[1] > now:
        return hit[0]
    try:
        exp = float(jwt.decode(token, options={"verify_signature": False}).get("exp", now + 300))
    except jwt.PyJWTError as e:
        raise HTTPException(401, "malformed token") from e
    if exp <= now:
        raise HTTPException(401, "token expired")
    user = await _verify_remote(token)
    if len(_cache) > 10_000:
        _cache.clear()
    _cache[key] = (user, min(exp, now + 300))
    return user


async def ensure_profile(user: CurrentUser) -> None:
    if user.id in _known_profiles:
        return
    async with pool().acquire() as conn, conn.transaction():
        await conn.execute(
            "insert into echo.profiles(user_id, display_name) values ($1, $2) on conflict do nothing",
            user.id,
            (user.email or "").split("@")[0] or None,
        )
        await conn.execute("insert into echo.user_settings(user_id) values ($1) on conflict do nothing", user.id)
    _known_profiles.add(user.id)


async def current_user(request: Request) -> CurrentUser:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    user = await verify_token(header[7:].strip())
    await ensure_profile(user)
    request.state.user_id = user.id
    return user


CurrentUserDep = Depends(current_user)
