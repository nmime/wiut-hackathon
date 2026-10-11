"""Компонент C: адаптивный график платежей (scipy linprog).

Платёж месяца стремится к α·c_m — пропорционально прогнозному свободному потоку месяца c_m
(P50), где α подобрано так, чтобы пропорциональный график ровно гасил кредит: в слабые месяцы
платёж ниже, в сильные — выше. Жёсткие ограничения:
  * полное погашение за срок;
  * платёж >= процентов периода (без отрицательной амортизации);
  * остаток долга не уходит в минус;
  * скачок платежа между соседними месяцами <= jump_frac × аннуитет.
Посильная выплата месяца (cap_m) — мягкое ограничение с большим штрафом: если его
нельзя выполнить, решатель показывает перегрузку явно, а сервис предлагает меньшую
сумму или больший срок. Молчаливых нарушений нет.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import linprog

TOL = 1.0  # сум


def annuity_payment(P: float, i: float, n: int) -> float:
    if n <= 0:
        raise ValueError("срок должен быть > 0")
    return P / n if i == 0 else P * i / (1 - (1 + i) ** -n)


def present_value(pmt: float, i: float, n: int) -> float:
    return pmt * n if i == 0 else pmt * (1 - (1 + i) ** -n) / i


def amortize(P: float, i: float, payments) -> list[dict]:
    rows, bal = [], P
    for m, p in enumerate(payments, 1):
        interest = bal * i
        principal = p - interest
        bal = bal - principal
        rows.append(dict(n=m, payment=float(p), interest=float(interest),
                         principal=float(principal), balance=float(max(bal, 0.0) if abs(bal) < 1 else bal)))
    return rows


def _balance_matrix(n: int, i: float) -> np.ndarray:
    """G[m-1, j-1] = (1+i)^(m-j) при j<=m: B_m = P(1+i)^m - (G p)_m."""
    G = np.zeros((n, n))
    for m in range(n):
        for j in range(m + 1):
            G[m, j] = (1 + i) ** (m - j)
    return G


def _hard_rows(n: int, i: float, P: float):
    """Ограничения A_ub p <= b_ub (процентный пол, неотрицательный остаток) и A_eq p = b_eq."""
    G = _balance_matrix(n, i)
    A, b = [], []
    for m in range(n):  # процентный пол: p_m >= i * B_{m-1}
        row = np.zeros(n)
        row[m] = -1.0
        if m > 0:
            row[:m] -= i * G[m - 1, :m]
        A.append(row)
        b.append(-i * P * (1 + i) ** m)
    for m in range(n - 1):  # B_m >= 0
        A.append(G[m].copy())
        b.append(P * (1 + i) ** (m + 1))
    A_eq = G[n - 1][None, :]
    b_eq = [P * (1 + i) ** n]
    return np.array(A), np.array(b), A_eq, np.array(b_eq)


def solve_adaptive(P: float, i: float, caps: np.ndarray, jump_frac: float = 0.6,
                   shape: np.ndarray | None = None) -> dict:
    """Решается в единицах аннуитетного платежа: в абсолютных сумах (~1e8) HiGHS теряет точность."""
    caps = np.asarray(caps, float)
    s = annuity_payment(P, i, len(caps))
    shape = caps if shape is None else np.asarray(shape, float)
    res = _solve_adaptive_scaled(P / s, i, caps / s, jump_frac, shape / s)
    if res["status"] == "ok":
        res["payments"] = res["payments"] * s
        res["overload"] = res["overload"] * s
        res["annuity"] = res["annuity"] * s
        res["within_capacity"] = bool(res["overload"].sum() <= TOL * len(caps))
    return res


def _solve_adaptive_scaled(P: float, i: float, caps: np.ndarray, jump_frac: float,
                           shape: np.ndarray) -> dict:
    n = len(caps)
    A_pay = annuity_payment(P, i, n)
    c = np.maximum(shape, 0.1 * max(shape.mean(), 0) + 1e-6)
    # α: пропорциональный график c_m·α гасит кредит ровно
    disc = (1 + i) ** (n - 1 - np.arange(n))
    alpha = P * (1 + i) ** n / float((c * disc).sum())
    target = alpha * c

    A_h, b_h, A_eq_p, b_eq = _hard_rows(n, i, P)
    nv = 3 * n  # p, o (перегрузка), d (отклонение от цели)
    Z = np.zeros((n, n))
    I = np.eye(n)
    rows, rhs = [], []
    rows.append(np.hstack([A_h, np.zeros((A_h.shape[0], 2 * n))]))
    rhs.append(b_h)
    rows.append(np.hstack([I, -I, Z]))  # p - o <= cap
    rhs.append(caps)
    rows.append(np.hstack([I, Z, -I]))  # p - d <= target
    rhs.append(target)
    rows.append(np.hstack([-I, Z, -I]))  # -p - d <= -target
    rhs.append(-target)
    J = jump_frac * A_pay
    D = np.zeros((n - 1, n))
    for m in range(n - 1):
        D[m, m], D[m, m + 1] = -1, 1
    if n > 1:
        rows.append(np.hstack([D, np.zeros((n - 1, 2 * n))]))
        rhs.append(np.full(n - 1, J))
        rows.append(np.hstack([-D, np.zeros((n - 1, 2 * n))]))
        rhs.append(np.full(n - 1, J))
    rows.append(np.hstack([Z, Z, I]))  # d_m <= dmax (последний столбец добавляется ниже)
    rhs.append(np.zeros(n))
    A_ub = np.vstack(rows)
    dcol = np.zeros((A_ub.shape[0], 1))
    dcol[-n:, 0] = -1.0
    # столбцы: p, o, d, dmax, omax
    A_ub = np.hstack([A_ub, dcol, np.zeros((A_ub.shape[0], 1))])
    # o_m <= omax: неизбежная перегрузка распределяется по месяцам. Без этого минимум суммы
    # перегрузки достигается досрочным погашением (меньше процентов) — огромные первые платежи.
    A_ub = np.vstack([A_ub, np.hstack([Z, I, Z, np.zeros((n, 1)), -np.ones((n, 1))])])
    rhs.append(np.zeros(n))
    b_ub = np.concatenate(rhs)
    A_eq = np.hstack([A_eq_p, np.zeros((1, 2 * n + 2))])
    # штраф: перегрузка (макс. и сумма) >> максимальное отклонение > сумма отклонений
    cost = np.concatenate([np.zeros(n), np.full(n, 1000.0 / A_pay), np.full(n, 1.0 / A_pay),
                           [3.0 / A_pay], [3000.0 / A_pay]])
    res = linprog(cost, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
                  bounds=[(0, None)] * (nv + 2), method="highs")
    if res.status != 0:
        return dict(status="solver_failed", message=res.message, payments=None)
    p = res.x[:n]
    over = np.maximum(p - caps, 0)
    return dict(status="ok", payments=p, overload=over, annuity=A_pay)


def max_feasible_principal(i: float, caps: np.ndarray) -> float:
    """Максимальная сумма, которую можно погасить, не превышая cap_m ни в одном месяце."""
    caps = np.maximum(np.asarray(caps, float), 0)
    s = caps.mean()
    if s <= 0:
        return 0.0
    return _max_principal_scaled(i, caps / s) * s


def _max_principal_scaled(i: float, caps: np.ndarray) -> float:
    n = len(caps)
    G = _balance_matrix(n, i)
    # переменные [p_1..p_n, P]; maximize P
    A, b = [], []
    for m in range(n):
        row = np.zeros(n + 1)
        row[m] = -1.0
        if m > 0:
            row[:m] -= i * G[m - 1, :m]
        row[n] = i * (1 + i) ** m
        A.append(row)
        b.append(0.0)
    for m in range(n - 1):
        row = np.zeros(n + 1)
        row[:n] = G[m]
        row[n] = -(1 + i) ** (m + 1)
        A.append(row)
        b.append(0.0)
    A_eq = np.zeros((1, n + 1))
    A_eq[0, :n] = G[n - 1]
    A_eq[0, n] = -(1 + i) ** n
    bounds = [(0, caps[m]) for m in range(n)] + [(0, None)]
    cost = np.zeros(n + 1)
    cost[n] = -1.0
    res = linprog(cost, A_ub=np.array(A), b_ub=np.array(b), A_eq=A_eq, b_eq=[0.0],
                  bounds=bounds, method="highs")
    return float(res.x[n]) if res.status == 0 else 0.0


def extend_caps(caps12: np.ndarray, n: int) -> np.ndarray:
    """Срок > 12 мес.: сезонный профиль прогноза повторяется без роста (консервативно)."""
    return np.resize(np.asarray(caps12, float), n)


def min_feasible_term(P: float, i: float, caps12: np.ndarray, start: int, max_term: int) -> int | None:
    for n in range(start, max_term + 1):
        if max_feasible_principal(i, extend_caps(caps12, n)) >= P - 1:
            return n
    return None
