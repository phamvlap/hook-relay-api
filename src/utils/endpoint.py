import base64
import binascii
import hashlib
import hmac
import secrets
from typing import Final

from cryptography.fernet import Fernet

from src.core.config import settings

DEFAULT_SECRET_PREFIX: Final[str] = "whsec_"


class EndpointSecretCrypto:
    """
    Reusable cryptographic utility class for webhook endpoint secret management.

    Handles:
    - Symmetric encryption/decryption of endpoint signing secrets using Fernet
    - Secure secret generation (e.g. whsec_...)
    - HMAC-SHA256 signature computation and constant-time verification for deliveries
    """

    def __init__(self, key: str | None = None) -> None:
        self._encryption_key = key
        self._cipher: Fernet | None = None

    @staticmethod
    def derive_fernet_key(raw_key: str) -> bytes:
        """
        Ensure a valid 32-byte URL-safe base64 encoded key for Fernet.
        If raw_key is already a valid 32-byte base64 string, returns it directly.
        Otherwise, deterministically derives a 32-byte key using SHA-256 and base64.
        """
        try:
            decoded = base64.urlsafe_b64decode(raw_key.encode("utf-8"))
            if len(decoded) == 32:
                return raw_key.encode("utf-8")
        except binascii.Error:
            pass

        return base64.urlsafe_b64encode(hashlib.sha256(raw_key.encode("utf-8")).digest())

    @property
    def cipher(self) -> Fernet:
        if self._cipher is None:
            raw_key = self._encryption_key or settings.endpoint_secret_encryption_key_value
            self._cipher = Fernet(self.derive_fernet_key(raw_key))
        return self._cipher

    def generate_secret(self, prefix: str = DEFAULT_SECRET_PREFIX) -> str:
        """
        Generate a cryptographically secure random secret token.
        """
        return f"{prefix}{secrets.token_urlsafe(32)}"

    def encrypt(self, secret: str) -> str:
        """
        Encrypt a plaintext secret using Fernet symmetric encryption.
        """
        return self.cipher.encrypt(secret.encode("utf-8")).decode("utf-8")

    def decrypt(self, encrypted_secret: str) -> str:
        """
        Decrypt an encrypted secret token using Fernet symmetric decryption.
        """
        return self.cipher.decrypt(encrypted_secret.encode("utf-8")).decode("utf-8")

    def compute_signature(self, payload: bytes, secret: str, timestamp: str | int) -> str:
        """
        Compute HMAC-SHA256 signature for webhook payload:
        HMAC-SHA256(secret, f"{timestamp}." + payload)
        """
        to_sign = f"{timestamp}.".encode() + payload
        return hmac.new(
            key=secret.encode("utf-8"),
            msg=to_sign,
            digestmod=hashlib.sha256,
        ).hexdigest()

    def verify_signature(
        self,
        payload: bytes,
        secret: str,
        timestamp: str | int,
        expected_signature: str,
    ) -> bool:
        """
        Verify webhook signature using constant-time comparison to prevent timing attacks.
        """
        computed = self.compute_signature(payload=payload, secret=secret, timestamp=timestamp)
        return hmac.compare_digest(computed, expected_signature)
