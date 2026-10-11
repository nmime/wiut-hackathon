"""Компонент B: посильная выплата (два уровня риска), сумма, capacity_score и confidence.

Формула-ядро (прозрачная), для уровня с допустимой долей перегрузки α:
    база             = наибольший платёж X, при котором прогнозная доля месяцев,
                       где свободный поток < X, не выше α  (по распределению прогноза
                       ЭТОГО бизнеса: учитывает и сезонность, и его собственную точность)
    max_installment  = k × база          — k: калибровочный буфер, один на всех
    cap_m            = k × max(P_α прогноза свободного потока месяца m, 0)  — для графика
    recommended_amt  = PV(max_installment, ставка, срок)

Два уровня (решение выбирает кредитный офицер):
    основной  — α = 10% (полоса P10), k подобран под фактическое покрытие 90%;
    риск      — α = 20% (полоса P20), свой k подобран под покрытие 80%. Больше сумма,
                выше шанс перегрузки; вероятность перегрузки показывается явно.
Оба k выбираются на бэктесте внутри видимой истории (не на тесте).

capacity_score = 100 × средняя по 12 месяцам вероятность того, что свободный поток
месяца >= ref_load × средний приток. Это вероятность измеримого события, а не ручные
веса: её калибровка проверяется на тесте по децилям (eval/).
"""
from __future__ import annotations

import numpy as np

from config import TARGET_COVERAGE, TARGET_COVERAGE_RISK

from models.forecast import ForecastResult
from models.schedule import present_value

HIST_FACTOR = {"no_seasonality": 0.45, "reduced_seasonality": 0.7, "full": 1.0}
# полоса уровня = допустимая доля месяцев с перегрузкой
MAIN_BAND, RISK_BAND = round(1 - TARGET_COVERAGE, 2), round(1 - TARGET_COVERAGE_RISK, 2)


def base_quantity(fr: ForecastResult, band: float = MAIN_BAND) -> float:
    """Наибольший платёж, при котором прогнозная доля месяцев с перегрузкой <= band."""
    lo, hi = 0.0, max(float(fr.free_grid.max()), 0.0)
    if hi <= 0 or expected_overload_share(fr, 1.0) > band:
        return 0.0
    for _ in range(50):
        mid = (lo + hi) / 2
        if expected_overload_share(fr, mid) <= band:
            lo = mid
        else:
            hi = mid
    return lo


def monthly_caps(fr: ForecastResult, k: float, band: float = MAIN_BAND) -> np.ndarray:
    return k * np.maximum(fr.q(band), 0.0)


def max_installment(fr: ForecastResult, k: float, band: float = MAIN_BAND) -> float:
    return k * base_quantity(fr, band)


def expected_overload_share(fr: ForecastResult, payment: float) -> float:
    """Прогнозная доля месяцев, где свободный поток < платежа (по конформному распределению)."""
    if payment <= 0:
        return 0.0
    return float(1.0 - fr.prob_at_least(payment).mean())


def capacity_score(fr: ForecastResult, ref_load: float) -> float:
    thr = ref_load * fr.state["L_in"]
    return float(100.0 * fr.prob_at_least(thr).mean())


def confidence(fr: ForecastResult) -> dict:
    hist = HIST_FACTOR.get(fr.mode, 0.3)
    width = float(np.mean(fr.q(0.9) - fr.q(0.1)))
    rel = width / max(float(fr.in_p50.mean()), 1.0)
    wf = float(np.clip(1 - 0.8 * rel, 0.2, 1.0))
    v = round(hist * wf, 3)
    level = "high" if v >= 0.65 else ("medium" if v >= 0.4 else "low")
    reasons = []
    if fr.mode == "no_seasonality":
        reasons.append("история меньше 12 месяцев: сезонность не оценивается")
    elif fr.mode == "reduced_seasonality":
        reasons.append("история 12–23 месяца: сезонность наблюдалась один раз")
    if rel > 0.5:
        reasons.append(f"широкий интервал прогноза: P90−P10 ≈ {rel:.0%} среднего притока")
    if not reasons:
        reasons.append("длинная история и узкий интервал прогноза")
    return dict(level=level, value=v, history_factor=hist, interval_factor=round(wf, 3),
                relative_interval_width=round(rel, 3), reasons=reasons)


def decomposition(fr: ForecastResult, k: float, band: float = MAIN_BAND,
                  target: float = TARGET_COVERAGE) -> list[dict]:
    """Точное аддитивное разложение посильного платежа (сум/мес)."""
    mean_in = float(fr.in_p50.mean())
    mean_out = float(fr.out_p50.mean())
    debt = float(fr.debt.mean())
    mean_free = mean_in - mean_out - debt
    weak_free = float(np.quantile(fr.free_p50, 0.10))
    base_q = base_quantity(fr, band)
    final = max_installment(fr, k, band)
    items = [
        ("forecast_inflow", "Прогноз среднего месячного притока", mean_in),
        ("operating_outflow", "Операционные расходы (поставщики, зарплата, аренда, налоги)", -mean_out),
        ("existing_debt", "Текущие платежи по кредитам", -debt),
        ("seasonal_dip", "Поправка на слабый месяц (сезонность)", -(mean_free - weak_free)),
        ("uncertainty", f"Поправка на неопределённость: платёж, при котором прогнозная доля месяцев "
                        f"с перегрузкой не выше {band:.0%}", -(weak_free - base_q)),
        ("buffer", f"Калиброванный коэффициент буфера k = {k:.2f} (подобран на валидации "
                   f"под фактическое покрытие {target:.0%})", final - base_q),
    ]
    return [dict(key=a, label=b, value=round(v, 2)) for a, b, v in items]


def _tier(fr, k, band, target, i, term) -> dict:
    mi = max(max_installment(fr, k, band), 0.0)
    return dict(band=f"P{round(band * 100)}", buffer_k=k, target_coverage=target,
                max_installment=round(mi, 2), recommended_amount=round(present_value(mi, i, term), 2),
                expected_overload_share=round(expected_overload_share(fr, mi), 4))


def assess_capacity(fr: ForecastResult, k: float, ref_load: float, annual_rate: float,
                    term: int, k_risk: float | None = None) -> dict:
    i = annual_rate / 12
    main = _tier(fr, k, MAIN_BAND, TARGET_COVERAGE, i, term)
    out = dict(
        max_installment=main["max_installment"],
        recommended_amount=main["recommended_amount"],
        expected_overload_share=main["expected_overload_share"],
        capacity_score=round(capacity_score(fr, ref_load), 1),
        buffer_k=k,
        reference_load=ref_load,
        confidence=confidence(fr),
        decomposition=decomposition(fr, k),
        risk_tier=None,
    )
    if k_risk is not None:
        risk = _tier(fr, k_risk, RISK_BAND, TARGET_COVERAGE_RISK, i, term)
        risk["decomposition"] = decomposition(fr, k_risk, RISK_BAND, TARGET_COVERAGE_RISK)
        risk["label"] = ("Повышенный риск: допустимо до 20% месяцев с перегрузкой, калиброван под покрытие "
                         f"{TARGET_COVERAGE_RISK:.0%} месяцев. Решение о таком уровне — за офицером.")
        out["risk_tier"] = risk
    return out
