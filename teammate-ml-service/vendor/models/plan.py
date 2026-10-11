"""Сборка предложения по кредиту: аннуитет vs адаптивный график + предложения при невыполнимости.

Один и тот же код используется API и скриптом оценки (eval/), чтобы метрики описывали
ровно то, что видит офицер.

Два уровня посильности: основной (полоса P10, покрытие 90%) и, если задан k_risk,
повышенный риск (полоса P20, покрытие 80%). Запрошенная сумма проверяется сначала на
основном уровне, затем на рисковом; какой уровень принять — решает офицер.
"""
from __future__ import annotations

import numpy as np

from config import MAX_TERM
from features.calendar import idx_to_str
from models.capacity import (MAIN_BAND, RISK_BAND, expected_overload_share, max_installment,
                             monthly_caps)
from models.forecast import ForecastResult
from models.schedule import (TOL, amortize, annuity_payment, max_feasible_principal,
                             present_value, solve_adaptive)


def payment_caps(caps12: np.ndarray, first_forecast_idx: int, pay_months: list[int]) -> np.ndarray:
    """cap для каждого месяца платежа; за горизонтом 12 мес. профиль повторяется."""
    return np.array([caps12[(m - first_forecast_idx) % 12] for m in pay_months])


def _rows(P, i, payments, months, caps):
    out = []
    for r, m, c in zip(amortize(P, i, payments), months, caps):
        r.update(month=idx_to_str(m), capacity=round(float(c), 2),
                 over_capacity=bool(r["payment"] > c + TOL))
        for k in ("payment", "interest", "principal", "balance"):
            r[k] = round(r[k], 2)
        out.append(r)
    return out


def _tier_eval(fr, k, band, amount, i, term, pay_months, f0) -> dict:
    """Посильность суммы на одном уровне: аннуитет и адаптивный график против cap этого уровня."""
    caps12 = monthly_caps(fr, k, band)
    caps = payment_caps(caps12, f0, pay_months)
    mi = max(max_installment(fr, k, band), 0.0)
    A = annuity_payment(amount, i, term)
    res = dict(mi=mi, caps12=caps12, caps=caps, A=A,
               within_annuity=bool(mi > 0 and A <= mi * 1.005 + TOL),
               adaptive_ok=fr.mode != "no_seasonality" and caps.max() > 0,
               sol=None, within_adaptive=False, reason_na=None)
    if fr.mode == "no_seasonality":
        res["reason_na"] = "история меньше 12 месяцев: сезонность не оценивается, предлагается аннуитет"
    elif caps.max() <= 0:
        res["reason_na"] = ("прогнозная capacity равна нулю во всех месяцах срока: перераспределение "
                            "платежей не поможет, нужен меньший платёж или дополнительное обеспечение")
    if res["adaptive_ok"]:
        # форма графика — прогноз свободного потока P50 (выбрано на val), потолок — cap_m уровня
        shape = payment_caps(np.maximum(fr.free_p50, 0.0), f0, pay_months)
        sol = solve_adaptive(amount, i, caps, shape=shape)
        if sol["status"] == "ok":
            res["sol"] = sol
            res["within_adaptive"] = sol["within_capacity"]
        else:
            res["adaptive_ok"] = False
            res["reason_na"] = f"решатель не нашёл график: {sol.get('message')}"
    res["fits"] = res["within_annuity"] or res["within_adaptive"]
    return res


def _max_amount(t: dict, i: float, term: int) -> float:
    m = present_value(t["mi"], i, term)
    if t["adaptive_ok"]:
        m = max(m, max_feasible_principal(i, t["caps"]))
    return m


