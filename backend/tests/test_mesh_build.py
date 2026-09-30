"""3D-модели по подтверждённым маскам (FR-5): гейт на находке, API, геометрия и экспорт."""

from __future__ import annotations

import gzip
import json
import struct
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.api import routes_findings
from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models.imaging import Series, Study
from app.models.ml import (
    ConfirmationStatus,
    Correction,
    CorrectionType,
    Finding,
    FindingSource,
    InferenceResult,
    ModelStatus,
    ModelVersion,
)
from app.models.patient import Patient

H = {"X-Debug-Subject": "dr.mesh", "X-Debug-Roles": "radiologist"}


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "allow_debug_auth", True)
    queued: list = []
    monkeypatch.setattr(routes_findings, "enqueue_mesh", queued.append)
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app, raise_server_exceptions=False)
    c.queued = queued
    yield c
    app.dependency_overrides.clear()


def _finding(db, *, thickness=1.0, mask_spacing=(1.5, 1.5, 1.5), status=ConfirmationStatus.CONFIRMED,
             shadow=False, lossy=False, label_ids=True):
    p = Patient()
    db.add(p)
    db.flush()
    st = Study(patient_id=p.id, study_instance_uid=f"st-{p.id.hex[:8]}", modality="CT",
               study_date=datetime(2026, 9, 1))
    db.add(st)
    db.flush()
    se = Series(study_id=st.id, series_instance_uid=f"se-{p.id.hex[:8]}", modality="CT",
                slice_thickness_mm=thickness, lossy_compressed=lossy, object_prefix=f"s/{p.id.hex[:8]}")
    mv = ModelVersion(name="totalseg", semver="1.0.0", weights_hash="w" * 64, task="segmentation",
                      status=ModelStatus.SHADOW if shadow else ModelStatus.ACTIVE)
    db.add_all([se, mv])
    db.flush()
    ir = InferenceResult(series_id=se.id, model_version_id=mv.id, artifact_ref="masks/s/seg.nii.gz",
                         shadow_run=shadow, metrics={},
                         preprocessing_params={"mask_spacing_mm": list(mask_spacing),
                                               "label_ids": {"liver": [5]} if label_ids else {}})
    db.add(ir)
    db.flush()
    f = Finding(series_id=se.id, inference_result_id=ir.id, coding_system="RadLex", label="Печень",
                measurements={"volume_ml": 1500.0}, coordinates={"structure_key": "liver"},
                source=FindingSource.MODEL, confirmation_status=status)
    db.add(f)
    db.commit()
    return f


def test_confirmed_mask_is_queued(client, db):
    f = _finding(db)
    r = client.post(f"/findings/{f.id}/mesh", headers=H)
    assert r.status_code == 202, r.text
    assert r.json()["mesh"] == {"status": "queued"}
    assert client.queued == [f.id]


@pytest.mark.parametrize("kwargs, reason", [
    ({"status": ConfirmationStatus.PENDING}, "не подтверждена"),
    ({"thickness": 5.0}, "Толщина среза"),
    ({"mask_spacing": (1.5, 1.5, 4.0)}, "Толщина среза"),   # грубая маска — тоже «ступеньки»
    ({"lossy": True}, "с потерями"),
    ({"label_ids": False}, "недоступна"),
])
def test_gate_refuses_with_reason(client, db, kwargs, reason):
    f = _finding(db, **kwargs)
    r = client.post(f"/findings/{f.id}/mesh", headers=H)
    assert r.status_code == 422
    assert reason in r.json()["detail"]
    assert client.queued == []


def test_modified_finding_refused(client, db):
    f = _finding(db)
    db.add(Correction(finding_id=f.id, series_id=f.series_id, correction_type=CorrectionType.MODIFIED,
                      before={}, after={"measurements": {"volume_ml": 1400}}, author="dr"))
    db.commit()
    r = client.post(f"/findings/{f.id}/mesh", headers=H)
    assert r.status_code == 422 and "исправил" in r.json()["detail"]


def test_shadow_run_is_not_disclosed(client, db):
    f = _finding(db, shadow=True)
    assert client.post(f"/findings/{f.id}/mesh", headers=H).status_code == 404


def test_download_is_audited_and_hides_refs(client, db, monkeypatch):
    from app.models.audit import AuditAction, AuditLog
    from app.services import storage

    f = _finding(db)
    assert client.get(f"/findings/{f.id}/mesh.stl", headers=H).status_code == 404  # ещё не построена
    f.coordinates = {**f.coordinates, "mesh": {"status": "ready", "stl": "meshes/a.stl", "glb": "meshes/a.glb",
                                               "faces": 10}}
    db.commit()
    monkeypatch.setattr(storage, "get_object_ref", lambda ref: b"STL:" + ref.encode())
    listed = client.get(f"/findings/series/{f.series_id}", headers=H).json()
    assert listed[0]["mesh"] == {"status": "ready", "faces": 10}   # ссылок на хранилище нет
    r = client.get(f"/findings/{f.id}/mesh.stl", headers=H)
    assert r.status_code == 200 and r.content == b"STL:meshes/a.stl"
    assert r.headers["content-disposition"] == 'attachment; filename="liver.stl"'
    assert client.get(f"/findings/{f.id}/mesh.obj", headers=H).status_code == 404
    assert client.get(f"/findings/{f.id}/mesh.glb", headers={**H, "X-Debug-Roles": "auditor"}).status_code == 403
    rows = db.query(AuditLog).filter(AuditLog.entity_type == "mesh").all()
    assert len(rows) == 1 and rows[0].action == AuditAction.EXPORT and rows[0].details["format"] == "stl"


