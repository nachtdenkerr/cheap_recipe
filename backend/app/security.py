"""Who is calling: a Neon Auth (Managed Better Auth) JWT, verified here.

The browser signs in with Neon Auth directly (frontend/src/auth/neonAuth.ts)
and sends the session's short-lived JWT as `Authorization: Bearer`. It is an
EdDSA token whose keys are at NEON_AUTH_JWKS_URL, issued by — and for — the
origin of NEON_AUTH_BASE_URL. Nothing about passwords lives in this API.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from urllib.parse import urlsplit

import jwt

from cheaprecipe.config import neon_auth_base_url, neon_auth_jwks_url

log = logging.getLogger(__name__)


class AuthNotConfigured(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _jwks() -> jwt.PyJWKClient:
    url = neon_auth_jwks_url()
    if not url:
        raise AuthNotConfigured("NEON_AUTH_JWKS_URL is not set — run `neon deploy` or `neon env pull`.")
    # Keys are cached, and refetched when a token names a kid not seen yet.
    return jwt.PyJWKClient(url, cache_keys=True, lifespan=3600)


def issuer() -> str:
    base = neon_auth_base_url()
    if not base:
        raise AuthNotConfigured("NEON_AUTH_BASE_URL is not set — run `neon deploy` or `neon env pull`.")
    parts = urlsplit(base)
    return f"{parts.scheme}://{parts.netloc}"


def read_token(token: str) -> dict | None:
    """The claims of a valid, unexpired Neon Auth token; None for anything else."""
    try:
        key = _jwks().get_signing_key_from_jwt(token)
        origin = issuer()
        claims = jwt.decode(
            token, key.key, algorithms=["EdDSA"], issuer=origin, audience=origin,
            options={"require": ["exp", "sub", "iss", "aud"]},
        )
    except AuthNotConfigured:
        raise
    except jwt.PyJWTError as exc:
        log.debug("rejected a token: %s", exc)
        return None
    return claims
