"""Unit tests for Settings validation and property derivations."""

import pytest
from pydantic import RedisDsn, SecretStr

from src.core.config import Settings


@pytest.mark.unit
class TestSettingsValidation:
    def test_pepper_length_validation_rejects_under_12_chars(self):
        with pytest.raises(ValueError, match="API key pepper must be at least 12 characters long"):
            Settings(
                api_key_pepper=SecretStr("short"),
                endpoint_secret_encryption_key=SecretStr("valid_key_12_chars_long"),
                db_host="localhost",
                db_port=5432,
                db_name="test_db",
                db_username="postgres",
                db_password=SecretStr("postgres"),
                redis_host="localhost",
                redis_port=6379,
                redis_db=0,
            )

    def test_encryption_key_validation_rejects_under_12_chars(self):
        with pytest.raises(
            ValueError,
            match="Endpoint secret encryption key must be at least 12 characters long",
        ):
            Settings(
                api_key_pepper=SecretStr("valid_pepper_12_chars"),
                endpoint_secret_encryption_key=SecretStr("short"),
                db_host="localhost",
                db_port=5432,
                db_name="test_db",
                db_username="postgres",
                db_password=SecretStr("postgres"),
                redis_host="localhost",
                redis_port=6379,
                redis_db=0,
            )

    def test_allowed_hosts_and_cors_lists_parsing(self):
        settings = Settings(
            allowed_hosts=" localhost, api.example.com , , internal.service ",
            cors_origins="https://app.example.com, https://admin.example.com",
            api_key_pepper=SecretStr("valid_pepper_12_chars"),
            endpoint_secret_encryption_key=SecretStr("valid_key_12_chars_long"),
            db_host="localhost",
            db_port=5432,
            db_name="test_db",
            db_username="postgres",
            db_password=SecretStr("postgres"),
            redis_host="localhost",
            redis_port=6379,
            redis_db=0,
        )

        assert settings.allowed_hosts_list == ["localhost", "api.example.com", "internal.service"]
        assert settings.cors_origins_list == [
            "https://app.example.com",
            "https://admin.example.com",
        ]

    def test_dsn_string_construction(self):
        settings = Settings(
            db_host="db.example.com",
            db_port=5432,
            db_name="prod_db",
            db_username="app_user",
            db_password=SecretStr("secret_pw"),
            redis_host="redis.example.com",
            redis_port=6379,
            redis_db=2,
            api_key_pepper=SecretStr("valid_pepper_12_chars"),
            endpoint_secret_encryption_key=SecretStr("valid_key_12_chars_long"),
        )

        assert (
            "postgresql://app_user:secret_pw@db.example.com:5432/prod_db"
            in settings.postgres_dsn_str
        )
        assert (
            "postgresql+asyncpg://app_user:secret_pw@db.example.com:5432/prod_db"
            in settings.postgres_async_dsn_str
        )
        assert "redis://redis.example.com:6379/2" in settings.redis_dsn_str
        assert "redis://redis.example.com:6379/2" in settings.celery_redis_dsn_str
        assert "ssl_cert_reqs" not in settings.celery_redis_dsn_str
        assert settings.rate_limit_enabled is True

    def test_celery_redis_dsn_with_ssl_appends_cert_reqs(self):
        settings = Settings(
            db_host="localhost",
            db_port=5432,
            db_name="test_db",
            db_username="postgres",
            db_password=SecretStr("postgres"),
            redis_host="secure-redis.example.com",
            redis_port=6379,
            redis_db=1,
            redis_enabled_ssl=True,
            api_key_pepper=SecretStr("valid_pepper_12_chars"),
            endpoint_secret_encryption_key=SecretStr("valid_key_12_chars_long"),
        )

        assert "rediss://secure-redis.example.com:6379/1" in settings.redis_dsn_str
        assert "ssl_cert_reqs" not in settings.redis_dsn_str
        assert (
            "rediss://secure-redis.example.com:6379/1?ssl_cert_reqs=CERT_NONE"
            in settings.celery_redis_dsn_str
        )

    def test_celery_redis_dsn_with_custom_url(self):
        settings = Settings(
            db_host="localhost",
            db_port=5432,
            db_name="test_db",
            db_username="postgres",
            db_password=SecretStr("postgres"),
            redis_host="localhost",
            redis_port=6379,
            redis_db=0,
            redis_url=RedisDsn("rediss://default:mypass@cloud.redis.io:6379/0?timeout=5"),
            api_key_pepper=SecretStr("valid_pepper_12_chars"),
            endpoint_secret_encryption_key=SecretStr("valid_key_12_chars_long"),
        )

        assert "rediss://default:mypass@cloud.redis.io:6379/0" in settings.celery_redis_dsn_str
        assert "ssl_cert_reqs=CERT_NONE" in settings.celery_redis_dsn_str
        assert "timeout=5" in settings.celery_redis_dsn_str

    def test_redis_ssl_cert_reqs_validation_rejects_invalid_value(self):
        with pytest.raises(ValueError, match="redis_ssl_cert_reqs must be one of"):
            Settings(
                db_host="localhost",
                db_port=5432,
                db_name="test_db",
                db_username="postgres",
                db_password=SecretStr("postgres"),
                redis_host="localhost",
                redis_port=6379,
                redis_db=0,
                redis_ssl_cert_reqs="INVALID_MODE",
                api_key_pepper=SecretStr("valid_pepper_12_chars"),
                endpoint_secret_encryption_key=SecretStr("valid_key_12_chars_long"),
            )
