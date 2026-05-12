from typing import Literal, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str

    # Storage
    storage_backend: Literal["local", "r2"] = "local"
    storage_local_path: str = "/storage"
    r2_account_id: Optional[str] = None
    r2_access_key_id: Optional[str] = None
    r2_secret_access_key: Optional[str] = None
    r2_bucket: Optional[str] = None

    # Google Cloud Vision (OCR)
    # Set GOOGLE_CLOUD_CREDENTIALS_JSON to service account JSON string, or
    # set GOOGLE_APPLICATION_CREDENTIALS to a file path (standard GCP ADC).
    google_cloud_credentials_json: Optional[str] = None

    # Gemini (Vision LLM + semantic pick + escalation + segmentation)
    google_api_key: Optional[str] = None
    gemini_flash_lite_model: str = "gemini-2.5-flash-lite"
    gemini_pro_model: str = "gemini-2.5-pro"

    # Google Drive (service account)
    gdrive_service_account_json: Optional[str] = None

    # Worker tuning
    worker_concurrency: int = 15
    worker_poll_interval_seconds: int = 2

    # Limits
    max_files_per_job: int = 200
    max_file_size_mb: int = 20
    max_total_upload_mb: int = 500

    # Logging
    log_level: str = "INFO"


settings = Settings()