# --- Геометрия (numpy + scikit-image) ---

def _ellipsoid():
    np = pytest.importorskip("numpy")
    pytest.importorskip("skimage")
    k, j, i = np.mgrid[:50, :50, :30]
    mask = ((i - 15) * 2) ** 2 + (j - 25) ** 2 + (k - 25) ** 2 < 18 ** 2
    affine = np.diag([2.0, 1.0, 1.0, 1.0])
    return np, mask.transpose(2, 1, 0), affine


def test_mesh_volume_matches_mask():
    from app.services.mesh import mask_to_mesh, mesh_stats

    np, mask, affine = _ellipsoid()
    verts, faces, step = mask_to_mesh(mask, affine)
    stats = mesh_stats(verts, faces)
    mask_ml = mask.sum() * 2.0 / 1000
    assert step == 1
    assert abs(stats["volume_ml"] - mask_ml) / mask_ml < 0.03   # сглаживание Таубина без усадки
    again = mask_to_mesh(mask, affine)
    assert np.array_equal(verts, again[0])                        # детерминированность (FR-6)


def test_face_budget_coarsens_step():
    from app.services.mesh import mask_to_mesh

    _, mask, affine = _ellipsoid()
    _, faces, step = mask_to_mesh(mask, affine, max_faces=2000)
    assert step > 1 and len(faces) <= 2000


def test_empty_mask_refused():
    from app.services.mesh import mask_to_mesh

    np, mask, affine = _ellipsoid()
    with pytest.raises(ValueError):
        mask_to_mesh(np.zeros_like(mask), affine)


def test_stl_and_glb_are_well_formed():
    from app.services.mesh import mask_to_mesh, to_glb, to_stl

    np, mask, affine = _ellipsoid()
    verts, faces, _ = mask_to_mesh(mask, affine, max_faces=5000)
    stl = to_stl(verts, faces)
    assert len(stl) == 84 + 50 * len(faces)
    assert struct.unpack("<I", stl[80:84])[0] == len(faces)
    glb = to_glb(verts, faces, name="liver")
    magic, version, length = struct.unpack("<III", glb[:12])
    assert (magic, version, length) == (0x46546C67, 2, len(glb))
    js_len, js_type = struct.unpack("<II", glb[12:20])
    doc = json.loads(glb[20:20 + js_len])
    assert js_type == 0x4E4F534A and doc["asset"]["version"] == "2.0"
    assert doc["accessors"][0]["count"] == len(verts)
    assert doc["accessors"][2]["count"] == faces.size
    assert max(abs(v) for v in doc["accessors"][0]["max"]) < 1.0   # метры, не миллиметры


def test_build_and_store_end_to_end(db):
    np = pytest.importorskip("numpy")
    nib = pytest.importorskip("nibabel")
    pytest.importorskip("skimage")
    from app.services.mesh_builder import build_and_store

    _, mask, affine = _ellipsoid()
    labelmap = np.where(mask, 5, 0).astype(np.uint8)
    labelmap[:3, :3, :3] = 7                                      # чужая структура не попадает в модель
    blob = gzip.compress(nib.Nifti1Image(labelmap, affine).to_bytes())
    f = _finding(db)
    stored = {}

    def store(key, data, ctype):
        stored[key] = (data, ctype)
        return f"meshes/{key}"

    state = build_and_store(db, f.id, load_mask=lambda ref: blob, store=store)
    assert state["status"] == "ready" and state["stl"].endswith(".stl") and state["glb"].endswith(".glb")
    assert abs(state["volume_ml"] - mask.sum() * 2.0 / 1000) < 0.5
    assert {c for _, c in stored.values()} == {"model/stl", "model/gltf-binary"}
    assert f.coordinates["mesh"]["status"] == "ready" and f.coordinates["structure_key"] == "liver"


def test_worker_marks_failed_on_storage_error(db, monkeypatch):
    """Сбой хранилища не оставляет статус «queued» навсегда: failed с понятной причиной."""
    np = pytest.importorskip("numpy")
    nib = pytest.importorskip("nibabel")
    pytest.importorskip("skimage")
    from contextlib import contextmanager

    from app.services import storage
    from app.workers import mesh_tasks

    _, mask, affine = _ellipsoid()
    blob = gzip.compress(nib.Nifti1Image(np.where(mask, 5, 0).astype(np.uint8), affine).to_bytes())
    f = _finding(db)

    @contextmanager
    def session():
        yield db

    def broken_put(*a, **k):
        raise ConnectionError("S3 недоступно")

    monkeypatch.setattr(mesh_tasks, "SessionLocal", session)
    monkeypatch.setattr(storage, "get_object_ref", lambda ref: blob)
    monkeypatch.setattr(storage, "put_object", broken_put)
    state = mesh_tasks.build_mesh(str(f.id))
    assert state["status"] == "failed" and "Технический сбой (ConnectionError)" in state["reason"]
    db.refresh(f)
    assert f.coordinates["mesh"]["status"] == "failed"
