"""Рабочие точки (пороги) по каждой находке (ТЗ, FR-10, SR-1).

Модель выдаёт вероятность; находка-черновик создаётся только при уверенности не
ниже порога, подобранного на ВАЛИДАЦИИ (не на замороженном тесте). Порог — по
индексу Юдена (max чувствительность + специфичность − 1). Если по коду нет обоих
классов в валидации, рабочей точки нет и модель этот код не выдаёт.
"""

from __future__ import annotations


def youden_threshold(truths: list[int | None], scores: list[float]) -> dict | None:
    pairs = [(float(s), int(t)) for t, s in zip(truths, scores, strict=True) if t is not None]
    n_pos = sum(t for _, t in pairs)
    n_neg = len(pairs) - n_pos
    if n_pos == 0 or n_neg == 0:
        return None
    best: dict | None = None
    for cut in sorted({s for s, _ in pairs}):
        tp = sum(1 for s, t in pairs if t == 1 and s >= cut)
        tn = sum(1 for s, t in pairs if t == 0 and s < cut)
        sens, spec = tp / n_pos, tn / n_neg
        j = sens + spec - 1
        # При равенстве J берём больший порог — меньше ложных черновиков.
        if best is None or j >= best["youden"]:
            best = {"threshold": cut, "sensitivity": sens, "specificity": spec, "youden": j}
    best.update({"n_pos": n_pos, "n_neg": n_neg})
    return best


def operating_points(
    codes: list[str], truths: list[list[int | None]], scores: list[list[float]]
) -> dict[str, dict]:
    """Порог по каждому коду; коды без рабочей точки опускаются."""
    out: dict[str, dict] = {}
    for i, code in enumerate(codes):
        op = youden_threshold([row[i] for row in truths], [row[i] for row in scores])
        if op is not None:
            out[code] = op
    return out
