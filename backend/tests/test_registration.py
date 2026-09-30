"""Тесты совмещения модальностей (ТЗ, FR-4)."""

from __future__ import annotations

import uuid

import pytest

from app.models.imaging import Series, Study
from app.models.patient import Patient
from app.models.registration import RegistrationReview, RegistrationStage
from app.services import registration
from app.services.registration import (
    STAGE_ORDER,
    RegistrationError,
    StubRegistrationEngine,
    ensure_usable_for_measurements,
    run_registration,
)


def _two_series(db, *, same_patient=True):
    p1 = Patient()
    db.add(p1)
    db.flush()
    p2 = p1 if same_patient else Patient()
    if not same_patient:
        db.add(p2)
        db.flush()

    st1 = Study(patient_id=p1.id, study_instance_uid="ct", modality="CT")
    st2 = Study(patient_id=p2.id, study_instance_uid="mr", modality="MR")
    db.add_all([st1, st2])
    db.flush()
    se1 = Series(study_id=st1.id, series_instance_uid="ct-s", modality="CT", object_prefix="ct/x")
    se2 = Series(study_id=st2.id, series_instance_uid="mr-s", modality="MR", object_prefix="mr/x")
    db.add_all([se1, se2])
    db.flush()
    return se1, se2


def test_stage_order_is_rigid_affine_deformable():
    assert STAGE_ORDER == [
        RegistrationStage.RIGID, RegistrationStage.AFFINE, RegistrationStage.DEFORMABLE
    ]


def test_registration_runs_pending_by_default(db):
    fixed, moving = _two_series(db)
    reg = run_registration(
        db, fixed_series=fixed, moving_series=moving, engine=StubRegistrationEngine()
    )
    # Метрика — mutual information; результат не подтверждён и негоден для измерений.
    assert reg.metric_name == "mutual_information"
    assert reg.metric_value is not None
    assert reg.review_status == RegistrationReview.PENDING
    assert reg.usable_for_measurements() is False


def test_unapproved_registration_blocks_measurements(db):
    fixed, moving = _two_series(db)
    reg = run_registration(
        db, fixed_series=fixed, moving_series=moving, engine=StubRegistrationEngine()
    )
    with pytest.raises(RegistrationError):
        ensure_usable_for_measurements(reg)


class _FakeEngine(StubRegistrationEngine):
    """Как заглушка, но выдаёт себя за настоящий движок (заглушку подтвердить нельзя)."""

    def __init__(self, **quality):
        self.extra = quality

    def register(self, fixed_prefix, moving_prefix, up_to_stage):
        out = super().register(fixed_prefix, moving_prefix, up_to_stage)
        out.quality = {**out.quality, "engine": "simpleitk", **self.extra}
        return out


def test_approved_registration_usable(db):
    fixed, moving = _two_series(db)
    reg = run_registration(
        db, fixed_series=fixed, moving_series=moving, engine=_FakeEngine()
    )
    registration.review_registration(
        db, registration_id=reg.id, approved=True, physician="dr"
    )
    assert reg.usable_for_measurements() is True
    ensure_usable_for_measurements(reg)  # не бросает


def test_rejected_registration_still_blocked(db):
    fixed, moving = _two_series(db)
    reg = run_registration(
        db, fixed_series=fixed, moving_series=moving, engine=StubRegistrationEngine()
    )
    registration.review_registration(db, registration_id=reg.id, approved=False, physician="dr")
    assert reg.usable_for_measurements() is False


def test_cannot_register_different_patients(db):
    fixed, moving = _two_series(db, same_patient=False)
    with pytest.raises(RegistrationError, match="разным пациентам"):
        run_registration(
            db, fixed_series=fixed, moving_series=moving, engine=StubRegistrationEngine()
        )


def test_deterministic_metric(db):
    fixed, moving = _two_series(db)
    engine = StubRegistrationEngine()
    a = engine.register("ct/x", "mr/x", RegistrationStage.DEFORMABLE)
    b = engine.register("ct/x", "mr/x", RegistrationStage.DEFORMABLE)
    assert a.metric_value == b.metric_value
    # Более поздняя стадия даёт не меньшую метрику.
    rigid = engine.register("ct/x", "mr/x", RegistrationStage.RIGID)
    assert a.metric_value >= rigid.metric_value


