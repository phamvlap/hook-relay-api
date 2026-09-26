from functools import cached_property, lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        str_strip_whitespace=True,
        case_sensitive=False,
        extra="ignore",
    )

    # Application configuration
    environment: Literal["development", "staging", "production"] = "development"

    # PostgreSQL database configuration
    db_host: str = Field(description="PostgreSQL database host")
    db_port: int = Field(ge=1, le=65535, description="PostgreSQL database port")
    db_name: str = Field(description="PostgreSQL database name")
    db_username: str = Field(description="PostgreSQL database username")
    db_password: SecretStr = Field(description="PostgreSQL database password")

    database_url: PostgresDsn | None = Field(
        default=None,
        description="PostgreSQL database URL (optional)",
    )

    # Redis configuration
    redis_host: str = Field(description="Redis host")
    redis_port: int = Field(ge=1, le=65535, description="Redis port")
    redis_password: SecretStr | None = Field(default=None, description="Redis password (optional)")
    redis_username: str | None = Field(default=None, description="Redis username (optional)")
    redis_db: int = Field(ge=0, le=10, description="Redis database")
    redis_enabled_ssl: bool = Field(default=False, description="Enable SSL for Redis connection")

    redis_url: RedisDsn | None = Field(
        default=None,
        description="Redis URL (optional)",
    )

    # Security configuration
    api_key_pepper: SecretStr = Field(description="High-entropy pepper value for API key hashing")

    # Encryption key for encrypting endpoint secrets
    endpoint_secret_encryption_key: SecretStr = Field(
        description="High-entropy encryption key for encrypting endpoint secrets",
    )

    @field_validator("api_key_pepper")
    def validate_api_key_pepper(cls, value: SecretStr) -> SecretStr:
        raw_val = value.get_secret_value().strip()

        if len(raw_val) < 12:
            raise ValueError("API key pepper must be at least 12 characters long")

        return value

    @field_validator("endpoint_secret_encryption_key")
    def validate_endpoint_secret_encryption_key(cls, value: SecretStr) -> SecretStr:
        raw_val = value.get_secret_value().strip()

        if len(raw_val) < 12:
            raise ValueError("Endpoint secret encryption key must be at least 12 characters long")

        return value

    @cached_property
    def postgres_dsn(self) -> PostgresDsn:
        if self.database_url:
            return self.database_url

        return PostgresDsn.build(
            scheme="postgresql",
            username=self.db_username,
            password=self.db_password.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            path=self.db_name,
        )

    @cached_property
    def postgres_dsn_str(self) -> str:
        return str(self.postgres_dsn)

    @cached_property
    def redis_dsn(self) -> RedisDsn:
        if self.redis_url:
            return self.redis_url

        scheme = "rediss" if self.redis_enabled_ssl else "redis"
        return RedisDsn.build(
            scheme=scheme,
            username=self.redis_username,
            password=self.redis_password.get_secret_value() if self.redis_password else None,
            host=self.redis_host,
            port=self.redis_port,
            path=str(self.redis_db),
        )

    @cached_property
    def redis_dsn_str(self) -> str:
        return str(self.redis_dsn)

    @property
    def api_key_pepper_value(self) -> str:
        return self.api_key_pepper.get_secret_value()

    @property
    def endpoint_secret_encryption_key_value(self) -> str:
        return self.endpoint_secret_encryption_key.get_secret_value()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]


settings: Settings = get_settings()
