import ipaddress
from functools import cached_property, lru_cache

from pydantic import Field, PostgresDsn, RedisDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.core.enum import BaseStrEnum


class Environment(BaseStrEnum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TEST = "test"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        str_strip_whitespace=True,
        case_sensitive=False,
        extra="ignore",
    )

    # Application configuration
    environment: Environment = Environment.DEVELOPMENT

    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION

    @property
    def is_development(self) -> bool:
        return self.environment == Environment.DEVELOPMENT

    @property
    def is_staging(self) -> bool:
        return self.environment == Environment.STAGING

    @property
    def is_test(self) -> bool:
        return self.environment == Environment.TEST

    allowed_hosts: str = Field(
        default="*",
        description="Comma-separated list of allowed hosts for the application",
    )
    cors_origins: str = Field(
        default="*",
        description="Comma-separated list of allowed origins for CORS",
    )
    trusted_proxies: str = Field(
        default="127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16",
        description="Comma-separated list of trusted proxy IPs or CIDR networks for reverse-proxy client IP extraction",
    )

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

    # Database Pool & Engine Configuration (Shared)
    db_pool_timeout: int = Field(
        default=30,
        ge=1,
        description="Timeout in seconds to wait for an available connection from the pool",
    )
    db_pool_recycle: int = Field(
        default=1800,
        ge=-1,
        description="Recycle connections older than this age in seconds (-1 to disable)",
    )
    db_pool_pre_ping: bool = Field(
        default=True,
        description="Enable connection liveness pre-ping before checkout to handle dropped connections",
    )
    db_echo: bool = Field(
        default=False,
        description="Log all SQL statements to stdout (use only in local development/debugging)",
    )
    db_statement_cache_size: int = Field(
        default=0,
        ge=0,
        description="Prepared statement cache size for asyncpg (must be 0 when using PgBouncer/Supabase pooler in transaction mode)",
    )

    # Engine-Specific Pool Limits
    # Sync Engine (migrations, CLI, sync utilities)
    db_sync_pool_size: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Connection pool size for synchronous database connections",
    )
    db_sync_max_overflow: int = Field(
        default=5,
        ge=0,
        le=50,
        description="Maximum burst connections allowed beyond db_sync_pool_size",
    )

    # Main Async Engine (FastAPI web request handling)
    db_async_pool_size: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Connection pool size for main async FastAPI connections",
    )
    db_async_max_overflow: int = Field(
        default=10,
        ge=0,
        le=50,
        description="Maximum burst connections allowed beyond db_async_pool_size",
    )

    # Worker Async Engine (Celery worker processes / background tasks)
    db_worker_pool_size: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Connection pool size for background Celery worker async connections",
    )
    db_worker_max_overflow: int = Field(
        default=5,
        ge=0,
        le=50,
        description="Maximum burst connections allowed beyond db_worker_pool_size",
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

    # Rate limiting configuration
    rate_limit_enabled: bool = Field(
        default=True,
        description="Enable or disable rate limiting globally",
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
    def postgres_async_dsn(self) -> PostgresDsn:
        if self.database_url:
            raw_url = str(self.database_url)
            if raw_url.startswith("postgresql+asyncpg://"):
                return self.database_url
            if raw_url.startswith("postgresql://"):
                return PostgresDsn(raw_url.replace("postgresql://", "postgresql+asyncpg://", 1))
            if raw_url.startswith("postgres://"):
                return PostgresDsn(raw_url.replace("postgres://", "postgresql+asyncpg://", 1))
            return self.database_url

        return PostgresDsn.build(
            scheme="postgresql+asyncpg",
            username=self.db_username,
            password=self.db_password.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            path=self.db_name,
        )

    @cached_property
    def postgres_async_dsn_str(self) -> str:
        return str(self.postgres_async_dsn)

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

    @property
    def allowed_hosts_list(self) -> list[str]:
        hosts = [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]
        return hosts

    @property
    def cors_origins_list(self) -> list[str]:
        origins = [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
        return origins

    @cached_property
    def trusted_proxy_networks(self) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
        """Parsed list of trusted IP networks for secure client IP extraction."""
        networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        for raw in self.trusted_proxies.split(","):
            raw_clean = raw.strip()
            if not raw_clean:
                continue
            try:
                networks.append(ipaddress.ip_network(raw_clean, strict=False))
            except ValueError:
                continue
        return networks


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]


settings: Settings = get_settings()
