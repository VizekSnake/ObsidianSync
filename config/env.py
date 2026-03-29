from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    secret_key: str = Field(alias="DJANGO_SECRET_KEY")
    debug: bool = Field(default=False, alias="DJANGO_DEBUG")
    allowed_hosts: list[str] = Field(default_factory=lambda: ["127.0.0.1", "localhost"])
    timezone: str = Field(default="Europe/Warsaw", alias="DJANGO_TIME_ZONE")
    language_code: str = Field(default="pl-pl", alias="DJANGO_LANGUAGE_CODE")
    database_url: str = Field(default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}", alias="DATABASE_URL")
    backup_storage_root: Path = Field(
        default=BASE_DIR / "var" / "snapshots",
        alias="BACKUP_STORAGE_ROOT",
    )


settings = AppSettings()
