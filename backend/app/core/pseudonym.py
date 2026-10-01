"""Ключевая псевдонимизация (SR-9): HMAC-SHA256 с секретом площадки.

Псевдоним пациента, обезличенные UID и токены идентификаторов для сопоставления пациентов
выводятся из реальных значений с ключом PSEUDONYM_KEY. Без ключа обратить их нельзя:
раньше был SHA-256 без ключа, и по псевдониму перебором номеров карт (их немного)
восстанавливался пациент. Ключ хранится только на сервере платформы (.env) и в
резервной копии рядом с ключом бэкапа; в обезличенный контур он не попадает.

Потеря ключа не раскрывает данных, но новые исследования уже известных пациентов
перестанут связываться с ними автоматически (понадобится ручное объединение).
"""

from __future__ import annotations

import hashlib
import hmac

TOKEN_PREFIX = "h1:"


class PseudonymKeyMissing(RuntimeError):
    """PSEUDONYM_KEY не задан — обезличивание без ключа запрещено."""


def _key() -> bytes:
    from app.core.config import get_settings

    key = get_settings().pseudonym_key
    if not key:
        raise PseudonymKeyMissing(
            "PSEUDONYM_KEY не задан в .env (сгенерировать: openssl rand -hex 32) — приём остановлен, "
            "чтобы не создавать обратимые псевдонимы")
    return key.encode()


def digest(purpose: str, value: str) -> bytes:
    """HMAC-SHA256(ключ, «назначение|значение»): разные назначения не совпадают между собой."""
    return hmac.new(_key(), f"{purpose}|{value}".encode(), hashlib.sha256).digest()


def identifier_token(id_type: str, normalized_value: str) -> str:
    """Токен идентификатора для сопоставления пациентов в доверенном контуре (не обратим)."""
    return TOKEN_PREFIX + digest(f"identifier:{id_type}", normalized_value).hex()[:40]


def key_state() -> tuple[bool, str]:
    """Для «Состояния системы»: ключ задан и не учебный."""
    from app.core.config import get_settings

    key = get_settings().pseudonym_key
    if not key:
        return False, "PSEUDONYM_KEY не задан — приём остановлен (сгенерировать: openssl rand -hex 32)"
    if key.startswith("change_me") or len(key) < 32:
        return False, "PSEUDONYM_KEY учебный или короткий — задать свой (openssl rand -hex 32) до приёма данных"
    return True, "задан"
