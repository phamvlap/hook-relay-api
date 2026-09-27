import hashlib
import hmac
import secrets
from typing import Final

from src.core.config import settings
from src.exceptions.api_key import InvalidAPIKeyFormatError
from src.models.api_key import APIKeyEnvironment

API_KEY_PREFIX: Final[str] = "hr"
DUMMY_HASH: Final[str] = "0" * 64  # Timing attack mitigation dummy hash


def parse_api_key(raw_key: str) -> tuple[str, str]:
    """Parses raw 'hr_<env>_<key_id>_<secret>' into (key_id, secret_key)."""
    parts = raw_key.strip().split("_", 3)
    if len(parts) != 4 or parts[0] != API_KEY_PREFIX or parts[1] not in APIKeyEnvironment.values():
        raise InvalidAPIKeyFormatError("Malformed API key format")
    return parts[2], parts[3]


def hash_secret(secret: str) -> str:
    """Computes HMAC-SHA256 with the configured application pepper."""
    return hmac.new(
        key=settings.api_key_pepper_value.encode(),
        msg=secret.encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()


def verify_secret(secret_key: str, expected_hash: str) -> bool:
    """Constant-time comparison to prevent timing side-channel attacks."""
    computed_hash = hash_secret(secret_key)
    return hmac.compare_digest(computed_hash, expected_hash)


def generate_api_key(environment: APIKeyEnvironment) -> tuple[str, str, str, str]:
    """Generates (key_id, secret_key, key_hash, constructed_api_key)."""
    key_id = secrets.token_hex(6)
    secret_key = secrets.token_urlsafe(32)
    key_hash = hash_secret(secret_key)
    full_key = f"{API_KEY_PREFIX}_{environment.value}_{key_id}_{secret_key}"
    return key_id, secret_key, key_hash, full_key
