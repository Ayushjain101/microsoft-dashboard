"""Pydantic Settings — loaded from environment / .env file."""

from pydantic import field_validator, model_validator
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

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: object) -> object:
        if isinstance(v, str):
            import json
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return parsed
            except (json.JSONDecodeError, TypeError):
                pass
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @model_validator(mode="after")
    def validate_fernet_key(self):
        if not self.fernet_key:
            raise ValueError(
                "FERNET_KEY environment variable is required. "
                "Generate one with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
            )
        return self


settings = Settings()
