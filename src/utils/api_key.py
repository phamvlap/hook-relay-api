import hashlib
import hmac
import secrets
from functools import lru_cache
from typing import Final, NamedTuple

from src.core.config import settings
from src.exceptions.api_key import InvalidAPIKeyFormatError
from src.models.api_key import APIKeyEnvironment

API_KEY_PREFIX: Final[str] = "hr"
KEY_ID_BYTES: Final[int] = 16  # 32 hex chars -> 128-bit collision resistance
SECRET_BYTES: Final[int] = 32  # 256-bit cryptographic entropy
DUMMY_HASH: Final[str] = "0" * 64  # Matches SHA-256 64-char hexdigest length


class ParsedAPIKey(NamedTuple):
    """Structured representation of a parsed API key."""

    prefix: str
    environment: APIKeyEnvironment
    key_id: str
    secret_key: str


class GeneratedAPIKey(NamedTuple):
    """Structured result of API key generation."""

    key_id: str
    secret_key: str
    key_hash: str
    full_key: str


@lru_cache(maxsize=1)
def get_default_pepper_bytes() -> bytes:
    """Retrieves and caches the application pepper in bytes format."""
    return settings.api_key_pepper_value.encode("utf-8")


def parse_api_key(raw_key: str) -> ParsedAPIKey:
    """Parses and validates a raw API key token.

    Expected format:
        hr_<env>_<key_id>_<secret_key>

    Args:
        raw_key: Raw token string from request headers.

    Returns:
        ParsedAPIKey namedtuple containing the components.

    Raises:
        InvalidAPIKeyFormatError: If the token format, prefix, or environment is invalid.
    """
    if not raw_key or not isinstance(raw_key, str):
        raise InvalidAPIKeyFormatError("API key must be a non-empty string")

    parts = raw_key.strip().split("_", 3)
    if len(parts) != 4:
        raise InvalidAPIKeyFormatError("Malformed API key format")

    prefix, raw_env, key_id, secret_key = parts

    if prefix != API_KEY_PREFIX:
        raise InvalidAPIKeyFormatError(f"Invalid API key prefix: expected '{API_KEY_PREFIX}'")

    try:
        environment = APIKeyEnvironment(raw_env)
    except ValueError:
        raise InvalidAPIKeyFormatError(f"Unknown API key environment: '{raw_env}'")

    if len(key_id) < 8 or not secret_key.strip():
        raise InvalidAPIKeyFormatError("API key contains invalid key_id or secret")

    return ParsedAPIKey(
        prefix=prefix,
        environment=environment,
        key_id=key_id,
        secret_key=secret_key,
    )


def hash_secret(secret: str, *, pepper: bytes | None = None) -> str:
    """Computes an HMAC-SHA256 digest of the secret with the pepper.

    Args:
        secret: Plain-text secret part of the API key.
        pepper: Optional pepper bytes. Defaults to the configured system pepper.

    Returns:
        Hex-encoded 64-character SHA-256 HMAC digest.
    """
    secret_bytes = secret.encode("utf-8")
    pepper_bytes = pepper if pepper is not None else get_default_pepper_bytes()

    return hmac.new(
        key=pepper_bytes,
        msg=secret_bytes,
        digestmod=hashlib.sha256,
    ).hexdigest()


def verify_secret(
    secret_key: str,
    expected_hash: str | None,
    *,
    pepper: bytes | None = None,
) -> bool:
    """Verifies a secret against an expected hash using constant-time comparison.

    Performs a constant-time comparison against a dummy hash when expected_hash
    is None to mitigate timing side-channel leakage.

    Args:
        secret_key: Plain-text secret key presented by the client.
        expected_hash: Hex-encoded hash from the database, or None if key was not found.
        pepper: Optional pepper bytes.

    Returns:
        True if the secret matches expected_hash; False otherwise.
    """
    computed_hash = hash_secret(secret_key, pepper=pepper)
    target_hash = expected_hash if expected_hash is not None else DUMMY_HASH

    is_valid = hmac.compare_digest(computed_hash, target_hash)
    return is_valid and (expected_hash is not None)


def generate_api_key(environment: APIKeyEnvironment) -> GeneratedAPIKey:
    """Generates a cryptographically secure API key.

    Uses 128-bit random hex key_id and 256-bit URL-safe secret token.

    Args:
        environment: Target environment (e.g., TEST or LIVE).

    Returns:
        GeneratedAPIKey containing key_id, secret_key, key_hash, and full_key.
    """
    key_id = secrets.token_hex(KEY_ID_BYTES)
    secret_key = secrets.token_urlsafe(SECRET_BYTES)
    key_hash = hash_secret(secret_key)
    full_key = f"{API_KEY_PREFIX}_{environment.value}_{key_id}_{secret_key}"

    return GeneratedAPIKey(
        key_id=key_id,
        secret_key=secret_key,
        key_hash=key_hash,
        full_key=full_key,
    )
