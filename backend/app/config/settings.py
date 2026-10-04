from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "SSDD: Steel Defect Agent"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True
    SKIP_EXTERNAL_STARTUP: bool = False
    BOOTSTRAP_ADMIN_PASSWORD: str = ""
    BOOTSTRAP_ADMIN_EMAIL: str = "admin@example.com"

    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "logs"
    LOG_MAX_BYTES: int = 10 * 1024 * 1024
    LOG_BACKUP_COUNT: int = 5

    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "rsod_agent"
    DB_USER: str = "rsod_admin"
    DB_PASSWORD: str = "rsod_admin"

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379

    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "rsod-agent-images"
    MINIO_SECURE: bool = False

    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_MODEL: str = "gpt-4o-mini"

    # The project uses the DashScope-compatible embedding endpoint by default.
    # Its dimension must stay aligned with EMBEDDING_DIM in db_models.py.
    EMBEDDING_MODEL: str = "qwen3.7-text-embedding"
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_BASE_URL: str = ""

    @property
    def embedding_api_key(self) -> str:
        return self.EMBEDDING_API_KEY or self.OPENAI_API_KEY

    @property
    def embedding_base_url(self) -> str:
        return self.EMBEDDING_BASE_URL or self.OPENAI_BASE_URL

    DATASET_BASE_DIR: str = "datasets/ssdd"
    TRAIN_OUTPUT_DIR: str = "runs/train"
    CLEANUP_RETRY_INTERVAL_SECONDS: int = 300
    CLEANUP_LOCK_TTL_SECONDS: int = 600

    JWT_SECRET_KEY: str = "your-super-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = ""
    SMTP_USE_TLS: bool = True
    PASSWORD_RESET_URL: str = "http://localhost:3000/login"

    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:5173,http://localhost:8080"

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug(cls, value):
        if isinstance(value, str) and value.strip().lower() in {"release", "prod", "production"}:
            return False
        return value

    @model_validator(mode="after")
    def validate_production_secrets(self):
        if self.DEBUG:
            return self
        placeholders = {
            "your-super-secret-key-change-in-production",
            "minioadmin",
            "rsod_admin",
            "REPLACE_WITH_A_LONG_UNIQUE_PASSWORD",
            "REPLACE_WITH_A_32_BYTE_OR_LONGER_RANDOM_SECRET",
        }
        if self.JWT_SECRET_KEY in placeholders or len(self.JWT_SECRET_KEY) < 32:
            raise ValueError("JWT_SECRET_KEY must be a non-placeholder value of at least 32 characters in production")
        if self.DB_PASSWORD in placeholders or self.MINIO_SECRET_KEY in placeholders:
            raise ValueError("Database and MinIO passwords must not use example values in production")
        origins = self.cors_origins_list
        if not origins or "*" in origins or any("localhost" in origin for origin in origins):
            raise ValueError("ALLOWED_ORIGINS must contain explicit non-localhost origins in production")
        return self

    @property
    def DATABASE_URL(self) -> str:
        from sqlalchemy.engine import URL

        return URL.create("postgresql", username=self.DB_USER, password=self.DB_PASSWORD,
                          host=self.DB_HOST, port=self.DB_PORT, database=self.DB_NAME).render_as_string(hide_password=False)

    @property
    def REDIS_URL(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/0"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",")]


settings = Settings()
