from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    echo_database_url: str
    db_pool_min: int = 1
    db_pool_max: int = 5
    db_statement_cache: int = 256

    supabase_url: str
    supabase_service_role_key: str
    supabase_jwt_secret: str | None = None
    audio_bucket: str = "echo-audio"

    providers: Literal["fake", "live"] = "fake"
    azure_openai_base_url: str = ""
    azure_openai_api_key: str = ""
    llm_deployment_reasoning: str = "gpt-6.1-sol"
    llm_deployment_fast: str = "gpt-5.4-mini"
    llm_fast_reasoning_effort: str = "minimal"
    llm_reasoning_effort: str = "low"
    embedding_deployment: str = "text-embedding-3-large"
    embedding_dimensions: int = 1536

    sarvam_api_key: str = ""
    sarvam_base_url: str = "https://api.sarvam.ai"
    sarvam_stt_model: str = "saaras:v4"
    sarvam_tts_model: str = "bulbul:v3"
    sarvam_tts_speaker: str = "shubh"
    sarvam_callback_token: str = ""

    public_base_url: str = "http://localhost:8000"
    allow_password_login: bool = False

    stt_mode: Literal["budget", "quality"] = "budget"
    sarvam_daily_budget_inr: float = 150.0
    sarvam_stt_inr_per_hour: float = 30.0
    sarvam_stt_batch_inr_per_hour: float = 45.0
    sarvam_tts_inr_per_10k_chars: float = 15.0
    azure_llm_inr_per_1k_tokens: float = 0.5
    azure_embed_inr_per_1k_tokens: float = 0.011

    conversation_gap_s: int = 90
    min_speech_ms: int = 400
    min_speech_ratio: float = 0.15
    min_rms_dbfs: float = -55.0
    lang_prob_retry_below: float = 0.5

    vad_model_path: str = str(BASE_DIR / "models" / "silero_vad.onnx")
    speaker_model_path: str = str(BASE_DIR / "models" / "campplus_en_voxceleb.onnx")
    voiceprint_threshold: float = 0.55
    person_voice_threshold: float = 0.62
    speaker_cluster_threshold: float = 0.5

    worker_concurrency: int = 2
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
