"""Зависимости FastAPI: аутентификация (OIDC/Keycloak) и роли (FR-12).

Токен проверяется по JWKS Keycloak (подпись RS256, iss, aud, exp); роли берутся
из realm_access.roles. Dev-заголовки X-Debug-* работают ТОЛЬКО при явно включённом
ALLOW_DEBUG_AUTH (изолированные стенды) — в продакшне отключены.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status

from app.core.config import get_settings
from app.core.roles import Role
from app.core.security import AuthError, decode_token, extract_roles


@dataclass
class CurrentUser:
    subject: str
    roles: set[Role]

    def has(self, role: Role) -> bool:
        return role in self.roles

    def require(self, *roles: Role) -> None:
        if not any(r in self.roles for r in roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав",
            )


def _debug_user(subject: str, roles_header: str | None) -> CurrentUser:
    roles = {
        Role(r.strip())
        for r in (roles_header or "").split(",")
        if r.strip() in {e.value for e in Role}
    }
    return CurrentUser(subject=subject, roles=roles)


def get_current_user(
    authorization: str | None = Header(default=None),
    x_debug_subject: str | None = Header(default=None),
    x_debug_roles: str | None = Header(default=None),
) -> CurrentUser:
    """Извлечь пользователя из OIDC-токена (или dev-заголовков при ALLOW_DEBUG_AUTH)."""
    settings = get_settings()

    if x_debug_subject:
        if not settings.allow_debug_auth:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Отладочная аутентификация отключена (ALLOW_DEBUG_AUTH=false)",
            )
        return _debug_user(x_debug_subject, x_debug_roles)

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Требуется аутентификация"
        )

    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = decode_token(
            token,
            jwks_url=settings.oidc_jwks_url,
            issuer=settings.oidc_issuer,
            audience=settings.keycloak_client_id,
        )
    except AuthError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e)) from e

    subject = claims.get("sub") or claims.get("preferred_username")
    if not subject:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="В токене нет subject")

    return CurrentUser(subject=str(subject), roles=extract_roles(claims))


def require_roles(*roles: Role):
    def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        user.require(*roles)
        return user

    return _dep
