import httpx

from app.core.config import get_settings


class Storage:
    def __init__(self) -> None:
        s = get_settings()
        self.base = s.supabase_url.rstrip("/") + "/storage/v1"
        self.bucket = s.audio_bucket
        key = s.supabase_service_role_key
        self.client = httpx.AsyncClient(
            headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=httpx.Timeout(60, connect=10)
        )

    async def signed_upload_url(self, path: str) -> str:
        r = await self.client.post(f"{self.base}/object/upload/sign/{self.bucket}/{path}", headers={"x-upsert": "true"})
        r.raise_for_status()
        return self.base + r.json()["url"]

    async def signed_download_url(self, path: str, expires_s: int = 900) -> str:
        r = await self.client.post(f"{self.base}/object/sign/{self.bucket}/{path}", json={"expiresIn": expires_s})
        r.raise_for_status()
        return self.base + r.json()["signedURL"]

    async def upload(self, path: str, data: bytes, content_type: str) -> None:
        r = await self.client.post(
            f"{self.base}/object/{self.bucket}/{path}",
            content=data,
            headers={"Content-Type": content_type, "x-upsert": "true"},
        )
        r.raise_for_status()

    async def download(self, path: str) -> bytes:
        r = await self.client.get(f"{self.base}/object/{self.bucket}/{path}")
        r.raise_for_status()
        return r.content

    async def info(self, path: str) -> dict | None:
        r = await self.client.get(f"{self.base}/object/info/{self.bucket}/{path}")
        if r.status_code in (400, 404):
            return None
        r.raise_for_status()
        return r.json()

    async def delete(self, paths: list[str]) -> None:
        for i in range(0, len(paths), 500):
            r = await self.client.request(
                "DELETE", f"{self.base}/object/{self.bucket}", json={"prefixes": paths[i : i + 500]}
            )
            r.raise_for_status()

    async def list_prefix(self, prefix: str) -> list[str]:
        out: list[str] = []
        stack = [prefix.rstrip("/")]
        while stack:
            p = stack.pop()
            offset = 0
            while True:
                r = await self.client.post(
                    f"{self.base}/object/list/{self.bucket}",
                    json={"prefix": p + "/", "limit": 1000, "offset": offset},
                )
                r.raise_for_status()
                items = r.json()
                for it in items:
                    full = f"{p}/{it['name']}"
                    (out.append(full) if it.get("id") else stack.append(full))
                if len(items) < 1000:
                    break
                offset += 1000
        return out


_storage: Storage | None = None


def storage() -> Storage:
    global _storage
    if _storage is None:
        _storage = Storage()
    return _storage
