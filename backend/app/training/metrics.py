"""Метрики качества (чистый Python, детерминированно).

AUROC считается ранговым методом (Манна–Уитни) с учётом связей; замаскированные
метки (None) исключаются. Если в выборке один класс — метрика не определена (None).
"""

from __future__ import annotations


def auroc(y_true: list[int | None], y_score: list[float]) -> float | None:
    pairs = [(s, t) for t, s in zip(y_true, y_score, strict=True) if t is not None]
    pos = sum(1 for _, t in pairs if t == 1)
    neg = len(pairs) - pos
    if pos == 0 or neg == 0:
        return None
    ordered = sorted(pairs, key=lambda p: p[0])
    rank_sum_pos = 0.0
    i = 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1][0] == ordered[i][0]:
            j += 1
        avg_rank = (i + j) / 2 + 1  # ранги с 1, связи — средний ранг
        rank_sum_pos += avg_rank * sum(1 for k in range(i, j + 1) if ordered[k][1] == 1)
        i = j + 1
    return round((rank_sum_pos - pos * (pos + 1) / 2) / (pos * neg), 6)


def per_code_auroc(
    codes: list[str], y_true: list[list[int | None]], y_score: list[list[float]]
) -> dict[str, float | None]:
    return {
        code: auroc([row[i] for row in y_true], [row[i] for row in y_score])
        for i, code in enumerate(codes)
    }


def mean_defined(values: dict[str, float | None]) -> float | None:
    defined = [v for v in values.values() if v is not None]
    return round(sum(defined) / len(defined), 6) if defined else None
