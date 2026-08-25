from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # OpenRouter
    openrouter_api_key: str = ""
    openrouter_model: str = "stealth/ox-alpha"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_app_url: str = "http://localhost:3000"
    openrouter_app_title: str = "Scientific Skill Transfer Agent"

    # Data stores
    database_url: str = "postgresql+asyncpg://ssta:ssta_dev_password@postgres:5432/ssta"
    # Alembic runs synchronously. The +psycopg suffix is required: a bare
    # postgresql:// URL makes SQLAlchemy load the psycopg2 driver, which is not
    # a dependency of this project -- psycopg 3 is.
    sync_database_url: str = "postgresql+psycopg://ssta:ssta_dev_password@postgres:5432/ssta"
    redis_url: str = "redis://redis:6379/0"

    # Object storage
    s3_endpoint_url: str = "http://minio:9000"
    s3_public_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "ssta"
    s3_region: str = "us-east-1"
    # Create the bucket during API startup. Turn off when pointing at managed
    # object storage where the bucket is provisioned out of band and the
    # credentials have no CreateBucket permission.
    s3_ensure_bucket_on_startup: bool = True
    # Hard cap on that startup check so a slow or unreachable object store can
    # never hold up the API's boot.
    s3_startup_timeout_s: float = 5.0

    # Sandbox
    sandbox_url: str = "http://sandbox:8000"
    sandbox_timeout_s: int = 600
    sandbox_memory_mb: int = 3072

    # Agent
    agent_max_iterations: int = 8
    agent_temperature: float = 0.0
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
