from datetime import datetime, time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class SegmentMeta(BaseModel):
    segment_id: UUID
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    duration_ms: int = Field(gt=0, le=60000)
    started_at: datetime
    source: Literal["phone", "bt_sco", "bt_le", "wired"] = "phone"
    sample_rate: int = 16000
    speech_ratio: float | None = None
    session_hint: UUID | None = None
    pinned: bool = False
    device_id: UUID | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    accuracy_m: float | None = None
    locality: str | None = Field(default=None, max_length=200)
    content_type: Literal["audio/ogg", "audio/wav"] = "audio/ogg"


class DeviceIn(BaseModel):
    device_id: UUID | None = None
    model: str | None = None
    os_version: str | None = None
    app_version: str | None = None


class RememberIn(BaseModel):
    at: datetime | None = None
    before_s: int = Field(default=30, ge=0, le=300)
    after_s: int = Field(default=60, ge=0, le=600)


class AskIn(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    language: str | None = None
    speak: bool = False


class FeedbackIn(BaseModel):
    feedback: Literal["up", "down"]


class MemoryPatch(BaseModel):
    content_en: str | None = Field(default=None, min_length=1, max_length=2000)
    importance: float | None = Field(default=None, ge=0, le=1)
    pinned: bool | None = None


class SpeakerLabelIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    is_me: bool = False


class CommitmentPatch(BaseModel):
    status: Literal["open", "done", "dismissed"]


class SettingsPatch(BaseModel):
    audio_retention_days: int | None = Field(default=None, ge=0, le=3650)
    retention_forever: bool | None = None
    quiet_hours: list[str | dict] | None = None
    earbud_policy: Literal["never", "when_no_media", "always"] | None = None
    location_enabled: bool | None = None
    daily_digest_time: time | None = None
    speech_cap_min_per_day: int | None = Field(default=None, ge=10, le=1440)
    display_name: str | None = Field(default=None, max_length=80)
    timezone: str | None = None
    answer_language: str | None = None
