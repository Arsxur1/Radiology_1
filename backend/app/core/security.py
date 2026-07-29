"""Валидация OIDC-токенов Keycloak и извлечение ролей (ТЗ, FR-12).

Проверка подписи по JWKS (RS256), издателя (iss), аудитории (aud) и срока (exp).
Роли берутся из realm_access.roles Keycloak и отображаются на роли платформы.

Библиотека `jose` импортируется лениво внутри функции проверки подписи, чтобы
проблемы бинарного backend в отдельных средах не роняли импорт приложения.
Чистые функции (роли, проверка claims) от неё не зависят и полностью тестируемы.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.core.roles import Role


class AuthError(Exception):
    """Токен недействителен или не проходит проверку."""


def extract_roles(claims: dict) -> set[Role]:
    """Отобразить realm_access.roles Keycloak на роли платформы.

    Неизвестные роли игнорируются (в токене могут быть служебные роли Keycloak).
    """
    realm = claims.get("realm_access") or {}
    raw = realm.get("roles") or []
    known = {r.value for r in Role}
    return {Role(r) for r in raw if r in known}


def validate_claims(
    claims: dict,
    *,
    issuer: str | None,
    audience: str | None,
    now: float | None = None,
    leeway: int = 30,
) -> None:
    """Проверить iss/aud/exp/nbf вне зависимости от подписи. Бросает AuthError.

    Проверка подписи выполняется отдельно (decode_token). Здесь — семантика claims,
    тестируемая без криптографии.
    """
    now = now if now is not None else time.time()

    exp = claims.get("exp")
    if exp is not None and now > float(exp) + leeway:
        raise AuthError("Срок действия токена истёк")

    nbf = claims.get("nbf")
    if nbf is not None and now + leeway < float(nbf):
        raise AuthError("Токен ещё не действителен (nbf)")

    if issuer and claims.get("iss") != issuer:
        raise AuthError(f"Неверный издатель токена: {claims.get('iss')!r}")

    if audience:
        aud = claims.get("aud")
        aud_set = set(aud) if isinstance(aud, list) else {aud}
        # Keycloak часто кладёт клиента в azp, а aud=account — допускаем оба.
        if audience not in aud_set and claims.get("azp") != audience:
            raise AuthError("Токен предназначен другой аудитории")


@dataclass
class _JwksCache:
    url: str
    keys: list = field(default_factory=list)
    fetched_at: float = 0.0
    ttl: float = 3600.0

    def get(self) -> list:
        if not self.keys or (time.time() - self.fetched_at) > self.ttl:
            self._refresh()
        return self.keys

    def _refresh(self) -> None:
        import httpx  # ленивый импорт: чистая логика claims не требует сети

        resp = httpx.get(self.url, timeout=10.0)
        resp.raise_for_status()
        self.keys = resp.json().get("keys", [])
        self.fetched_at = time.time()


_jwks_caches: dict[str, _JwksCache] = {}


def _jwks_for(url: str) -> _JwksCache:
    cache = _jwks_caches.get(url)
    if cache is None:
        cache = _JwksCache(url=url)
        _jwks_caches[url] = cache
    return cache


def decode_token(
    token: str,
    *,
    jwks_url: str,
    issuer: str | None,
    audience: str | None,
) -> dict:
    """Проверить подпись токена по JWKS и вернуть claims. Бросает AuthError."""
    from jose import jwt  # ленивый импорт (см. модульную заметку)
    from jose.exceptions import JWTError

    keys = _jwks_for(jwks_url).get()
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as e:
        raise AuthError("Некорректный заголовок токена") from e

    key = next((k for k in keys if k.get("kid") == header.get("kid")), None)
    if key is None:
        # kid не найден — возможно, ротация ключей; сбросить кэш и повторить один раз.
        _jwks_for(jwks_url)._refresh()
        keys = _jwks_for(jwks_url).get()
        key = next((k for k in keys if k.get("kid") == header.get("kid")), None)
    if key is None:
        raise AuthError("Не найден ключ подписи (kid)")

    try:
        # aud проверяем вручную в validate_claims (Keycloak-специфика azp/account).
        claims = jwt.decode(
            token, key, algorithms=["RS256"], options={"verify_aud": False}
        )
    except JWTError as e:
        raise AuthError("Подпись токена недействительна") from e

    validate_claims(claims, issuer=issuer, audience=audience)
    return claims
