# Дообучение на публичных датасетах: MIMIC-CXR-JPG, VinDr-CXR, VinDr-PCXR

Офлайн-контур FR-10 п. 3: обучение идёт **только на отдельном обучающем сервере**
заказчика. На продуктивном сервере запуск технически запрещён (`MEDVIZ_CONTOUR`).

## 1. Что и зачем

| Датасет | Популяция | Что даёт |
|---|---|---|
| MIMIC-CXR-JPG | взрослые (США, стационар) | крупнейший набор; CheXpert-метки на исследование |
| VinDr-CXR | взрослые (Вьетнам) | метки нескольких врачей + рамки находок |
| **VinDr-PCXR** | **дети** | главный набор для NCMC (детский центр) |

Модель учится только на **находках** (выпот, кардиомегалия, консолидация, пневмоторакс…),
а метки уровня **диагноза** (пневмония, туберкулёз, ХОБЛ, опухоль, бронхит…) явно
исключаются — SR-1 и раздел 8 ТЗ. Выход модели — черновик для подтверждения врачом,
кандидат стартует в **SHADOW**. Используется предобученная сеть + дообучение
(обучение «с нуля» ТЗ исключает).

> Решение о допустимости классификатора *находок* в первой версии нужно подтвердить
> у владельца ТЗ: раздел 8 исключает «классификацию патологии», а SR-1 разрешает
> «находки и степень уверенности». Мы трактуем модель находок-черновиков как допустимую.

## 2. Доступ к данным (делает каждый, кто работает с данными)

1. Аккаунт на physionet.org.
2. Обучение CITI «Data or Specimens Only Research».
3. Запрос credentialed-доступа, затем **подписать DUA** на странице каждого проекта
   (MIMIC-CXR-JPG, VinDr-CXR, VinDr-PCXR).
4. **Юрист:** проверить лицензии на использование в коммерческом медизделии
   до регистрации (ТЗ, вопрос 34).

### Правила DUA — обязательно

- Данные хранятся только на вашем обучающем сервере. Никому не передавать.
- **Не загружать изображения, CSV, отчёты или любые записи в онлайн-ИИ-сервисы —
  включая этот чат.** Мне присылайте только сводные `*.report.json` (счётчики меток и
  имена меток), без построчных данных.
- Не пытаться повторно идентифицировать пациентов.

## 3. Сервер

- GPU от 24 ГБ видеопамяти (обучение на CPU практически нереально).
- Диск: MIMIC-CXR-JPG — сотни ГБ; VinDr — десятки–сотни ГБ DICOM.
- Linux, Python 3.11.

```bash
git clone <репозиторий> && cd Radiology_1/backend
pip install -e ".[train]"
export MEDVIZ_CONTOUR=training
```

Скачивание (со своими учётными данными PhysioNet, версию смотрите на странице проекта):
```bash
wget -r -N -c -np --user <логин> --ask-password https://physionet.org/files/mimic-cxr-jpg/<версия>/
wget -r -N -c -np --user <логин> --ask-password https://physionet.org/files/vindr-cxr/<версия>/
wget -r -N -c -np --user <логин> --ask-password https://physionet.org/files/vindr-pcxr/<версия>/
```

## 4. Запуск по шагам

```bash
# 1) Манифесты + отчёт по меткам (что сопоставлено, что исключено, что неизвестно)
python -m app.training.cli manifest --dataset mimic-cxr-jpg --root /data/mimic-cxr-jpg/<версия> --out work/mimic.jsonl
python -m app.training.cli manifest --dataset vindr-cxr     --root /data/vindr-cxr/<версия>     --out work/vindr.jsonl
python -m app.training.cli manifest --dataset vindr-pcxr    --root /data/vindr-pcxr/<версия>    --out work/pcxr.jsonl
```
Откройте `work/*.report.json`: раздел `unmapped` — метки, которых нет в карте.
**Пришлите мне список их имён** — дополню `label_map.py` (решение по каждой — за врачом).

```bash
# 2) Замороженный тест — ДО обучения, отдельно для взрослых и детей (FR-10 п. 4)
python -m app.training.cli freeze --manifest work/mimic.jsonl work/vindr.jsonl --population adult     --out work/frozen_adult.json
python -m app.training.cli freeze --manifest work/pcxr.jsonl                   --population pediatric --out work/frozen_peds.json

# 3) Обучение — раздельно (п. 1.2 ТЗ)
python -m app.training.cli train --population adult --name cxr_findings_adult --semver 0.1.0 \
  --manifest work/mimic.jsonl work/vindr.jsonl --frozen work/frozen_adult.json \
  --root mimic-cxr-jpg=/data/mimic-cxr-jpg/<версия> --root vindr-cxr=/data/vindr-cxr/<версия> \
  --out runs/adult_v0.1.0 --epochs 5

python -m app.training.cli train --population pediatric --age-max <по описанию VinDr-PCXR> \
  --name cxr_findings_peds --semver 0.1.0 --manifest work/pcxr.jsonl --frozen work/frozen_peds.json \
  --root vindr-pcxr=/data/vindr-pcxr/<версия> --out runs/peds_v0.1.0 --epochs 10

# 4) Оценка на замороженном тесте (журналируется в frozen_evaluations.jsonl)
python -m app.training.cli evaluate --run runs/peds_v0.1.0 --manifest work/pcxr.jsonl \
  --frozen work/frozen_peds.json --root vindr-pcxr=/data/vindr-pcxr/<версия>
```

Результат прогона: `model.pt`, `model_card.json` (происхождение, коды выходов,
исключённые метки, метрики, границы применимости), `registration.json`, `history.json`.

## 5. Путь в клинику

1. `POST /models/candidates` с телом `registration.json` → кандидат в **SHADOW**.
2. Теневой прогон на живом потоке NCMC, сравнение с заключениями врачей.
3. Локальное валидационное исследование — отдельно дети/взрослые (раздел 9).
4. Гейт продвижения (`/models/{id}/evaluate` → `/promote`) — решение ответственного лица.

Публичные данные — это другие аппараты и другое население (США, Вьетнам), поэтому
локальная валидация на NCMC обязательна: без неё модель остаётся в SHADOW.

## 6. Как это становится самообучением

Правки врачей на NCMC (FR-9) экспортируются `POST /learning/export` и добавляются к
публичным данным при следующем дообучении → новый кандидат → SHADOW → гейт → откат
при необходимости. Публичные датасеты дают старт, данные площадки — адаптацию.