def test_stub_result_cannot_be_approved(db):
    fixed, moving = _two_series(db)
    reg = run_registration(db, fixed_series=fixed, moving_series=moving, engine=StubRegistrationEngine())
    with pytest.raises(registration.RegistrationBlocked, match="заглушка"):
        registration.review_registration(db, registration_id=reg.id, approved=True, physician="dr")
    # Отклонить можно всегда.
    registration.review_registration(db, registration_id=reg.id, approved=False, physician="dr")


def test_folding_blocks_approval(db):
    fixed, moving = _two_series(db)
    warn = [{"code": "folding", "blocking": True, "text": "Деформация со «складками»"}]
    reg = run_registration(db, fixed_series=fixed, moving_series=moving, engine=_FakeEngine(warnings=warn))
    with pytest.raises(registration.RegistrationBlocked, match="складк"):
        registration.review_registration(db, registration_id=reg.id, approved=True, physician="dr")


def test_queued_registration_cannot_be_approved(db):
    fixed, moving = _two_series(db)
    reg = registration.queue_registration(db, fixed_series=fixed, moving_series=moving)
    assert reg.metric_value is None and reg.quality == {"status": "queued"}
    with pytest.raises(registration.RegistrationBlocked, match="очереди"):
        registration.review_registration(db, registration_id=reg.id, approved=True, physician="dr")
    out = _FakeEngine().register("ct/x", "mr/x", RegistrationStage.AFFINE)
    registration.apply_output(db, reg, out, requested=RegistrationStage.DEFORMABLE)
    assert reg.quality["status"] == "done" and reg.quality["requested_stage"] == "deformable"
    assert reg.stage == RegistrationStage.AFFINE   # достигнутая стадия, а не запрошенная
    registration.review_registration(db, registration_id=reg.id, approved=True, physician="dr")
    assert reg.usable_for_measurements()


