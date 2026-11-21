import uuid

import httpx

from app.core.config import get_settings


async def create_test_user() -> tuple[str, str, str]:
    s = get_settings()
    email = f"echo-test-{uuid.uuid4().hex[:10]}@example.com"
    password = uuid.uuid4().hex + "Aa1!"
    h = {"apikey": s.supabase_service_role_key, "Authorization": f"Bearer {s.supabase_service_role_key}"}
    async with httpx.AsyncClient(base_url=s.supabase_url.rstrip("/") + "/auth/v1", timeout=30) as c:
        r = await c.post("/admin/users", headers=h, json={"email": email, "password": password, "email_confirm": True,
                                                         "user_metadata": {"echo_test": True}})
        r.raise_for_status()
        uid = r.json()["id"]
        r = await c.post("/token?grant_type=password", headers={"apikey": s.supabase_service_role_key},
                         json={"email": email, "password": password})
        r.raise_for_status()
        return uid, r.json()["access_token"], email


async def delete_test_user(uid: str) -> None:
    s = get_settings()
    h = {"apikey": s.supabase_service_role_key, "Authorization": f"Bearer {s.supabase_service_role_key}"}
    async with httpx.AsyncClient(base_url=s.supabase_url.rstrip("/") + "/auth/v1", timeout=30) as c:
        await c.delete(f"/admin/users/{uid}", headers=h)
