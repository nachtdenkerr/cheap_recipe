"""A stand-in for the branch's Neon Auth: an Ed25519 key that signs tokens
the way Managed Better Auth does, installed where app/security.py looks."""

from __future__ import annotations

import time
import uuid
from types import SimpleNamespace

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app import security

BASE_URL = "https://auth.test/neondb/auth"
ORIGIN = "https://auth.test"


class LocalNeonAuth:
    def __init__(self) -> None:
        self.key = Ed25519PrivateKey.generate()
        self.users: dict[str, str] = {}  # email -> sub

    def install(self, monkeypatch) -> None:
        monkeypatch.setenv("NEON_AUTH_BASE_URL", BASE_URL)
        monkeypatch.setenv("NEON_AUTH_JWKS_URL", f"{BASE_URL}/.well-known/jwks.json")
        public = self.key.public_key()
        jwks = SimpleNamespace(get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=public))
        monkeypatch.setattr(security, "_jwks", lambda: jwks)

    def token(
        self, email: str, name: str | None = "Nga", verified: bool = False,
        expires_in: int = 900, sub: str | None = None, audience: str = ORIGIN,
    ) -> str:
        sub = sub or self.users.setdefault(email.lower(), str(uuid.uuid4()))
        now = int(time.time())
        claims = {
            "sub": sub, "id": sub, "email": email, "name": name, "emailVerified": verified,
            "role": "authenticated", "iat": now, "exp": now + expires_in,
            "iss": ORIGIN, "aud": audience,
        }
        return jwt.encode(claims, self.key, algorithm="EdDSA")

    def sign_in(self, client, email: str = "nga@example.com", name: str | None = "Nga", **kw) -> dict:
        """What signing in used to return: the token and the account it opens."""
        token = self.token(email, name, **kw)
        response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200, response.text
        return {"token": token, "user": response.json()}
