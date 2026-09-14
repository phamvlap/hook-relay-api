from pydantic import Field, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    db_host: str
    db_port: int = Field(ge=1, le=65535)
    db_name: str
    db_username: str
    db_password: SecretStr

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


settings = Settings()  # pyright: ignore[reportCallIssue]
