from functools import lru_cache
import os
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    app_name: str = "eng-learn"
    data_dir: Path = Path("data")
    db_url: str = "sqlite:///data/eng_learn.db"

    media_dir: Path = Path("data/media")
    subtitles_dir: Path = Path("data/subtitles")
    backups_dir: Path = Path("data/backups")
    models_dir: Path = Path("data/models")

    store_attempt_audio: bool = Field(default=False)

    stt_provider: str = "local_whisper"
    default_transcript_mode: str = "strict_whisper"
    local_whisper_model: str = "small"
    local_whisper_device: str = "auto"
    local_whisper_compute_type: str = "int8"
    local_whisper_language: str = "en"
    local_whisper_beam_size: int = 5

    whisper_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("WHISPER_API_KEY", "OPENAI_API_KEY"),
    )
    whisper_base_url: str = "https://api.openai.com/v1"
    whisper_model: str = "whisper-1"

    llm_api_key: str | None = None
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"


@lru_cache
def get_settings() -> Settings:
    disable_dotenv = os.getenv("DISABLE_DOTENV", "").strip().lower() in {"1", "true", "yes"}
    settings = Settings(_env_file=None) if disable_dotenv else Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    settings.subtitles_dir.mkdir(parents=True, exist_ok=True)
    settings.backups_dir.mkdir(parents=True, exist_ok=True)
    settings.models_dir.mkdir(parents=True, exist_ok=True)
    return settings
