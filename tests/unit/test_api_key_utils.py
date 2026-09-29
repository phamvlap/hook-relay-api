"""Unit tests for API key parsing, generation, hashing, and verification."""

import pytest

from src.exceptions.api_key import InvalidAPIKeyFormatError
from src.models.api_key import APIKeyEnvironment
from src.utils.api_key import (
    API_KEY_PREFIX,
    generate_api_key,
    hash_secret,
    parse_api_key,
    verify_secret,
)


@pytest.mark.unit
class TestAPIKeyParsing:
    def test_parse_valid_live_key(self):
        token = "hr_live_0123456789abcdef_mySecretTokenValue123"
        parsed = parse_api_key(token)

        assert parsed.prefix == API_KEY_PREFIX
        assert parsed.environment == APIKeyEnvironment.LIVE
        assert parsed.key_id == "0123456789abcdef"
        assert parsed.secret_key == "mySecretTokenValue123"

    def test_parse_valid_test_key(self):
        token = "hr_test_abcdef0123456789_secretKeyTest456"
        parsed = parse_api_key(token)

        assert parsed.prefix == API_KEY_PREFIX
        assert parsed.environment == APIKeyEnvironment.TEST
        assert parsed.key_id == "abcdef0123456789"
        assert parsed.secret_key == "secretKeyTest456"

    def test_parse_invalid_prefix_raises_error(self):
        token = "sk_live_0123456789abcdef_mySecretTokenValue123"
        with pytest.raises(InvalidAPIKeyFormatError, match="Invalid API key prefix"):
            parse_api_key(token)

    def test_parse_invalid_environment_raises_error(self):
        token = "hr_staging_0123456789abcdef_mySecretTokenValue123"
        with pytest.raises(InvalidAPIKeyFormatError, match="Unknown API key environment"):
            parse_api_key(token)

    def test_parse_malformed_parts_raises_error(self):
        with pytest.raises(
            InvalidAPIKeyFormatError, match="API key contains invalid key_id or secret"
        ):
            parse_api_key("hr_live_too_few_parts")

        with pytest.raises(InvalidAPIKeyFormatError, match="API key must be a non-empty string"):
            parse_api_key("")

    def test_parse_short_key_id_raises_error(self):
        with pytest.raises(InvalidAPIKeyFormatError, match="invalid key_id or secret"):
            parse_api_key("hr_test_short_secret")


@pytest.mark.unit
class TestAPIKeyHashingAndVerification:
    def test_hash_secret_is_deterministic_and_sha256(self):
        secret = "secret_value_123"
        pepper = b"my_custom_pepper_123"
        hash_1 = hash_secret(secret, pepper=pepper)
        hash_2 = hash_secret(secret, pepper=pepper)

        assert hash_1 == hash_2
        assert len(hash_1) == 64  # SHA-256 hex digest length

    def test_hash_secret_differs_with_different_peppers(self):
        secret = "secret_value_123"
        hash_1 = hash_secret(secret, pepper=b"pepper_one_12345")
        hash_2 = hash_secret(secret, pepper=b"pepper_two_12345")

        assert hash_1 != hash_2

    def test_verify_secret_success(self):
        secret = "super_secret_token"
        pepper = b"test_pepper_1234"
        expected_hash = hash_secret(secret, pepper=pepper)

        assert verify_secret(secret, expected_hash, pepper=pepper) is True

    def test_verify_secret_wrong_secret_fails(self):
        secret = "super_secret_token"
        pepper = b"test_pepper_1234"
        expected_hash = hash_secret(secret, pepper=pepper)

        assert verify_secret("wrong_secret_token", expected_hash, pepper=pepper) is False

    def test_verify_secret_with_none_hash_is_constant_time_safe(self):
        # When expected_hash is None, verify_secret runs dummy comparison and returns False
        assert verify_secret("any_secret", None) is False


@pytest.mark.unit
class TestAPIKeyGeneration:
    def test_generate_api_key_structure_and_roundtrip(self):
        generated = generate_api_key(APIKeyEnvironment.TEST)

        assert generated.full_key.startswith("hr_test_")
        assert len(generated.key_id) == 32  # 16 bytes hex -> 32 chars
        assert len(generated.secret_key) > 30
        assert len(generated.key_hash) == 64

        # Roundtrip parse
        parsed = parse_api_key(generated.full_key)
        assert parsed.key_id == generated.key_id
        assert parsed.secret_key == generated.secret_key
        assert parsed.environment == APIKeyEnvironment.TEST

        # Secret verification
        assert verify_secret(generated.secret_key, generated.key_hash) is True

    def test_generate_api_key_live_environment(self):
        generated = generate_api_key(APIKeyEnvironment.LIVE)
        assert generated.full_key.startswith("hr_live_")
        assert len(generated.key_id) == 32
        assert len(generated.key_hash) == 64

    def test_parse_api_key_trims_whitespace(self):
        token = "  hr_test_0123456789abcdef_mySecretTokenValue123  \n"
        parsed = parse_api_key(token)
        assert parsed.key_id == "0123456789abcdef"
        assert parsed.secret_key == "mySecretTokenValue123"

    def test_parse_api_key_rejects_non_string(self):
        with pytest.raises(InvalidAPIKeyFormatError, match="API key must be a non-empty string"):
            parse_api_key(None)  # type: ignore

        with pytest.raises(InvalidAPIKeyFormatError, match="API key must be a non-empty string"):
            parse_api_key(12345)  # type: ignore
