"""Реальные движки совмещения (ТЗ, раздел 4: SimpleITK/Elastix либо ANTs).

Подключаются на стенде. Тяжёлые зависимости импортируются лениво. Метрика для
разных модальностей — mutual information (FR-4). Последовательность стадий
(жёсткая → аффинная → деформируемая) обеспечивается вызывающим кодом.
"""

from __future__ import annotations

from app.models.registration import RegistrationStage
from app.services.registration import RegistrationEngine, RegistrationOutput


class ItkRegistrationEngine(RegistrationEngine):
    """Совмещение на SimpleITK (Mattes mutual information). Подключается на стенде."""

    def register(  # pragma: no cover - требует SimpleITK и пиксельных данных
        self, fixed_prefix: str, moving_prefix: str, up_to_stage: RegistrationStage
    ) -> RegistrationOutput:
        # import SimpleITK as sitk
        # 1) загрузить fixed/moving из объектного хранилища
        # 2) rigid → affine → (по запросу) deformable (BSpline), метрика — MattesMI
        # 3) вернуть значение MI, оценку качества и ссылку на трансформацию
        raise NotImplementedError(
            "SimpleITK-регистрация подключается на стенде; см. docs/STAGE-2.md и FR-4"
        )
