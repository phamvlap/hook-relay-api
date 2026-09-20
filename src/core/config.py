from pydantic import Field, PostgresDsn, RedisDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    db_host: str
    db_port: int = Field(ge=1, le=65535)
    db_name: str
    db_username: str
    db_password: SecretStr

    redis_host: str
    redis_port: int = Field(ge=1, le=65535)
    redis_password: SecretStr | None = None
    redis_username: str | None = None
    redis_db: int = Field(ge=0, le=10)
    redis_enabled_ssl: bool = False

    api_key_pepper: SecretStr

    @property
    def postgres_dsn(self) -> PostgresDsn:
        return PostgresDsn.build(
            scheme="postgresql",
            username=self.db_username,
            password=self.db_password.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            path=self.db_name,
        )

    @property
    def redis_dsn(self) -> RedisDsn:
        scheme = "rediss" if self.redis_enabled_ssl else "redis"
        return RedisDsn.build(
            scheme=scheme,
            username=self.redis_username,
            password=self.redis_password.get_secret_value() if self.redis_password else None,
            host=self.redis_host,
            port=self.redis_port,
            path=str(self.redis_db),
        )

    @property
    def api_key_pepper_value(self) -> str:
        return self.api_key_pepper.get_secret_value()


settings = Settings()  # pyright: ignore[reportCallIssue]
