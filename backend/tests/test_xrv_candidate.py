"""Кандидат из открытой модели TorchXRayVision: сопоставление выходов и пороги (без torch)."""

from app.services.model_registry import PromotionError, register_candidate
from app.training.xrv import registration_from_card, xrv_card

PATHOLOGIES = ["Atelectasis", "Consolidation", "Pneumonia", "Effusion", "Cardiomegaly", "Nodule",
               "Mass", "Hernia", "Lung Lesion", "", ""]
PPV80 = [0.727, 0.889, 0.988, 0.613, 0.663, 0.785, 0.931, 0.936, 0.679, float("nan"), float("nan")]


def test_card_maps_findings_and_excludes_diagnoses():
    card = xrv_card(weights_name="densenet121-res224-all", weights_hash="h", pathologies=PATHOLOGIES,
                    description="test", ppv80=PPV80)
    ops = card["operating_points"]
    assert "CXR-200" in ops and ops["CXR-500"]["threshold"] == 0.663
    assert card["excluded_labels"] == ["Pneumonia"] and card["unmapped_outputs"] == ["Hernia"]
    assert all(not c.startswith("Pneu") for c in ops)
    assert card["adapter"] == {"type": "xrv", "weights": "densenet121-res224-all"}
    assert card["initial_status"] == "shadow"


def test_registration_goes_to_shadow_and_validates_adapter(db):
    card = xrv_card(weights_name="densenet121-res224-nih", weights_hash="h", pathologies=PATHOLOGIES,
                    description="t")
    mv = register_candidate(db, actor="admin", **registration_from_card(card))
    assert mv.status.value == "shadow" and mv.adapter["type"] == "xrv"
    bad = {**registration_from_card(card), "adapter": {"type": "xrv", "weights": "evil"}}
    try:
        register_candidate(db, actor="admin", **bad)
        raise AssertionError("неизвестные веса должны отклоняться")
    except PromotionError:
        pass