def test_api_queues_real_engine(db, monkeypatch):
    from fastapi.testclient import TestClient

    from app.api import routes_registration
    from app.core.config import get_settings
    from app.db.session import get_db
    from app.main import app

    monkeypatch.setattr(get_settings(), "allow_debug_auth", True)
    queued = []
    monkeypatch.setattr(routes_registration, "enqueue_registration", lambda rid, actor: queued.append(rid))
    app.dependency_overrides[get_db] = lambda: db
    try:
        c = TestClient(app, raise_server_exceptions=False)
        h = {"X-Debug-Subject": "dr", "X-Debug-Roles": "radiologist"}
        fixed, moving = _two_series(db)
        db.commit()
        r = c.post("/registration", json={"fixed_series_id": str(fixed.id), "moving_series_id": str(moving.id)},
                   headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["quality"] == {"status": "queued"} and body["review_blockers"] == ["Совмещение ещё в очереди"]
        assert [str(q) for q in queued] == [body["id"]]
        assert c.post(f"/registration/{body['id']}/review", json={"approved": True}, headers=h).status_code == 409
        assert c.get(f"/registration/{body['id']}/preview", headers=h).status_code == 404
    finally:
        app.dependency_overrides.clear()


# --- Настоящий движок на синтетическом фантоме (SimpleITK) ---

def _phantom():
    np = pytest.importorskip("numpy")
    sitk = pytest.importorskip("SimpleITK")
    z, y, x = np.mgrid[:48, :64, :64].astype(np.float32)
    a = np.zeros((48, 64, 64), np.float32)
    a[((x - 32) / 26) ** 2 + ((y - 32) / 19) ** 2 < 1] = 100
    a[((x - 22) ** 2 + (y - 32) ** 2 + (z - 24) ** 2) < 8 ** 2] = 300
    a[(abs(x - 42) < 5) & (abs(y - 28) < 6) & (abs(z - 24) < 12)] = 200
    fixed = sitk.GetImageFromArray(a)
    fixed.SetSpacing((1.5, 1.5, 2.5))
    t = sitk.Euler3DTransform((0, 0, 0), 0.0, 0.0, float(np.deg2rad(8)), (5.0, -4.0, 3.0))
    t.SetCenter(fixed.TransformContinuousIndexToPhysicalPoint([32, 32, 24]))
    moved = sitk.Resample(fixed, fixed, t, sitk.sitkLinear, 0)
    # Другая «модальность»: инверсия контраста внутри тела.
    moving = sitk.Cast(400 - moved, sitk.sitkFloat32) * sitk.Cast(moved > 0, sitk.sitkFloat32)
    return sitk, fixed, moving


def test_itk_engine_recovers_rigid_motion_across_contrast():
    from app.services.registration_engines import ItkRegistrationEngine

    sitk, fixed, moving = _phantom()
    stored = {}
    engine = ItkRegistrationEngine(load=lambda p: fixed if p == "f" else moving,
                                   store=lambda k, d, t: stored.setdefault(k, (d, t)) and f"masks/{k}")
    out = engine.register("f", "m", RegistrationStage.AFFINE)
    q = out.quality
    assert q["stages"]["rigid"]["mi"] > q["mi_initial"]
    assert out.stage == RegistrationStage.AFFINE
    assert q["stages"]["affine"]["dice"] > 0.93 > q["dice_initial"]
    assert q["warnings"] == []
    assert out.transform_ref.endswith(".tfm") and q["preview_ref"].endswith(".png")
    png = next(d for k, (d, t) in stored.items() if t == "image/png")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    again = engine.register("f", "m", RegistrationStage.AFFINE)
    assert again.metric_value == out.metric_value   # детерминированность (FR-6)


def test_quality_warnings_rules():
    from app.services.registration_engines import quality_warnings

    q = {"mi_initial": 0.5, "dice_initial": 0.9,
         "stages": {"rigid": {"mi": 0.6, "dice": 0.92},
                    "affine": {"mi": 0.4, "dice": 0.5, "accepted": False},
                    "deformable": {"mi": 0.3, "dice": 0.6, "accepted": True, "jacobian_min": -0.2}}}
    codes = {w["code"]: w["blocking"] for w in quality_warnings(q)}
    assert codes["affine_reverted"] is False
    assert codes["folding"] is True
    assert "mi_decreased" in codes and "low_overlap" in codes


# --- Совмещённая серия для просмотрщика ---

def test_resampled_series_matches_fixed_geometry(tmp_path):
    """Moving, пересчитанная на сетку fixed по верному преобразованию, совпадает с fixed
    и читается обратно как обычная DICOM-серия той же геометрии."""
    np = pytest.importorskip("numpy")
    sitk, fixed, _ = _phantom()
    from pydicom.dataset import Dataset

    from app.services.registration_publish import dataset_bytes, resampled_series

    t = sitk.Euler3DTransform((0, 0, 0), 0.0, 0.0, float(np.deg2rad(8)), (5.0, -4.0, 3.0))
    t.SetCenter(fixed.TransformContinuousIndexToPhysicalPoint([32, 32, 24]))
    moving = sitk.Resample(fixed, fixed, t, sitk.sitkLinear, 0)       # m(x) = f(t(x))
    template = Dataset()
    template.PatientID, template.StudyInstanceUID, template.FrameOfReferenceUID = "PSEUDO-1", "2.25.5", "2.25.6"
    series = resampled_series(fixed, moving, t.GetInverse(), template, registration_id="r1",
                              modality="MR", description="MR совмещено, подтверждено врачом")
    assert len(series) == fixed.GetSize()[2]
    assert {s.StudyInstanceUID for s in series} == {"2.25.5"} and series[0].FrameOfReferenceUID == "2.25.6"
    assert list(series[0].ImageType) == ["DERIVED", "SECONDARY", "REGISTERED"]
    again = resampled_series(fixed, moving, t.GetInverse(), template, registration_id="r1",
                             modality="MR", description="x")
    assert again[3].SOPInstanceUID == series[3].SOPInstanceUID    # повторная публикация заменяет серию

    for i, ds in enumerate(series):
        (tmp_path / f"{i:03d}.dcm").write_bytes(dataset_bytes(ds))
    reader = sitk.ImageSeriesReader()
    reader.SetFileNames(reader.GetGDCMSeriesFileNames(str(tmp_path)))
    back = reader.Execute()
    assert back.GetSize() == fixed.GetSize()
    assert np.allclose(back.GetSpacing(), fixed.GetSpacing(), atol=1e-3)
    assert np.allclose(back.GetOrigin(), fixed.GetOrigin(), atol=1e-3)
    a, b = sitk.GetArrayFromImage(fixed), sitk.GetArrayFromImage(back).astype(np.float32)
    inner = a[6:-6, 8:-8, 8:-8].ravel(), b[6:-6, 8:-8, 8:-8].ravel()   # край поля обзора — вне moving
    assert np.corrcoef(*inner)[0, 1] > 0.95


def test_publish_only_after_approval(db, monkeypatch):
    from fastapi.testclient import TestClient

    from app.api import routes_registration
    from app.core.config import get_settings
    from app.db.session import get_db
    from app.main import app

    monkeypatch.setattr(get_settings(), "allow_debug_auth", True)
    queued = []
    monkeypatch.setattr(routes_registration, "enqueue_publish", queued.append)
    app.dependency_overrides[get_db] = lambda: db
    try:
        c = TestClient(app, raise_server_exceptions=False)
        h = {"X-Debug-Subject": "dr", "X-Debug-Roles": "radiologist"}
        fixed, moving = _two_series(db)
        reg = run_registration(db, fixed_series=fixed, moving_series=moving, engine=_FakeEngine())
        db.commit()
        assert c.post(f"/registration/{reg.id}/publish", headers=h).status_code == 409   # не подтверждено
        registration.review_registration(db, registration_id=reg.id, approved=True, physician="dr")
        db.commit()
        researcher = {**h, "X-Debug-Roles": "researcher"}
        assert c.post(f"/registration/{reg.id}/publish", headers=researcher).status_code == 403
        r = c.post(f"/registration/{reg.id}/publish", headers=h)
        assert r.status_code == 200 and r.json()["quality"]["published"] == {"status": "queued"}
        assert queued == [reg.id]
    finally:
        app.dependency_overrides.clear()


def test_deformable_stage_is_reproducible():
    """B-сплайн оптимизируется многопоточно — повторный прогон обязан совпасть (FR-6)."""
    from app.services.registration_engines import register_images

    sitk, fixed, moving = _phantom()
    fixed, moving = fixed[::2, ::2, ::2], moving[::2, ::2, ::2]      # меньше вокселей — быстрее тест
    t1, q1, _, _ = register_images(fixed, moving, RegistrationStage.DEFORMABLE)
    t2, q2, _, _ = register_images(fixed, moving, RegistrationStage.DEFORMABLE)
    assert q1["stages"] == q2["stages"]
    p = fixed.TransformContinuousIndexToPhysicalPoint([10, 12, 8])
    assert t1.TransformPoint(p) == t2.TransformPoint(p)


def test_preview_orientation_does_not_depend_on_index_order():
    """Превью строится в анатомических осях: тот же объём, записанный с другим порядком
    индексов (направляющие косинусы −1), даёт ту же картинку."""
    from app.services.registration_engines import checkerboard_png

    sitk, fixed, _ = _phantom()
    flipped = sitk.Flip(fixed, [True, True, False])        # физически тот же объём
    assert flipped.GetDirection() != fixed.GetDirection()
    identity = sitk.Transform(3, sitk.sitkIdentity)
    assert checkerboard_png(fixed, fixed, identity) == checkerboard_png(flipped, flipped, identity)


def test_list_registrations_for_patient(db, monkeypatch):
    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.db.session import get_db
    from app.main import app

    monkeypatch.setattr(get_settings(), "allow_debug_auth", True)
    app.dependency_overrides[get_db] = lambda: db
    try:
        c = TestClient(app, raise_server_exceptions=False)
        h = {"X-Debug-Subject": "dr", "X-Debug-Roles": "radiologist"}
        fixed, moving = _two_series(db)
        first = run_registration(db, fixed_series=fixed, moving_series=moving, engine=_FakeEngine())
        second = registration.queue_registration(db, fixed_series=fixed, moving_series=moving)
        db.commit()
        rows = c.get(f"/registration?patient_id={fixed.study.patient_id}", headers=h).json()
        assert {r["id"] for r in rows} == {str(first.id), str(second.id)}
        other = c.get(f"/registration?patient_id={uuid.uuid4()}", headers=h).json()
        assert other == []
        assert c.get(f"/registration?patient_id={fixed.study.patient_id}",
                     headers={**h, "X-Debug-Roles": "auditor"}).status_code == 403
    finally:
        app.dependency_overrides.clear()
