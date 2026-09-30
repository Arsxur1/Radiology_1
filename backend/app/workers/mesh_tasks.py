"""Построение 3D-модели в воркере (FR-5): маска из S3 → STL + GLB в бакет meshes."""

from __future__ import annotations

import logging
import uuid

from app.db.session import SessionLocal
from app.services.mesh_builder import MeshRefused, build_and_store, set_mesh_state
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="mesh.build")
def build_mesh(finding_id: str) -> dict:  # pragma: no cover - нужны nibabel, scikit-image и S3
    from app.core.config import get_settings
    from app.models.ml import Finding
    from app.services import storage

    bucket = get_settings().bucket_meshes
    with SessionLocal() as db:
        try:
            state = build_and_store(
                db, uuid.UUID(finding_id), load_mask=storage.get_object_ref,
                store=lambda key, data, ctype: storage.put_object(bucket, key, data, content_type=ctype),
            )
        except (MeshRefused, ValueError, ImportError, OSError) as e:
            db.rollback()
            logger.warning("3D-модель для находки %s не построена: %s", finding_id, e)
            f = db.get(Finding, uuid.UUID(finding_id))
            if f is not None:
                set_mesh_state(f, {"status": "failed", "reason": str(getattr(e, "reason", e))})
            state = {"status": "failed", "reason": str(e)}
        db.commit()
        return state
