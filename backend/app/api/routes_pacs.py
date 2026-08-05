"""API коннектора к внешнему PACS (ТЗ, FR-1).

Только администратор. Проверка связи, поиск и запрос выгрузки исследований.
Выгруженные данные проходят обезличивание на границе входа (SR-9).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import CurrentUser, require_roles
from app.core.config import get_settings
from app.core.roles import Role
from app.services import pacs, pacs_dicomweb
from app.services.pacs import PacsNode, PacsUnavailable, StudyQuery, default_node_from_settings

router = APIRouter(prefix="/pacs", tags=["pacs"])


class NodeIn(BaseModel):
    aet: str
    host: str
    port: int
    local_aet: str = "MEDVIZ_RAW"
    dicomweb_base_url: str | None = None


class QueryIn(BaseModel):
    node: NodeIn
    patient_id: str | None = None
    study_date: str | None = None
    modality: str | None = None
    accession_number: str | None = None
    study_instance_uid: str | None = None
    use_dicomweb: bool = False


class MoveIn(BaseModel):
    node: NodeIn
    study_instance_uid: str
    destination_aet: str | None = None


def _node(n: NodeIn) -> PacsNode:
    return PacsNode(
        aet=n.aet, host=n.host, port=n.port,
        local_aet=n.local_aet, dicomweb_base_url=n.dicomweb_base_url,
    )


def _query(q: QueryIn) -> StudyQuery:
    return StudyQuery(
        patient_id=q.patient_id, study_date=q.study_date, modality=q.modality,
        accession_number=q.accession_number, study_instance_uid=q.study_instance_uid,
    )


@router.get("/config")
def pacs_config(_: CurrentUser = Depends(require_roles(Role.ADMIN))) -> dict:
    """Показать настроенный узел PACS из .env (без секретов). Для проверки конфигурации."""
    s = get_settings()
    return {
        "configured": s.pacs_configured,
        "aet": s.pacs_aet,
        "host": s.pacs_host,
        "port": s.pacs_port,
        "local_aet": s.pacs_local_aet,
        "dicomweb_url": s.pacs_dicomweb_url,
        "direction": s.pacs_direction,
    }


def _default_node_or_400() -> PacsNode:
    node = default_node_from_settings()
    if node is None:
        raise HTTPException(
            status_code=400,
            detail="Узел PACS не настроен. Заполните PACS_AET/PACS_HOST/PACS_PORT в .env",
        )
    return node


@router.post("/echo/default")
def echo_default(_: CurrentUser = Depends(require_roles(Role.ADMIN))) -> dict:
    """C-ECHO к настроенному в .env узлу PACS (без передачи параметров)."""
    try:
        result = pacs.echo(_default_node_or_400())
    except PacsUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return {"ok": result.ok, "detail": result.detail}


@router.post("/echo")
def echo(
    node: NodeIn,
    _: CurrentUser = Depends(require_roles(Role.ADMIN)),
) -> dict:
    """C-ECHO: проверка связи с PACS."""
    try:
        result = pacs.echo(_node(node))
    except PacsUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return {"ok": result.ok, "detail": result.detail}


@router.post("/find")
def find(
    payload: QueryIn,
    _: CurrentUser = Depends(require_roles(Role.ADMIN)),
) -> dict:
    """C-FIND / QIDO: поиск исследований в PACS."""
    try:
        if payload.use_dicomweb:
            outcome = pacs_dicomweb.qido_find_studies(_node(payload.node), _query(payload))
        else:
            outcome = pacs.find_studies(_node(payload.node), _query(payload))
    except PacsUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "count": len(outcome.studies),
        "studies": [s.__dict__ for s in outcome.studies],
        "warnings": outcome.warnings,
    }


@router.post("/move")
def move(
    payload: MoveIn,
    _: CurrentUser = Depends(require_roles(Role.ADMIN)),
) -> dict:
    """C-MOVE: PACS выгружает исследование на наш приёмный AE (далее — обезличивание)."""
    try:
        ok = pacs.move_study(
            _node(payload.node), payload.study_instance_uid, payload.destination_aet
        )
    except PacsUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return {"requested": True, "ok": ok}
