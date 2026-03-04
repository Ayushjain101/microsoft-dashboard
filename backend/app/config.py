"""Pydantic Settings — loaded from environment / .env file."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Auth
    dashboard_password: str = "changeme"
    session_secret: str = "change-this-to-random-bytes"
    session_ttl_hours: int = 72

    # Encryption
    fernet_key: str = ""

    # Database
    database_url: str = "postgresql+asyncpg://tenantadmin:dbpass@localhost:5432/tenants"
    database_url_sync: str = "postgresql://tenantadmin:dbpass@localhost:5432/tenants"

    # Redis
    redis_url: str = "redis://:redispass@localhost:6379/0"
    redis_password: str = "redispass"

    # CORS
    cors_origins: list[str] = ["http://localhost:3000"]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
