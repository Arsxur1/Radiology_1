# Матрица трассируемости: ТЗ → реализация

Соответствие требований ТЗ элементам кода этапа 1. «Задел» — структура готова,
наполнение на указанном этапе. Помогает приёмке (раздел 10) и будущей регистрации.

## Требования безопасности пациента (раздел 3)

| ID | Требование | Где реализовано / заложено |
|---|---|---|
| SR-1 | Нет формулировок диагноза, только находки/измерения/уверенность | `models/ml.py::Finding` (коды, измерения; нет поля «диагноз»); `services/report_draft.py` только перекладывает числа/коды в текст, ничего не добавляя |
| SR-2 | Включение результата — активное действие врача, авто-принятие запрещено | `ConfirmationStatus.PENDING` по умолчанию; нет операции «принять всё» |
| SR-3 | В ASSIST версия модели зафиксирована, автообновление запрещено технически | `ModelVersion.status`, контур FR-10; проверка перехода `core/modes.py` |
| SR-4 | Отказ ИИ → режим просмотрщика, доступ к изображениям сохраняется | `api/routes_health.py::ready` (ai изолирован); просмотр не зависит от воркеров |
| SR-5 | Трассировка: версия модели, хеш весов, серия, время, препроцессинг | `models/ml.py::InferenceResult` (все поля), `ModelVersion.weights_hash` |
| SR-6 | Отклонение одним действием фиксируется как обучающий сигнал | `models/ml.py::Correction` (`REJECTED`), задел UI этап 2 |
| SR-7 | Отказ при выходе за границы применимости, без «пониженной уверенности» | **Реализовано:** `services/applicability.py::check_applicability` (`test_applicability.py`); `ModelVersion.applicability` (JSONB) |
| SR-8 | Аудит-лог только на добавление на уровне прав СУБД | `alembic/versions/0002_audit_append_only.py` (триггер + REVOKE + роль) |
| SR-9 | Обезличивание на границе входа, PHI не покидает контур | `services/anonymization.py`, `models/idmap.py` (отдельная БД postgres-idmap) |

## Модель данных (раздел 5)

| Сущность | Реализация |
|---|---|
| `patient` | `models/patient.py::Patient` (UUID — единственный PK) |
| `patient_identifier` | `models/patient.py::PatientIdentifier` (merge/split, транслитерация) |
| `patient_pseudonym_map` | `models/idmap.py` (идентифицирующий контур) |
| `study` / `series` | `models/imaging.py` (толщина среза, воксель, transfer syntax, lossy) |
| `model_version` | `models/ml.py::ModelVersion` (границы применимости в JSONB) |
| `inference_result` | `models/ml.py::InferenceResult` |
| `correction` | `models/ml.py::Correction` (время в секундах) |
| `finding` | `models/ml.py::Finding` (source, confirmation_status) |
| `report` | `models/ml.py::Report` (собирается только из находок) |
| `audit_log` | `models/audit.py::AuditLog` (append-only, хеш-цепочка) |
| `data_drift_metric` | `models/drift.py::DataDriftMetric` |
| `operating_mode` | `models/audit.py::OperatingModeState` |

## Функциональные требования (раздел 6) — статус на этапе 1

| ID | Требование | Статус |
|---|---|---|
| FR-1 | Приём, обезличивание, дедуп, связывание пациента, резервная папка | **Реализовано:** `services/ingest.py`, `anonymization.py`, `patient_matching.py`, `workers/folder_watcher.py` |
| FR-2 | Просмотр (MPR, оконные пресеты, сравнение) | **Реализовано:** OHIF (`frontend/config/ohif.js`), `api/routes_studies.py` |
| FR-3 | Сегментация + правки → correction | **Реализовано (каркас):** `services/segmentation.py`, `api/routes_segmentation.py`, автозапуск `workers/segmentation_tasks.py`; реальная модель — на GPU-стенде |
| FR-4 | Совмещение модальностей | Задел (этап 6) |
| FR-5 | 3D-модели, отказ при недостаточной толщине среза | **Реализовано (гейт):** `services/mesh.py::can_build_mesh`; геометрия — на стенде |
| FR-6 | Измерения, детерминированность | **Реализовано:** `services/measurements.py` (`test_measurements.py`) |
| FR-7 | Сравнение во времени (без ИИ) | **Реализовано:** `services/temporal.py`, `temporal_repo.py`, `api/routes_temporal.py` (`test_temporal.py`) |
| FR-8 | Черновик заключения из подтверждённых находок | **Реализовано:** `services/report_draft.py`, `report_repo.py`, `report_export.py`, `api/routes_reports.py` (`test_report_draft.py`, `test_report_export.py`) |
| FR-9 | Захват обучающих данных + экспорт с фильтрами | **Реализовано:** `services/corrections.py`, `services/dataset_export.py`, `api/routes_findings.py`, `api/routes_learning.py` |
| FR-10 | Контур развития моделей (PCCP): гейт продвижения, откат | **Реализовано (каркас):** `services/model_registry.py`, `api/routes_models.py`; интеграция реальных пайплайнов — этап 7 |
| FR-11 | Контроль дрейфа: доля отклонений по срезам, новый аппарат | **Реализовано:** `services/drift.py`, `api/routes_learning.py` |
| FR-12 | Роли и аудит | **Реализовано:** `core/roles.py`, `api/deps.py`, `api/routes_audit.py` |

## Критерии приёмки (раздел 10)

Автоматизированы в `test_acceptance_criteria.py` и `test_integration_flow.py`
(см. `docs/ACCEPTANCE.md`).

| Критерий | Как проверяется |
|---|---|
| Полная трассируемость | `InferenceResult` + `audit_log`; `GET /audit`; `test_traceability_inference_and_findings` |
| Воспроизводимость | Детерминированные UID/псевдонимы и измерения; `test_reproducibility_*` |
| Отказ вне границ применимости | `services/applicability.py`; `POST /segmentation` → 422; `test_refusal_out_of_range` |
| Отказ ИИ не ломает просмотр | Изоляция воркеров; `GET /ready`; автосегментация no-op без активной модели |
| Невозможность подмены аудита | Хеш-цепочка (`test_audit_chain_detects_tampering`) + триггер/права СУБД (миграция 0002); `GET /audit/verify` |
| Восстановление из бэкапа | `scripts/backup.sh` + проверка на чистом стенде |
| Сквозной путь целиком | `test_integration_flow.py` (приём→сегментация→правка→заключение) |
