"""Password hashing and session tokens, on the standard library alone.

Passwords go through scrypt with a per-user salt. Tokens are
`<user id>.<expiry>.<HMAC>`: stateless, so logging out is the client
forgetting the token, and rotating SECRET_KEY signs everyone out.
"""

import base64
import hashlib
import hmac
import logging
import secrets
import time

from cheaprecipe.config import secret_key

log = logging.getLogger(__name__)

TOKEN_TTL_SECONDS = 7 * 24 * 3600

# OWASP's minimum for scrypt: N=2^17, r=8, p=1 (~128 MiB per hash).
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**17, 8, 1
_SCRYPT_MAXMEM = 256 * 1024 * 1024

_fallback_key: bytes | None = None


def _key() -> bytes:
    global _fallback_key
    configured = secret_key()
    if configured:
        return configured.encode()
    if _fallback_key is None:
        log.warning("SECRET_KEY is not set; sessions will not survive a restart")
        _fallback_key = secrets.token_bytes(32)
    return _fallback_key


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P,
        maxmem=_SCRYPT_MAXMEM,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    candidate = hashlib.scrypt(
        password.encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p),
        maxmem=_SCRYPT_MAXMEM,
    )
    return hmac.compare_digest(candidate, _unb64(digest))


def _sign(payload: str) -> str:
    return _b64(hmac.new(_key(), payload.encode(), hashlib.sha256).digest())


def issue_token(user_id: int, ttl: int = TOKEN_TTL_SECONDS) -> str:
    payload = f"{user_id}.{int(time.time()) + ttl}"
    return f"{payload}.{_sign(payload)}"


def read_token(token: str) -> int | None:
    """The user id a valid, unexpired token carries; None for anything else."""
    try:
        user_id, expires, signature = token.split(".")
        if not hmac.compare_digest(signature, _sign(f"{user_id}.{expires}")):
            return None
        if int(expires) < time.time():
            return None
        return int(user_id)
    except ValueError:
        return None
