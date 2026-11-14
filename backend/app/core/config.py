from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str | None = None
    postgres_db: str = "job_hunting"
    postgres_user: str = "job_hunting"
    postgres_password: str = "change-me"
    postgres_password_file: Path | None = None
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    verify_database_name: str = "job_hunting_verify"
    jwt_secret: str = Field(default="replace-this-development-secret-before-deploying", min_length=32)
    jwt_secret_file: Path | None = None
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = Field(default=15, gt=0)
    refresh_token_days: int = Field(default=30, gt=0)
    cors_origins: str = "http://localhost:5173"
    resume_storage_root: Path = Path(__file__).resolve().parents[2] / "var" / "private" / "resumes"
    max_resume_upload_bytes: int = Field(default=5 * 1024 * 1024, gt=0)
    openai_api_key: str | None = None
    openai_api_key_file: Path | None = None
    openai_model: str = "gpt-4o-mini"
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: str | None = None
    google_oauth_client_secret_file: Path | None = None
    google_oauth_redirect_uri: str | None = None
    oauth_token_encryption_key: str | None = None
    oauth_token_encryption_key_file: Path | None = None
    matching_ai_enabled: bool = False
    matching_timeout_seconds: int = Field(default=20, ge=1, le=120)
    matching_weights: str = '{"skills":40,"experience":20,"role":15,"location":15,"salary":10}'
    matching_max_batch: int = Field(default=50, ge=1, le=100)
    matching_max_ai_calls: int = Field(default=8, ge=0, le=50)
    matching_rate_limit_per_minute: int = Field(default=10, ge=1, le=120)
    application_generation_daily_limit: int = Field(default=10, ge=1, le=50)
    application_generation_timeout_seconds: int = Field(default=45, ge=1, le=120)
    automation_timezone: str = "Asia/Kolkata"
    collection_timeout_seconds: int = Field(default=300, ge=30, le=1800)
    collection_retry_attempts: int = Field(default=3, ge=1, le=5)
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_password_file: Path | None = None
    smtp_from_email: str | None = None
    smtp_starttls: bool = True
    auth_login_max_attempts: int = Field(default=10, ge=3, le=50)
    auth_login_window_minutes: int = Field(default=15, ge=1, le=60)
    app_env: str = Field(default="development", pattern="^(development|test|production)$")

    @model_validator(mode="before")
    @classmethod
    def read_secret_files(cls, values):
        if not isinstance(values, dict):
            return values
        values = dict(values)
        for secret_name in ("postgres_password", "jwt_secret", "openai_api_key", "smtp_password", "google_oauth_client_secret", "oauth_token_encryption_key"):
            path = values.get(f"{secret_name}_file")
            if path and not values.get(secret_name):
                try:
                    values[secret_name] = Path(path).read_text(encoding="utf-8").rstrip("\r\n")
                except OSError as exc:
                    raise ValueError(f"Could not read configured {secret_name.upper()}_FILE") from exc
        return values

    @model_validator(mode="after")
    def production_secrets_and_origins(self):
        if self.app_env == "production":
            if self.jwt_secret == "replace-this-development-secret-before-deploying":
                raise ValueError("JWT_SECRET must be set to a unique secret in production")
            database_password = make_url(self.database_url).password if self.database_url else self.postgres_password
            if database_password in {None, "", "change-me"}:
                raise ValueError("POSTGRES_PASSWORD must be set in production")
            if len(database_password) < 20:
                raise ValueError("POSTGRES_PASSWORD must contain at least 20 characters in production")
            if any(origin == "*" or origin.startswith("http://") for origin in self.cors_origin_list):
                raise ValueError("Production CORS_ORIGINS must use explicit HTTPS origins")
            if bool(self.smtp_username) != bool(self.smtp_password):
                raise ValueError("SMTP_USERNAME and SMTP_PASSWORD must be configured together")
            if bool(self.google_oauth_client_id) != bool(self.google_oauth_client_secret):
                raise ValueError("Google OAuth client ID and secret must be configured together")
            if self.google_oauth_client_id and (
                not self.google_oauth_redirect_uri
                or not self.google_oauth_redirect_uri.startswith("https://")
                or not self.oauth_token_encryption_key
            ):
                raise ValueError("Google OAuth requires an HTTPS redirect URI and token encryption key")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return URL.create(
            "postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        ).render_as_string(hide_password=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
