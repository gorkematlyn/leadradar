"""Password hashing, token generation and secret encryption."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from leadradar.core.config import get_settings

# Argon2id with OWASP-recommended parameters (19 MiB, t=2, p=1) tuned for a small VDS.
_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1, hash_len=32, salt_len=16)

MIN_PASSWORD_LENGTH = 12


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


# A pre-computed hash used to equalize timing when the account does not exist.
_DUMMY_HASH = _hasher.hash("leadradar-timing-equalizer")


def dummy_verify() -> None:
    verify_password(_DUMMY_HASH, "not-the-password")


def validate_password_strength(password: str) -> list[str]:
    problems: list[str] = []
    if len(password) < MIN_PASSWORD_LENGTH:
        problems.append("password_too_short")
    if len(set(password)) < 6:
        problems.append("password_too_simple")
    if len(password) > 256:
        problems.append("password_too_long")
    return problems


def generate_token(nbytes: int = 32) -> str:
    """Cryptographically secure URL-safe token."""
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """Keyed SHA-256 of a token for storage (session tokens, report tokens)."""
    key = get_settings().session_secret.encode()
    return hmac.new(key, token.encode(), hashlib.sha256).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def _fernet() -> Fernet:
    return Fernet(get_settings().app_encryption_key.encode())


def encrypt_secret(value: str | dict[str, Any]) -> str:
    raw = value if isinstance(value, str) else json.dumps(value)
    return _fernet().encrypt(raw.encode()).decode()


def decrypt_secret(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Unable to decrypt secret; APP_ENCRYPTION_KEY may have changed") from exc


def decrypt_json(token: str | None) -> dict[str, Any]:
    if not token:
        return {}
    return json.loads(decrypt_secret(token))


def generate_recovery_codes(count: int = 10) -> list[str]:
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    codes = []
    for _ in range(count):
        raw = "".join(secrets.choice(alphabet) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


def normalize_recovery_code(code: str) -> str:
    return code.strip().lower().replace(" ", "")
