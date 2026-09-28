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
исключённые метки, метрики, **пороги по каждой находке**, границы применимости),
`registration.json`, `history.json`.

Пороги (`operating_points`) подбираются на **валидации** лучшей эпохи по индексу
Юдена — не на замороженном тесте. Находка-черновик создаётся, только если
уверенность модели не ниже порога. Код без порога модель не выдаёт.

## 5. Путь в клинику

1. Скопировать `model.pt` на продуктивный сервер как
   `$MEDVIZ_MODELS_DIR/<weights_hash>.pt` (хеш сверяется при загрузке — подменённые
   веса не запустятся).
2. Админка → «Модели» → вставить `registration.json` → кандидат в **SHADOW**
   (или `POST /models/candidates`).
3. **Теневой прогон** начинается сам: каждый новый рентген ОГК (CR/DX) после приёма
   проходит через действующую модель и всех кандидатов. Находки кандидата пишутся
   с пометкой «теневой прогон» и врачу **не показываются никогда** — даже после
   продвижения.
4. Админка → «Сравнить с заключениями» (`GET /models/{id}/shadow-report`):
   по исследованиям с подписанным заключением — расхождения (черновик, который врач
   не включил), пропуски (находка врача, которой нет у модели), по каждому коду и
   по каждому аппарату. Доля расхождений подставляется в гейт как доля отклонений.
5. Локальное валидационное исследование — отдельно дети/взрослые (раздел 9).
6. Гейт продвижения (`/models/{id}/evaluate` → `/promote`) — решение ответственного лица.

Публичные данные — это другие аппараты и другое население (США, Вьетнам), поэтому
локальная валидация на NCMC обязательна: без неё модель остаётся в SHADOW.

## 6. Как это становится самообучением

```
врач подтверждает / отклоняет / добавляет находки, подписывает заключение
        ↓  POST /learning/site-manifest  (продуктивный сервер, роль researcher/admin)
export.json  — метки по сериям, псевдонимные ключи, без пикселей и PHI
        ↓  перенос на обучающий сервер + копия бакета images (mc mirror)
python -m app.training.cli import-site --json export.json --out work/ncmc.jsonl
python -m app.training.cli freeze --manifest work/ncmc.jsonl --population pediatric --out work/frozen_ncmc_peds.json
python -m app.training.cli train ... --manifest work/pcxr.jsonl work/ncmc.jsonl \
       --root vindr-pcxr=/data/vindr-pcxr/<версия> --root ncmc=/data/ncmc-images --semver 0.2.0
        ↓
новый кандидат → SHADOW → сравнение с заключениями → гейт → ASSIST (откат в один клик)
```

Как решения врача превращаются в метки:

| Решение врача | Метка |
|---|---|
| подтвердил/изменил находку ИИ, добавил свою находку | 1 |
| заменил код находки ИИ на другой | исходный код — 0, новый — 1 |
| отклонил находку ИИ | 0 |
| заключение подписано — всё, что врач не отметил | 0 («без патологии» = 1, если находок нет) |
| заключение не подписано — всё, что врач не отметил | маска (не учится) |
| находки теневого прогона | не используются никогда |

Разделение на train/validate/test — детерминированно по пациенту (один пациент
всегда в одной части). Серии без возраста не экспортируются: нельзя отнести к
взрослым или детям. Замороженный тест площадки формируется один раз — дальше
новые пациенты теста в обучение не попадают.
