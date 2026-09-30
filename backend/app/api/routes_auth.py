"""Вход через Keycloak (OIDC, Authorization Code + PKCE) и проверка доступа для шлюза.

/auth/config — публичный: браузеру нужно знать, куда идти за входом, ещё до входа.
/auth/check — для nginx auth_request: пускать ли запрос к DICOMweb (снимки).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from app.api.deps import CurrentUser, get_current_user
from app.core.config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/config")
def auth_config() -> dict:
    s = get_settings()
    return {
        # None — клиент возьмёт http(s)://<тот же хост>:8080/realms/<realm>.
        "issuer": s.oidc_issuer if s.keycloak_public_url else None,
        "realm": s.keycloak_realm,
        "client_id": s.web_client_id,
    }


@router.get("/check", status_code=204)
def auth_check(_: CurrentUser = Depends(get_current_user)) -> Response:
    """204 — пользователь аутентифицирован (любая роль видит обезличенные снимки)."""
    return Response(status_code=204)
