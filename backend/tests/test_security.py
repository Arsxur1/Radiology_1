"""Тесты валидации OIDC-claims и извлечения ролей (ТЗ, FR-12).

Проверка подписи (RS256) требует криптобэкенда и тестируется на стенде; здесь —
чистая логика семантики токена, не зависящая от криптографии.
"""

import time

import pytest

from app.core.roles import Role
from app.core.security import AuthError, extract_roles, validate_claims

ISS = "http://keycloak:8080/realms/medviz"
AUD = "medviz-backend"


def test_extract_known_roles():
    claims = {"realm_access": {"roles": ["radiologist", "offline_access", "admin"]}}
    roles = extract_roles(claims)
    assert roles == {Role.RADIOLOGIST, Role.ADMIN}  # служебные роли Keycloak отброшены


def test_extract_roles_empty():
    assert extract_roles({}) == set()


def test_valid_claims_pass():
    now = time.time()
    claims = {"iss": ISS, "aud": AUD, "exp": now + 300, "nbf": now - 10}
    validate_claims(claims, issuer=ISS, audience=AUD, now=now)  # не бросает


def test_expired_token_rejected():
    now = time.time()
    claims = {"iss": ISS, "aud": AUD, "exp": now - 100}
    with pytest.raises(AuthError, match="истёк"):
        validate_claims(claims, issuer=ISS, audience=AUD, now=now)


def test_wrong_issuer_rejected():
    claims = {"iss": "http://evil/realms/x", "aud": AUD, "exp": time.time() + 300}
    with pytest.raises(AuthError, match="издатель"):
        validate_claims(claims, issuer=ISS, audience=AUD)


def test_wrong_audience_rejected():
    claims = {"iss": ISS, "aud": "other-client", "exp": time.time() + 300}
    with pytest.raises(AuthError, match="аудитории"):
        validate_claims(claims, issuer=ISS, audience=AUD)


def test_audience_via_azp_accepted():
    # Keycloak часто кладёт клиента в azp, а aud=account.
    claims = {"iss": ISS, "aud": "account", "azp": AUD, "exp": time.time() + 300}
    validate_claims(claims, issuer=ISS, audience=AUD)  # не бросает


def test_audience_list_accepted():
    claims = {"iss": ISS, "aud": ["account", AUD], "exp": time.time() + 300}
    validate_claims(claims, issuer=ISS, audience=AUD)