def plan_loan(fr: ForecastResult, k: float, annual_rate: float, term: int,
              amount: float | None = None, issue_idx: int | None = None,
              k_risk: float | None = None) -> dict:
    i = annual_rate / 12
    f0 = fr.months[0]
    issue_idx = f0 if issue_idx is None else issue_idx
    if not (f0 - 1 <= issue_idx <= f0 + 11):
        raise ValueError(f"issue_month должен быть между {idx_to_str(f0 - 1)} и {idx_to_str(f0 + 11)}")
    pay_months = [issue_idx + j for j in range(1, term + 1)]
    mi_main = max(max_installment(fr, k, MAIN_BAND), 0.0)
    mi_risk = max(max_installment(fr, k_risk, RISK_BAND), 0.0) if k_risk is not None else 0.0

    source = "requested" if amount else "recommended"
    if not amount:
        amount = present_value(mi_main, i, term)
    notes: list[str] = []
    if amount <= 0:
        risk_amt = 0.0
        if mi_risk > 0:
            probe = _tier_eval(fr, k_risk, RISK_BAND, present_value(mi_risk, i, term), i, term,
                               pay_months, f0)
            risk_amt = round(_max_amount(probe, i, term), 2)
        if risk_amt > 0:
            notes.append(f"на уровне повышенного риска (P20) возможна сумма до {risk_amt / 1e6:.1f} млн сум "
                         "(с адаптивным графиком) — передайте её в requested_amount, чтобы построить график")
        return dict(amount=0.0, amount_source=source, term_months=term, annual_rate=annual_rate,
                    issue_month=idx_to_str(issue_idx), annuity_payment=0.0, status="no_capacity",
                    capacity_tier="main", adaptive_available=False,
                    adaptive_unavailable_reason="посильная выплата основного уровня по прогнозу равна нулю",
                    annuity=[], adaptive=None, comparison=None,
                    suggestions=dict(reason="прогнозный свободный поток в слабые месяцы не покрывает "
                                            "платёж основного уровня", max_amount_for_term=0.0,
                                     min_term_for_amount=None,
                                     max_amount_risk_tier=risk_amt if k_risk is not None else None),
                    notes=notes + ["прогноз свободного денежного потока в слабые месяцы (P10) <= 0"],
                    _caps=payment_caps(monthly_caps(fr, k), f0, pay_months), _pay_months=pay_months)

    main = _tier_eval(fr, k, MAIN_BAND, amount, i, term, pay_months, f0)
    risk = (_tier_eval(fr, k_risk, RISK_BAND, amount, i, term, pay_months, f0)
            if k_risk is not None else None)

    if main["fits"]:
        tier, status = main, "within_capacity"
    elif risk is not None and risk["fits"]:
        tier, status = risk, "within_risk_capacity"
        notes.append("сумма превышает посильную на основном уровне (P10, покрытие 90%), но укладывается "
                     "в уровень повышенного риска (P20, покрытие 80%); прогнозная доля месяцев с "
                     f"перегрузкой при аннуитете — {expected_overload_share(fr, tier['A']):.0%}. "
                     "Решение — за офицером")
    else:
        # показываем caps уровня, на котором есть хоть какая-то capacity
        tier = risk if (risk is not None and main["mi"] <= 0 and risk["mi"] > 0) else main
        no_cap = main["mi"] <= 0 and (risk is None or risk["mi"] <= 0)
        status = "no_capacity" if no_cap else "exceeds_capacity"

    caps, A = tier["caps"], tier["A"]
    ann_p = np.full(term, A)
    annuity = _rows(amount, i, ann_p, pay_months, caps)
    adaptive = comparison = ad_p = None
    if tier["sol"] is not None:
        ad_p = tier["sol"]["payments"]
        adaptive = _rows(amount, i, ad_p, pay_months, caps)
        ann_over = np.maximum(ann_p - caps, 0)
        ad_over = np.maximum(ad_p - caps, 0)
        ann_int = sum(r["interest"] for r in annuity)
        ad_int = sum(r["interest"] for r in adaptive)
        comparison = dict(
            annuity_overload_months=int((ann_over > TOL).sum()),
            adaptive_overload_months=int((ad_over > TOL).sum()),
            annuity_overload_volume=round(float(ann_over.sum()), 2),
            adaptive_overload_volume=round(float(ad_over.sum()), 2),
            annuity_total_interest=round(ann_int, 2), adaptive_total_interest=round(ad_int, 2),
            interest_difference=round(ad_int - ann_int, 2))

    if not tier["within_annuity"] and tier["within_adaptive"]:
        notes.append("аннуитет превышает посильный платёж, но адаптивный график укладывается "
                     "в прогнозную capacity каждого месяца")
    if any(m - f0 >= 12 for m in pay_months):
        notes.append("срок длиннее горизонта прогноза: для месяцев за 12-м сезонный профиль "
                     "повторён без роста, уверенность ниже")

    suggestions = None
    if status != "within_capacity":
        min_term = None
        for n in range(term + 1, MAX_TERM + 1):
            if annuity_payment(amount, i, n) <= main["mi"]:
                min_term = n
                break
            if main["adaptive_ok"]:
                pm = [issue_idx + j for j in range(1, n + 1)]
                if max_feasible_principal(i, payment_caps(main["caps12"], f0, pm)) >= amount - 1:
                    min_term = n
                    break
        reason = ("запрошенная сумма превышает посильную на основном уровне: платёж не укладывается "
                  "в прогнозный свободный поток с буфером" if main["mi"] > 0 else
                  "прогнозный свободный поток в слабые месяцы не покрывает платёж основного уровня")
        suggestions = dict(reason=reason, max_amount_for_term=round(_max_amount(main, i, term), 2),
                           min_term_for_amount=min_term,
                           max_amount_risk_tier=round(_max_amount(risk, i, term), 2) if risk else None)

    return dict(amount=round(float(amount), 2), amount_source=source, term_months=term,
                annual_rate=annual_rate, issue_month=idx_to_str(issue_idx),
                annuity_payment=round(A, 2), status=status,
                capacity_tier="risk" if tier is risk else "main",
                adaptive_available=tier["adaptive_ok"], adaptive_unavailable_reason=tier["reason_na"],
                annuity=annuity, adaptive=adaptive, comparison=comparison, suggestions=suggestions,
                notes=notes, _caps=caps, _pay_months=pay_months, _adaptive_payments=ad_p)
