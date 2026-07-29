"""Интеграционный тест проверки подписи токена (RS256) через JWKS.

Требует рабочего криптобэкенда python-jose. Там, где он недоступен (отдельные
среды со сломанным бинарным backend), тест пропускается; на стенде — выполняется.
"""

from __future__ import annotations

import pytest


def _jose_ok() -> bool:
    try:
        from jose import jwk, jwt  # noqa: F401

        return True
    except BaseException:  # noqa: BLE001  бинарный backend может паниковать, не ImportError
        return False


pytestmark = pytest.mark.skipif(not _jose_ok(), reason="jose/crypto backend недоступен")


def test_decode_token_roundtrip(monkeypatch):
    import time

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from jose import jwk, jwt

    from app.core import security
    from app.core.roles import Role

    # Сгенерировать пару ключей RSA и собрать JWKS из публичного ключа.
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_jwk = jwk.construct(pem, "RS256").public_key().to_dict()
    public_jwk["kid"] = "test-kid"

    iss = "http://kc/realms/medviz"
    aud = "medviz-backend"
    token = jwt.encode(
        {"sub": "user-1", "iss": iss, "aud": aud, "exp": time.time() + 300,
         "realm_access": {"roles": ["radiologist"]}},
        pem, algorithm="RS256", headers={"kid": "test-kid"},
    )

    # Подменить загрузку JWKS на наш публичный ключ.
    monkeypatch.setattr(security, "_jwks_for", lambda url: _FakeCache([public_jwk]))

    claims = security.decode_token(token, jwks_url="x", issuer=iss, audience=aud)
    assert claims["sub"] == "user-1"
    assert security.extract_roles(claims) == {Role.RADIOLOGIST}


class _FakeCache:
    def __init__(self, keys):
        self._keys = keys

    def get(self):
        return self._keys

    def _refresh(self):
        pass
