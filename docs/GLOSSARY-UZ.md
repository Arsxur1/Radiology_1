# Глоссарий заключений: русский → узбекский (латиница)

**Статус: черновой перевод, требует проверки врачом-рентгенологом — носителем языка.**
Пока проверка не завершена, при выборе узбекского языка интерфейс показывает предупреждение.
Правки вносить в `backend/app/services/i18n_uz.py`; после проверки — `UZ_GLOSSARY_APPROVED = True`.
Коды и числа в заключении не переводятся (SR-1).

## Находки рентгенографии ОГК

| Код | Русский | Узбекский (черновик) | Исправление врача |
|---|---|---|---|
| CXR-000 | Без патологических изменений | Patologik o‘zgarishlarsiz | |
| CXR-100 | Консолидация (уплотнение) | Konsolidatsiya (zichlashish) | |
| CXR-101 | Инфильтрация | Infiltratsiya | |
| CXR-102 | Ателектаз / коллапс | Atelektaz / kollaps | |
| CXR-103 | Очаг / узел | O‘choq / tugun | |
| CXR-104 | Образование (mass) | Hajmli hosila | |
| CXR-105 | Полость / каверна | Bo‘shliq / kaverna | |
| CXR-106 | Интерстициальный паттерн | Interstitsial o‘zgarishlar | |
| CXR-107 | Милиарная диссеминация | Miliar tarqalish | |
| CXR-108 | Матовое стекло | «Xira shisha» belgisi | |
| CXR-109 | Гиперинфляция / вздутие | Giperinflyatsiya | |
| CXR-110 | Бронхоэктазы | Bronxoektazlar | |
| CXR-111 | Фиброз / рубцовые изменения | Fibroz / chandiqli o‘zgarishlar | |
| CXR-112 | Узел / образование (неуточн.) | Tugun / hosila (aniqlanmagan) | |
| CXR-113 | Затенение (неуточнённое) | Soyalanish (aniqlanmagan) | |
| CXR-114 | Отёк лёгких (рентгенологический признак) | O‘pka shishi (rentgenologik belgi) | |
| CXR-115 | Эмфизема | Emfizema | |
| CXR-116 | Кальцинат | Kalsinat | |
| CXR-117 | Киста лёгкого | O‘pka kistasi | |
| CXR-200 | Плевральный выпот | Plevral bo‘shliqda suyuqlik | |
| CXR-201 | Пневмоторакс | Pnevmotoraks | |
| CXR-202 | Утолщение плевры | Plevraning qalinlashuvi | |
| CXR-203 | Иные изменения плевры | Plevradagi boshqa o‘zgarishlar | |
| CXR-300 | Перибронхиальные изменения | Peribronxial o‘zgarishlar | |
| CXR-301 | Сужение / компрессия дыхательных путей | Nafas yo‘llarining torayishi / siqilishi | |
| CXR-302 | Инородное тело | Yot jism | |
| CXR-400 | Расширение корня / лимфаденопатия | O‘pka ildizining kengayishi / limfadenopatiya | |
| CXR-401 | Расширение средостения | Ko‘ks oralig‘ining kengayishi | |
| CXR-402 | Образование средостения | Ko‘ks oralig‘i hosilasi | |
| CXR-403 | Расширение аорты | Aortaning kengayishi | |
| CXR-404 | Расширение лёгочной артерии | O‘pka arteriyasining kengayishi | |
| CXR-405 | Смещение средостения | Ko‘ks oralig‘ining siljishi | |
| CXR-406 | Расширение кардиомедиастинальной тени | Yurak-ko‘ks oralig‘i soyasining kengayishi | |
| CXR-500 | Кардиомегалия | Kardiomegaliya | |
| CXR-501 | Аномалия положения сердца / situs | Yurak joylashuvi anomaliyasi / situs | |
| CXR-600 | Перелом ребра | Qovurg‘a sinishi | |
| CXR-601 | Сколиоз / деформация грудной клетки | Skolioz / ko‘krak qafasi deformatsiyasi | |
| CXR-602 | Перелом костей грудной клетки (неуточн.) | Ko‘krak qafasi suyaklarining sinishi (aniqlanmagan) | |
| CXR-603 | Перелом ключицы | O‘mrov suyagi sinishi | |
| CXR-700 | Положение эндотрахеальной трубки | Endotraxeal naycha holati | |
| CXR-701 | Положение назогастрального зонда | Nazogastral zond holati | |
| CXR-702 | Положение центрального катетера | Markaziy kateter holati | |
| CXR-703 | Наличие устройств / катетеров | Qurilmalar / kateterlar mavjudligi | |

## Анатомические структуры (сегментация КТ/МРТ)

| Ключ | Русский | Узбекский (черновик) | Исправление врача |
|---|---|---|---|
| lung_upper_lobe_left | Верхняя доля левого лёгкого | Chap o‘pka yuqori bo‘lagi | |
| lung_lower_lobe_left | Нижняя доля левого лёгкого | Chap o‘pka pastki bo‘lagi | |
| lung_upper_lobe_right | Верхняя доля правого лёгкого | O‘ng o‘pka yuqori bo‘lagi | |
| lung_middle_lobe_right | Средняя доля правого лёгкого | O‘ng o‘pka o‘rta bo‘lagi | |
| lung_lower_lobe_right | Нижняя доля правого лёгкого | O‘ng o‘pka pastki bo‘lagi | |
| heart | Сердце | Yurak | |
| aorta | Аорта | Aorta | |
| trachea | Трахея | Traxeya | |
| esophagus | Пищевод | Qizilo‘ngach | |
| vertebrae_thoracic | Грудные позвонки | Ko‘krak umurtqalari | |
| liver | Печень | Jigar | |
| spleen | Селезёнка | Taloq | |
| kidney_left | Левая почка | Chap buyrak | |
| kidney_right | Правая почка | O‘ng buyrak | |
| pancreas | Поджелудочная железа | Oshqozon osti bezi | |
| gallbladder | Жёлчный пузырь | O‘t pufagi | |
| stomach | Желудок | Oshqozon | |
| urinary_bladder | Мочевой пузырь | Siydik pufagi | |
| vertebrae_lumbar | Поясничные позвонки | Bel umurtqalari | |
| brain | Головной мозг | Bosh miya | |
| ventricles | Желудочки мозга | Miya qorinchalari | |
| hippocampus_left | Левый гиппокамп | Chap gippokamp | |
| hippocampus_right | Правый гиппокамп | O‘ng gippokamp | |

## Слова шаблона

| Русский | Узбекский (черновик) |
|---|---|
| объём | hajm |
| мл | ml |
| размеры | o‘lchamlari |
| измерения отсутствуют | o‘lchovlar yo‘q |
| структура | tuzilma |
