"""Транзакции -> monthly_profile (бизнес × месяц) -> признаки профиля на дату отсечения.

Правило против утечки: любой признак на cutoff считается ТОЛЬКО по строкам
month_idx <= cutoff. Это проверяется тестом tests/test_leakage.py.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from config import (DEBT_CATEGORY, FIXED_CATEGORIES, FULL_MODE_MONTHS, MIN_HISTORY_MONTHS,
                    OWN_TRANSFER_CATEGORY, SEASONAL_MIN_MONTHS)
from features.calendar import days_in, idx_to_str

PROFILE_COLUMNS = [
    "business_id", "month", "month_idx",
    "inflow_card", "inflow_qr", "inflow_transfer", "inflow_cash_other", "inflow_total",
    "outflow_total", "outflow_fixed", "outflow_debt", "outflow_operating", "net_flow",
    "n_in_txn", "active_days", "unique_payers", "top_payer_share",
]


@dataclass
class ProfileInfo:
    business_id: str
    first_month: str | None
    last_complete_month: str | None
    months: int
    excluded_months: list[str]
    mode: str


def history_mode(months: int) -> str:
    if months < MIN_HISTORY_MONTHS:
        return "refused"
    if months < SEASONAL_MIN_MONTHS:
        return "no_seasonality"
    if months < FULL_MODE_MONTHS:
        return "reduced_seasonality"
    return "full"


def build_monthly_profile(tx: pd.DataFrame, as_of: pd.Timestamp | None = None,
                          drop_partial_first: bool = True
                          ) -> tuple[pd.DataFrame, dict[str, ProfileInfo]]:
    """tx — нормализованный DataFrame из validate_transactions (ts — локальное время)."""
    tx = tx[tx["category"] != OWN_TRANSFER_CATEGORY]
    as_of = pd.Timestamp(as_of) if as_of is not None else tx["ts"].max()
    as_of_idx = as_of.year * 12 + as_of.month - 1
    # Месяц считается полным, если дата выгрузки — его последний день или позже.
    last_complete = as_of_idx if as_of.day >= days_in(as_of_idx) else as_of_idx - 1

    ts = tx["ts"]
    m = (ts.dt.year * 12 + ts.dt.month - 1).to_numpy()
    day = ts.dt.day.to_numpy()
    is_in = (tx["direction"] == "in").to_numpy()
    amt = tx["amount"].to_numpy()
    ch = tx["channel"].to_numpy()
    cat = tx["category"].to_numpy()
    biz = tx["business_id"].to_numpy()

    base = pd.DataFrame({"business_id": biz, "month_idx": m})
    f = lambda mask: np.where(mask, amt, 0.0)  # noqa: E731
    base["inflow_card"] = f(is_in & (ch == "card"))
    base["inflow_qr"] = f(is_in & (ch == "qr"))
    base["inflow_transfer"] = f(is_in & (ch == "transfer"))
    base["inflow_cash_other"] = f(is_in & np.isin(ch, ["cash", "other"]))
    base["outflow_total"] = f(~is_in)
    base["outflow_fixed"] = f(~is_in & np.isin(cat, FIXED_CATEGORIES))
    base["outflow_debt"] = f(~is_in & (cat == DEBT_CATEGORY))
    base["n_in_txn"] = is_in.astype(int)
    agg = base.groupby(["business_id", "month_idx"], sort=True).sum()

    days = pd.DataFrame({"business_id": biz[is_in], "month_idx": m[is_in], "day": day[is_in]})
    agg["active_days"] = days.groupby(["business_id", "month_idx"])["day"].nunique()

    cp = tx["counterparty_id"].to_numpy()
    has_cp = is_in & (cp != "")
    cpdf = pd.DataFrame({"business_id": biz[has_cp], "month_idx": m[has_cp], "cp": cp[has_cp],
                         "amount": amt[has_cp]})
    if len(cpdf):
        by_cp = cpdf.groupby(["business_id", "month_idx", "cp"])["amount"].sum()
        agg["unique_payers"] = by_cp.groupby(level=[0, 1]).size()
        agg["_top_payer"] = by_cp.groupby(level=[0, 1]).max()
    else:
        agg["unique_payers"] = np.nan
        agg["_top_payer"] = np.nan

    frames, infos = [], {}
    first_day = pd.DataFrame({"business_id": biz, "m": m, "day": day}).groupby("business_id")
    first_m = first_day["m"].min()
    for b, g in agg.groupby(level=0, sort=False):
        g = g.droplevel(0)
        excluded = []
        start = int(first_m[b])
        # Неполный первый месяц (бизнес начал работать в середине месяца) — исключаем.
        fd = first_day.get_group(b)
        if drop_partial_first and fd.loc[fd["m"] == start, "day"].min() >= 10:
            excluded.append(idx_to_str(start))
            start += 1
        later = g.index[g.index > last_complete]
        excluded += [idx_to_str(i) + " (неполный)" for i in later]
        rng_idx = np.arange(start, last_complete + 1)
        g = g.reindex(rng_idx)
        fill0 = [c for c in g.columns if c not in ("unique_payers", "_top_payer")]
        g[fill0] = g[fill0].fillna(0.0)
        g["unique_payers"] = g["unique_payers"].fillna(0.0)
        g["business_id"] = b
        frames.append(g)
        n = len(rng_idx)
        infos[b] = ProfileInfo(
            business_id=b,
            first_month=idx_to_str(start) if n else None,
            last_complete_month=idx_to_str(last_complete) if n else None,
            months=n, excluded_months=excluded, mode=history_mode(n),
        )
    prof = pd.concat(frames) if frames else pd.DataFrame(columns=PROFILE_COLUMNS[1:])
    prof.index.name = "month_idx"
    prof = prof.reset_index()
    prof["inflow_total"] = prof[["inflow_card", "inflow_qr", "inflow_transfer",
                                 "inflow_cash_other"]].sum(axis=1)
    prof["outflow_operating"] = prof["outflow_total"] - prof["outflow_debt"]
    prof["net_flow"] = prof["inflow_total"] - prof["outflow_total"]
    prof["top_payer_share"] = np.where(prof["inflow_total"] > 0,
                                       prof["_top_payer"] / prof["inflow_total"].where(
                                           prof["inflow_total"] > 0), np.nan)
    prof["month"] = prof["month_idx"].map(idx_to_str)
    prof["month_idx"] = prof["month_idx"].astype(int)
    return prof[PROFILE_COLUMNS].reset_index(drop=True), infos


# ---------------------------------------------------------------- признаки профиля

def _slope_log(y: np.ndarray) -> float:
    """Годовой лог-тренд (регрессия log по месяцам)."""
    if len(y) < 4:
        return np.nan
    c = 0.05 * max(y.mean(), 1.0)
    ly = np.log(y + c)
    x = np.arange(len(y))
    return float(np.polyfit(x, ly, 1)[0] * 12)


def _seasonal_strength(y: np.ndarray) -> float:
    """Доля дисперсии детрендированного log-притока, объяснённая месяцем года (>=24 мес.)."""
    if len(y) < 24:
        return np.nan
    y = y[-36:]
    c = 0.05 * max(y.mean(), 1.0)
    ly = np.log(y + c)
    x = np.arange(len(ly))
    resid = ly - np.polyval(np.polyfit(x, ly, 1), x)
    moy = x % 12
    means = np.array([resid[moy == k].mean() for k in range(12)])
    fitted = means[moy]
    v = resid.var()
    return float(fitted.var() / v) if v > 0 else 0.0


def profile_features(p: pd.DataFrame, cutoff_idx: int | None = None) -> dict:
    """Признаки профиля одного бизнеса строго по месяцам <= cutoff_idx."""
    p = p.sort_values("month_idx")
    if cutoff_idx is not None:
        p = p[p["month_idx"] <= cutoff_idx]
    n = len(p)
    if n == 0:
        return {"months_history": 0}
    w = p.tail(12)
    inflow = p["inflow_total"].to_numpy(float)
    win = w["inflow_total"].to_numpy(float)
    tot_in = win.sum()
    safe = tot_in if tot_in > 0 else np.nan
    mean_in = win.mean()
    feats = {
        "months_history": n,
        "inflow_mean_12": float(mean_in),
        "inflow_median_12": float(np.median(win)),
        "outflow_mean_12": float(w["outflow_total"].mean()),
        "outflow_operating_mean_12": float(w["outflow_operating"].mean()),
        "net_mean_12": float(w["net_flow"].mean()),
        "inflow_cv": float(win.std() / mean_in) if mean_in > 0 else np.nan,
        "inflow_vol": _log_change_vol(win),
        "trend_annual": _slope_log(inflow[-24:]),
        "share_qr": float(w["inflow_qr"].sum() / safe),
        "share_card": float(w["inflow_card"].sum() / safe),
        "share_transfer": float(w["inflow_transfer"].sum() / safe),
        "share_cash_other": float(w["inflow_cash_other"].sum() / safe),
        "in_out_ratio": float(tot_in / w["outflow_total"].sum()) if w["outflow_total"].sum() > 0 else np.nan,
        "net_margin": float(w["net_flow"].sum() / safe),
        "fixed_share": float(w["outflow_fixed"].sum() / safe),
        "debt_share": float(w["outflow_debt"].sum() / safe),
        "debt_monthly_recent": float(p["outflow_debt"].tail(3).mean()),
        "active_days_mean": float(w["active_days"].mean()),
        "n_in_txn_mean": float(w["n_in_txn"].mean()),
        "zero_inflow_months": int((win <= 0).sum()),
        "unique_payers_mean": float(w["unique_payers"].mean()),
        "top_payer_share": float(w["top_payer_share"].mean()) if w["top_payer_share"].notna().any() else np.nan,
        "seasonal_strength": _seasonal_strength(inflow),
    }
    return feats


def _log_change_vol(y: np.ndarray) -> float:
    if len(y) < 3:
        return np.nan
    c = 0.05 * max(y.mean(), 1.0)
    d = np.diff(np.log(y + c))
    return float(d.std())
