"""Зависимости FastAPI: аутентификация (OIDC/Keycloak) и роли (FR-12).

На этапе 1 проверка подписи токена вынесена в TODO подключения JWKS Keycloak;
структура ролей и извлечение subject готовы. Для локальной разработки допускается
заголовок X-Debug-Roles (только при DEBUG-развёртывании).
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status

from app.core.roles import Role


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


def get_current_user(
    authorization: str | None = Header(default=None),
    x_debug_subject: str | None = Header(default=None),
    x_debug_roles: str | None = Header(default=None),
) -> CurrentUser:
    """Извлечь пользователя из OIDC-токена.

    Production: валидировать JWT по JWKS Keycloak и читать realm_access.roles.
    Dev: заголовки X-Debug-* (использовать только на изолированных стендах).
    """
    if x_debug_subject:
        roles = {
            Role(r.strip())
            for r in (x_debug_roles or "").split(",")
            if r.strip() in {e.value for e in Role}
        }
        return CurrentUser(subject=x_debug_subject, roles=roles)

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Требуется аутентификация"
        )
    # TODO(этап 1→2): валидация JWT по JWKS Keycloak.
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Подключение JWKS Keycloak выполняется при развёртывании стенда",
    )


def require_roles(*roles: Role):
    def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        user.require(*roles)
        return user

    return _dep
