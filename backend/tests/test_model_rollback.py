"""FR-10 п. 6: мгновенный откат модели — без гейта, поэтому строго ограничен."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models.audit import AuditLog
from app.models.ml import ModelStatus, ModelVersion
from app.services import model_registry
from app.services.model_registry import PromotionError, PromotionGate

T0 = datetime(2026, 9, 1, tzinfo=UTC)


def _mv(db, semver, status, days=0, name="cxr_peds"):
    m = ModelVersion(name=name, semver=semver, weights_hash=f"w{semver}", applicability={}, status=status,
                     task="classification", operating_points={}, installed_at=T0 + timedelta(days=days))
    db.add(m)
    db.flush()
    return m


def _promote(db, m):
    model_registry.promote(db, candidate_id=m.id, gate=PromotionGate(ok=True), actor="adm", justification="ok")


@pytest.fixture
def line(db):
    """v1 работала, v2 работала, v3 сейчас ACTIVE; v4 — кандидат в SHADOW; другая линейка рядом."""
    v1 = _mv(db, "1.0.0", ModelStatus.ACTIVE, 0)
    v2 = _mv(db, "1.1.0", ModelStatus.SHADOW, 10)
    _promote(db, v2)
    v3 = _mv(db, "1.2.0", ModelStatus.SHADOW, 20)
    _promote(db, v3)
    v4 = _mv(db, "2.0.0", ModelStatus.SHADOW, 30)
    other = _mv(db, "9.0.0", ModelStatus.ACTIVE, 0, name="xrv_all")
    db.commit()
    return v1, v2, v3, v4, other


def _status(db, *ms):
    for m in ms:
        db.refresh(m)
    return [m.status for m in ms]


def test_emergency_rollback_of_active_returns_previous(db, line):
    v1, v2, v3, v4, other = line
    active = model_registry.rollback(db, to_version_id=v3.id, actor="adm", reason="рост отклонений")
    assert active.id == v2.id                                       # предыдущая, а не самая старая
    assert _status(db, v1, v2, v3, v4, other) == [
        ModelStatus.RETIRED, ModelStatus.ACTIVE, ModelStatus.RETIRED, ModelStatus.SHADOW, ModelStatus.ACTIVE]
    rec = db.query(AuditLog).order_by(AuditLog.seq.desc()).first()
    assert rec.details == {"event": "rollback", "reason": "рост отклонений", "from": str(v3.id), "to": str(v2.id)}


def test_rollback_to_chosen_retired_version(db, line):
    v1, v2, v3, *_ = line
    assert model_registry.rollback(db, to_version_id=v1.id, actor="adm", reason="v2 и v3 хуже").id == v1.id
    assert _status(db, v1, v2, v3) == [ModelStatus.ACTIVE, ModelStatus.RETIRED, ModelStatus.RETIRED]


def test_shadow_candidate_cannot_bypass_gate(db, line):
    *_, v3, v4, _ = line
    with pytest.raises(PromotionError, match="через гейт"):
        model_registry.rollback(db, to_version_id=v4.id, actor="adm", reason="быстрее")
    assert _status(db, v3, v4) == [ModelStatus.ACTIVE, ModelStatus.SHADOW]


def test_reason_required_and_nothing_changes(db, line):
    *_, v3, _, _ = line
    for reason in ("", "   "):
        with pytest.raises(PromotionError, match="причина"):
            model_registry.rollback(db, to_version_id=v3.id, actor="adm", reason=reason)
    assert _status(db, v3) == [ModelStatus.ACTIVE]


def test_single_version_line_is_switched_off(db):
    only = _mv(db, "1.0.0", ModelStatus.ACTIVE)
    assert model_registry.rollback(db, to_version_id=only.id, actor="adm", reason="сбой") is None
    assert _status(db, only) == [ModelStatus.RETIRED]               # ИИ линейки отключён, просмотр работает


def test_api(db, line, monkeypatch):
    v1, v2, v3, v4, _ = line
    monkeypatch.setattr(get_settings(), "allow_debug_auth", True)
    app.dependency_overrides[get_db] = lambda: db
    try:
        c = TestClient(app)
        h = {"X-Debug-Subject": "adm", "X-Debug-Roles": "admin"}
        r = c.post(f"/models/{v3.id}/rollback", json={"reason": "сбой"}, headers=h)
        assert r.status_code == 200 and r.json()["active"]["semver"] == "1.1.0"
        assert c.post(f"/models/{v4.id}/rollback", json={"reason": "x"}, headers=h).status_code == 409
        assert c.post(f"/models/{v2.id}/rollback", json={"reason": ""}, headers=h).status_code == 409
        assert c.post("/models/00000000-0000-0000-0000-000000000000/rollback", json={"reason": "x"},
                      headers=h).status_code == 404
        h["X-Debug-Roles"] = "radiologist"
        assert c.post(f"/models/{v1.id}/rollback", json={"reason": "x"}, headers=h).status_code == 403
    finally:
        app.dependency_overrides.clear()
