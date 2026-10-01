"""Интеграционный тест проверки подписи токена (RS256) через JWKS.

Требует рабочего криптобэкенда PyJWT (cryptography). Там, где он недоступен (отдельные
среды со сломанным бинарным backend), тест пропускается; на стенде — выполняется.
"""

from __future__ import annotations

import pytest


def _crypto_ok() -> bool:
    try:
        import jwt  # noqa: F401
        from jwt.algorithms import RSAAlgorithm  # noqa: F401

        return True
    except BaseException:  # noqa: BLE001  бинарный backend может паниковать, не ImportError
        return False


pytestmark = pytest.mark.skipif(not _crypto_ok(), reason="PyJWT/crypto backend недоступен")


def test_decode_token_roundtrip(monkeypatch):
    import json
    import time

    import jwt
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from jwt.algorithms import RSAAlgorithm

    from app.core import security
    from app.core.roles import Role

    # Сгенерировать пару ключей RSA и собрать JWKS из публичного ключа.
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_jwk = json.loads(RSAAlgorithm.to_jwk(priv.public_key()))
    public_jwk["kid"] = "test-kid"

    iss = "http://kc/realms/medviz"
    aud = "medviz-backend"
    token = jwt.encode(
        {"sub": "user-1", "iss": iss, "aud": aud, "exp": time.time() + 300,
         "realm_access": {"roles": ["radiologist"]}},
        pem, algorithm="RS256", headers={"kid": "test-kid"},
    )

    # Чужой ключ и истёкший срок — отказ.
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode({"sub": "x", "iss": iss, "aud": aud, "exp": time.time() + 300},
                        other, algorithm="RS256", headers={"kid": "test-kid"})
    expired = jwt.encode({"sub": "x", "iss": iss, "aud": aud, "exp": time.time() - 3600},
                         pem, algorithm="RS256", headers={"kid": "test-kid"})

    # Подменить загрузку JWKS на наш публичный ключ.
    monkeypatch.setattr(security, "_jwks_for", lambda url: _FakeCache([public_jwk]))

    claims = security.decode_token(token, jwks_url="x", issuer=iss, audience=aud)
    assert claims["sub"] == "user-1"
    assert security.extract_roles(claims) == {Role.RADIOLOGIST}
    for bad in (forged, expired, token[:-4] + "AAAA"):
        with pytest.raises(security.AuthError):
            security.decode_token(bad, jwks_url="x", issuer=iss, audience=aud)
    # Подмена алгоритма на «none» не проходит.
    none_tok = jwt.encode({"sub": "x", "iss": iss, "aud": aud, "exp": time.time() + 300}, None,
                          algorithm="none", headers={"kid": "test-kid"})
    with pytest.raises(security.AuthError):
        security.decode_token(none_tok, jwks_url="x", issuer=iss, audience=aud)


class _FakeCache:
    def __init__(self, keys):
        self._keys = keys

    def get(self):
        return self._keys

    def _refresh(self):
        pass
