"""Unit tests for Webhook Endpoint cryptographic operations:

- Secret generation
- Fernet symmetric encryption & decryption
- HMAC-SHA256 signature computation and constant-time verification
"""

import pytest

from src.utils.endpoint import DEFAULT_SECRET_PREFIX, EndpointSecretCrypto


@pytest.mark.unit
class TestEndpointSecretCrypto:
    @pytest.fixture
    def crypto(self) -> EndpointSecretCrypto:
        # Use a fixed key for deterministic unit tests
        return EndpointSecretCrypto(key="test-encryption-key-for-unit-tests-12345")

    def test_generate_secret_format(self, crypto: EndpointSecretCrypto):
        secret = crypto.generate_secret()
        assert secret.startswith(DEFAULT_SECRET_PREFIX)
        assert len(secret) > len(DEFAULT_SECRET_PREFIX) + 20

        custom_prefix_secret = crypto.generate_secret(prefix="custom_sec_")
        assert custom_prefix_secret.startswith("custom_sec_")

    def test_encrypt_decrypt_roundtrip(self, crypto: EndpointSecretCrypto):
        plaintext = "whsec_test_secret_payload_123456789"
        encrypted = crypto.encrypt(plaintext)

        # Ciphertext should not match plaintext
        assert encrypted != plaintext

        # Decryption restores original plaintext
        decrypted = crypto.decrypt(encrypted)
        assert decrypted == plaintext

    def test_compute_and_verify_signature_success(self, crypto: EndpointSecretCrypto):
        payload = b'{"event": "invoice.paid", "amount": 100}'
        secret = "whsec_secret_key_123"
        timestamp = 1727618400

        sig = crypto.compute_signature(payload=payload, secret=secret, timestamp=timestamp)
        assert isinstance(sig, str)
        assert len(sig) == 64  # SHA-256 hex digest

        # Verification succeeds
        assert (
            crypto.verify_signature(
                payload=payload,
                secret=secret,
                timestamp=timestamp,
                expected_signature=sig,
            )
            is True
        )

    def test_verify_signature_fails_on_tampered_payload(self, crypto: EndpointSecretCrypto):
        payload = b'{"event": "invoice.paid", "amount": 100}'
        tampered_payload = b'{"event": "invoice.paid", "amount": 9999}'
        secret = "whsec_secret_key_123"
        timestamp = 1727618400

        sig = crypto.compute_signature(payload=payload, secret=secret, timestamp=timestamp)

        # Fails when payload is tampered
        assert (
            crypto.verify_signature(
                payload=tampered_payload,
                secret=secret,
                timestamp=timestamp,
                expected_signature=sig,
            )
            is False
        )

    def test_verify_signature_fails_on_tampered_timestamp(self, crypto: EndpointSecretCrypto):
        payload = b'{"event": "invoice.paid"}'
        secret = "whsec_secret_key_123"
        timestamp = 1727618400

        sig = crypto.compute_signature(payload=payload, secret=secret, timestamp=timestamp)

        # Fails when timestamp is altered
        assert (
            crypto.verify_signature(
                payload=payload,
                secret=secret,
                timestamp=timestamp + 100,
                expected_signature=sig,
            )
            is False
        )

    def test_derive_fernet_key_deterministic(self):
        key_1 = EndpointSecretCrypto.derive_fernet_key("my-arbitrary-secret-passphrase")
        key_2 = EndpointSecretCrypto.derive_fernet_key("my-arbitrary-secret-passphrase")

        assert key_1 == key_2
        assert len(key_1) == 44  # Base64 encoded 32 bytes is 44 chars

    def test_cipher_initializes_with_default_settings(self):
        crypto = EndpointSecretCrypto()
        assert crypto.cipher is not None
