from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    db_host: str
    db_port: int
    db_name: str
    db_username: str
    db_password: str

    @property
    def postgres_dsn(self) -> PostgresDsn:
        return PostgresDsn.build(
            scheme="postgresql",
            username=self.db_username,
            password=self.db_password,
            host=self.db_host,
            port=self.db_port,
            path=self.db_name,
        )


settings = Settings()  # pyright: ignore[reportCallIssue]
