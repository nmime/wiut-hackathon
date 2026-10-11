"""Компонент A: прогноз денежного потока на 12 месяцев.

Глобальная LightGBM (одна модель на все бизнесы) с прямой многошаговой схемой:
горизонт h — признак. Приток и операционный отток прогнозируются раздельно, цель —
лог-отношение к уровню последних 12 месяцев (масштаб бизнеса не важен).
Интервалы — локально-адаптивный split-conformal по out-of-fold остаткам обучающих
бизнесов (CV+), сгруппированным по горизонту и режиму истории.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from config import HORIZON
from features.calendar import eid_in_month, ramadan_fraction
from features.profile import history_mode

LEVELS = np.round(np.linspace(0.01, 0.99, 99), 2)
LAGS_IN = 12
LAGS_OUT = 3

FEATS_COMMON = [
    "h", "tgt_moy", "tgt_sin", "tgt_cos", "ram_tgt", "ram_tgt_ly", "ram_tgt_l2y", "eid_tgt",
    "eid_tgt_ly", "n_hist", "trend_in", "cv_in", "vol_in", "resid_vol", "season_strength",
    "share_qr", "share_card", "share_transfer", "share_cash", "fixed_share", "debt_share",
    "top_payer", "active_days", "ind_prior_tgt", "ind_prior_next", "margin", "trend_proj",
]
FEATS_IN = FEATS_COMMON + [f"lr_in_{k}" for k in range(LAGS_IN)] + [
    "recent3_in", "sm1_in", "sm2_in"]
FEATS_OUT = FEATS_COMMON + [f"lr_out_{k}" for k in range(LAGS_OUT)] + [
    "lr_in_0", "lr_in_1", "recent3_in", "recent3_out", "sm1_in", "sm1_in_next", "sm2_in",
    "sm1_out", "sm2_out", "trend_out"]

FEATURE_GROUPS = {
    "recent": ("Недавняя динамика потока", "So'nggi oylar dinamikasi"),
    "seasonal_ly": ("Сезонный паттерн прошлых лет", "O'tgan yillar mavsumiyligi"),
    "calendar": ("Календарь и горизонт прогноза", "Taqvim va prognoz ufqi"),
    "ramadan": ("Сдвиг Рамадана по годам", "Ramazon oyining siljishi"),
    "trend": ("Тренд выручки", "Tushum trendi"),
    "volatility": ("Волатильность поступлений", "Tushumlar o'zgaruvchanligi"),
    "structure": ("Структура поступлений и расходов", "Tushum va xarajatlar tuzilmasi"),
    "history": ("Длина истории", "Tarix uzunligi"),
    "industry": ("Отраслевая сезонность", "Tarmoq mavsumiyligi"),
}


def feature_group(name: str) -> str:
    if name == "trend_proj":
        return "trend"
    if name.startswith(("lr_", "recent3")):
        return "recent"
    if name.startswith(("sm1", "sm2", "season_strength")):
        return "seasonal_ly"
    if name.startswith(("ram_", "eid_")):
        return "ramadan"
    if name.startswith(("h", "tgt_")):
        return "calendar"
    if name.startswith("trend"):
        return "trend"
    if name in ("cv_in", "vol_in", "resid_vol"):
        return "volatility"
    if name == "n_hist":
        return "history"
    if name.startswith("ind_prior"):
        return "industry"
    return "structure"


# ---------------------------------------------------------------- массивы бизнеса

def business_arrays(prof_b: pd.DataFrame) -> dict:
    p = prof_b.sort_values("month_idx")
    get = lambda c: p[c].to_numpy(dtype=float)  # noqa: E731
    return dict(
        months=p["month_idx"].to_numpy(dtype=int), inflow=get("inflow_total"),
        out=get("outflow_operating"), debt=get("outflow_debt"), fixed=get("outflow_fixed"),
        qr=get("inflow_qr"), card=get("inflow_card"), transfer=get("inflow_transfer"),
        cash=get("inflow_cash_other"), top=get("top_payer_share"), active=get("active_days"),
    )


def _slope(y: np.ndarray) -> float:
    if len(y) < 4:
        return np.nan
    c = 0.05 * max(y.mean(), 1.0) + 1
    return float(np.polyfit(np.arange(len(y)), np.log(y + c), 1)[0] * 12)


def _season_strength(y: np.ndarray) -> float:
    if len(y) < 24:
        return np.nan
    y = y[-36:]
    c = 0.05 * max(y.mean(), 1.0) + 1
    ly = np.log(y + c)
    x = np.arange(len(ly))
    r = ly - np.polyval(np.polyfit(x, ly, 1), x)
    means = np.array([r[x % 12 == k].mean() for k in range(12)])
    v = r.var()
    return float(means[x % 12].var() / v) if v > 0 else 0.0


def _resid_vol(y: np.ndarray) -> float:
    """Непредсказуемая часть колебаний log-притока (без тренда и сезонности)."""
    y = y[-36:]
    n = len(y)
    if n < 3:
        return np.nan
    ly = np.log(y + 0.05 * max(y.mean(), 1.0) + 1)
    if n >= 24:
        x = np.arange(n)
        r = ly - np.polyval(np.polyfit(x, ly, 1), x)
        r = r - np.array([r[x % 12 == k].mean() for k in range(12)])[x % 12]
        return float(r.std() * np.sqrt(n / max(n - 14, 1)))
    if n >= 16:
        d = ly[12:] - ly[:-12]
        return float(np.std(d - d.mean()) / np.sqrt(2) * np.sqrt(len(d) / max(len(d) - 1, 1)))
    return float(np.std(np.diff(ly)) / np.sqrt(2))


def origin_state(a: dict, o: int) -> dict:
    """Всё, что известно на конец месяца-индекса o (включительно). Только прошлое."""
    lo = max(0, o - 11)
    win_in, win_out = a["inflow"][lo:o + 1], a["out"][lo:o + 1]
    L_in, L_out = float(win_in.mean()), float(win_out.mean())
    c_in, c_out = 0.05 * L_in + 1.0, 0.05 * L_out + 1.0
    tot = win_in.sum() if win_in.sum() > 0 else np.nan
    lr = lambda arr, k, L, c: (np.log((arr[o - k] + c) / (L + c)) if o - k >= 0 else np.nan)  # noqa
    d = np.diff(np.log(win_in + c_in)) if len(win_in) >= 3 else np.array([np.nan])
    st = dict(
        o=o, origin_month=int(a["months"][o]), L_in=L_in, L_out=L_out, c_in=c_in, c_out=c_out,
        n_hist=o + 1,
        trend_in=_slope(a["inflow"][max(0, o - 23):o + 1]),
        trend_out=_slope(a["out"][max(0, o - 23):o + 1]),
        cv_in=float(win_in.std() / L_in) if L_in > 0 else np.nan,
        vol_in=float(np.nanstd(d)),
        season_strength=_season_strength(a["inflow"][:o + 1]),
        share_qr=a["qr"][lo:o + 1].sum() / tot, share_card=a["card"][lo:o + 1].sum() / tot,
        share_transfer=a["transfer"][lo:o + 1].sum() / tot,
        share_cash=a["cash"][lo:o + 1].sum() / tot,
        fixed_share=a["fixed"][lo:o + 1].sum() / tot, debt_share=a["debt"][lo:o + 1].sum() / tot,
        top_payer=float(np.nanmean(a["top"][lo:o + 1])) if np.isfinite(a["top"][lo:o + 1]).any() else np.nan,
        active_days=float(a["active"][lo:o + 1].mean()),
        margin=float(L_out / L_in) if L_in > 0 else np.nan,
        recent3_in=float(np.log((a["inflow"][max(0, o - 2):o + 1].mean() + c_in) / (L_in + c_in))),
        recent3_out=float(np.log((a["out"][max(0, o - 2):o + 1].mean() + c_out) / (L_out + c_out))),
        debt_cur=float(a["debt"][max(0, o - 2):o + 1].mean()),
    )
    for k in range(LAGS_IN):
        st[f"lr_in_{k}"] = lr(a["inflow"], k, L_in, c_in)
    for k in range(LAGS_OUT):
        st[f"lr_out_{k}"] = lr(a["out"], k, L_out, c_out)
    rv = _resid_vol(a["inflow"][:o + 1])
    st["resid_vol"] = rv
    st["scale"] = L_in * max(rv if np.isfinite(rv) else 0.3, 0.03)
    return st


def horizon_row(a: dict, st: dict, h: int, prior: list | None) -> dict:
    o = st["o"]
    t_month = st["origin_month"] + h
    moy = t_month % 12
    row = {k: v for k, v in st.items() if k in FEATS_COMMON or k.startswith(("lr_", "recent3"))}
    row.update(h=h, tgt_moy=moy + 1, tgt_sin=np.sin(2 * np.pi * moy / 12),
               tgt_cos=np.cos(2 * np.pi * moy / 12), ram_tgt=ramadan_fraction(t_month),
               ram_tgt_ly=ramadan_fraction(t_month - 12), ram_tgt_l2y=ramadan_fraction(t_month - 24),
               eid_tgt=eid_in_month(t_month), eid_tgt_ly=eid_in_month(t_month - 12),
               trend_out=st["trend_out"])

    def ago(arr, back, L, c):
        j = o + h - back
        return float(np.log((arr[j] + c) / (L + c))) if 0 <= j <= o else np.nan

    row["sm1_in"] = ago(a["inflow"], 12, st["L_in"], st["c_in"])
    row["sm2_in"] = ago(a["inflow"], 24, st["L_in"], st["c_in"])
    row["sm1_in_next"] = ago(a["inflow"], 11, st["L_in"], st["c_in"])
    row["sm1_out"] = ago(a["out"], 12, st["L_out"], st["c_out"])
    row["sm2_out"] = ago(a["out"], 24, st["L_out"], st["c_out"])
    row["ind_prior_tgt"] = prior[moy] if prior else np.nan
    row["ind_prior_next"] = prior[(moy + 1) % 12] if prior else np.nan
    # Проекция тренда от центра окна уровня L (o - 5.5) до целевого месяца: деревья сами
    # тренд не экстраполируют, поэтому даём им готовое линейное продолжение.
    tr = st["trend_in"] if np.isfinite(st["trend_in"]) else 0.0
    row["trend_proj"] = tr * (h + min(st["n_hist"], 12) / 2 - 0.5) / 12
    return row


def industry_priors(profiles: pd.DataFrame, okeds: dict[str, str]) -> dict[str, list]:
    """Отраслевой профиль сезонности по обучающим бизнесам с историей >= 24 мес."""
    acc: dict[str, list] = {}
    for b, g in profiles.groupby("business_id"):
        if len(g) < 24 or not okeds.get(b):
            continue
        y = g.sort_values("month_idx")["inflow_total"].to_numpy(float)
        m = g.sort_values("month_idx")["month_idx"].to_numpy(int)
        c = 0.05 * y.mean() + 1
        ly = np.log(y + c)
        x = np.arange(len(ly))
        r = ly - np.polyval(np.polyfit(x, ly, 1), x)
        vec = np.array([r[m % 12 == k].mean() for k in range(12)])
        acc.setdefault(okeds[b], []).append(vec)
    return {k: np.mean(v, axis=0).round(4).tolist() for k, v in acc.items() if len(v) >= 3}


def hb(h: int) -> str:
    return "1-3" if h <= 3 else ("4-6" if h <= 6 else "7-12")


# ---------------------------------------------------------------- модель

LGB_PARAMS = dict(objective="l1", learning_rate=0.04, num_leaves=31, min_data_in_leaf=60,
                  feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0,
                  verbose=-1, num_threads=4, seed=0)
N_ROUNDS = 500


# Выбрано на val-бэктесте: веса 0 / 0.5 / 1.0 различаются в пределах шума, 0.5 лучше на сезонных.
# Вариант «якорь + дрейф тренда» на val хуже (WAPE 0.186 против 0.184) и не используется.
ANCHOR_WEIGHT = 0.5


def anchor(X: pd.DataFrame, kind: str) -> np.ndarray:
    """Якорь — наивный сезонный прогноз в лог-отношении (тот же месяц год назад).
    Бустинг учит поправку к нему: тренд, Рамадан, отраслевой приор, сломы. Нет истории — 0 (уровень L)."""
    col = "sm1_in" if kind == "in" else "sm1_out"
    return ANCHOR_WEIGHT * X[col].fillna(0.0).to_numpy()


def fit_booster(X: pd.DataFrame, y: np.ndarray, feats: list[str], kind: str = "in") -> lgb.Booster:
    ds = lgb.Dataset(X[feats], y, init_score=anchor(X, kind), free_raw_data=False)
    return lgb.train(LGB_PARAMS, ds, num_boost_round=N_ROUNDS)


def predict_log(b: lgb.Booster, X: pd.DataFrame, feats: list[str], kind: str) -> np.ndarray:
    return b.predict(X[feats]) + anchor(X, kind)


@dataclass
class ForecastResult:
    months: list[int]
    mode: str
    in_p50: np.ndarray
    out_p50: np.ndarray
    debt: np.ndarray
    free_p50: np.ndarray
    free_grid: np.ndarray           # (12, 99) значения на уровнях LEVELS
    in_grid: np.ndarray
    state: dict
    shap_in: dict = field(default_factory=dict)   # группа -> средний вклад (лог)
    shap_out: dict = field(default_factory=dict)
    shap_rows: list = field(default_factory=list)  # по месяцам: группа -> вклад

    def q(self, level: float, which: str = "free") -> np.ndarray:
        grid = self.free_grid if which == "free" else self.in_grid
        j = int(np.argmin(np.abs(LEVELS - level)))
        return grid[:, j]

    def prob_at_least(self, thr: np.ndarray | float) -> np.ndarray:
        thr = np.broadcast_to(np.asarray(thr, float), (len(self.months),))
        return (self.free_grid >= thr[:, None]).mean(axis=1)


class ForecastModel:
    def __init__(self, b_in: lgb.Booster, b_out: lgb.Booster, conformal: dict, priors: dict,
                 meta: dict | None = None):
        self.b_in, self.b_out = b_in, b_out
        self.conformal = conformal  # {"free": {group: [99]}, "in": {...}}
        self.priors = priors
        self.meta = meta or {}

    # -- сохранение
    def save(self, d: Path):
        d.mkdir(parents=True, exist_ok=True)
        self.b_in.save_model(str(d / "lgb_inflow.txt"))
        self.b_out.save_model(str(d / "lgb_outflow.txt"))
        (d / "conformal.json").write_text(json.dumps(self.conformal), encoding="utf-8")
        (d / "industry_priors.json").write_text(json.dumps(self.priors), encoding="utf-8")

    @classmethod
    def load(cls, d: Path, meta: dict | None = None) -> "ForecastModel":
        return cls(lgb.Booster(model_file=str(d / "lgb_inflow.txt")),
                   lgb.Booster(model_file=str(d / "lgb_outflow.txt")),
                   json.loads((d / "conformal.json").read_text(encoding="utf-8")),
                   json.loads((d / "industry_priors.json").read_text(encoding="utf-8")), meta)

    def _scores(self, kind: str, h: int, mode: str) -> np.ndarray:
        tab = self.conformal[kind]
        key = f"{hb(h)}|{mode}"
        return np.asarray(tab.get(key) or tab[f"{hb(h)}|*"])

    def predict_business(self, prof_b: pd.DataFrame, oked: str | None = None,
                         external_debt: float = 0.0, horizon: int = HORIZON,
                         with_shap: bool = True) -> ForecastResult:
        a = business_arrays(prof_b)
        o = len(a["months"]) - 1
        st = origin_state(a, o)
        prior = self.priors.get(oked) if oked else None
        rows = [horizon_row(a, st, h, prior) for h in range(1, horizon + 1)]
        X = pd.DataFrame(rows)
        y_in = predict_log(self.b_in, X, FEATS_IN, "in")
        y_out = predict_log(self.b_out, X, FEATS_OUT, "out")
        in_p50 = np.maximum(np.exp(y_in) * (st["L_in"] + st["c_in"]) - st["c_in"], 0)
        out_p50 = np.maximum(np.exp(y_out) * (st["L_out"] + st["c_out"]) - st["c_out"], 0)
        debt = np.full(horizon, st["debt_cur"] + external_debt)
        free = in_p50 - out_p50 - debt
        mode = history_mode(o + 1)
        hs = np.arange(1, horizon + 1)
        free_grid = np.stack([free[i] + self._scores("free", h, mode) * st["scale"]
                              for i, h in enumerate(hs)])
        in_grid = np.stack([np.maximum(in_p50[i] + self._scores("in", h, mode) * st["scale"], 0)
                            for i, h in enumerate(hs)])
        res = ForecastResult(
            months=[st["origin_month"] + h for h in hs], mode=mode, in_p50=in_p50,
            out_p50=out_p50, debt=debt, free_p50=free, free_grid=free_grid, in_grid=in_grid,
            state=st,
        )
        if with_shap:
            ci = self.b_in.predict(X[FEATS_IN], pred_contrib=True)[:, :-1]
            co = self.b_out.predict(X[FEATS_OUT], pred_contrib=True)[:, :-1]
            # вклад якоря (сезонный паттерн прошлого года) добавляется к своей группе
            ai, ao = anchor(X, "in"), anchor(X, "out")
            res.shap_in = _group(ci.mean(axis=0), FEATS_IN)
            res.shap_in["seasonal_ly"] = res.shap_in.get("seasonal_ly", 0.0) + float(ai.mean())
            res.shap_out = _group(co.mean(axis=0), FEATS_OUT)
            res.shap_out["seasonal_ly"] = res.shap_out.get("seasonal_ly", 0.0) + float(ao.mean())
            res.shap_rows = [_group(ci[i], FEATS_IN) for i in range(len(hs))]
        return res


def _group(vec: np.ndarray, feats: list[str]) -> dict:
    out: dict[str, float] = {}
    for v, f in zip(vec, feats):
        g = feature_group(f)
        out[g] = out.get(g, 0.0) + float(v)
    return out


# ---------------------------------------------------------------- конструирование обучающих строк

def build_rows(prof: pd.DataFrame, okeds: dict, priors: dict, min_origin: int = 5,
               origin_step: int = 1, max_h: int = HORIZON) -> pd.DataFrame:
    """Строки (бизнес, origin, h) с признаками и целями внутри видимой истории."""
    out = []
    for b, g in prof.groupby("business_id", sort=False):
        a = business_arrays(g)
        T = len(a["months"])
        prior = priors.get(okeds.get(b, ""))
        for o in range(min_origin, T - 1, origin_step):
            st = origin_state(a, o)
            for h in range(1, min(max_h, T - 1 - o) + 1):
                r = horizon_row(a, st, h, prior)
                t = o + h
                r.update(
                    business_id=b, L_in=st["L_in"], L_out=st["L_out"], c_in=st["c_in"],
                    c_out=st["c_out"], scale=st["scale"], debt_cur=st["debt_cur"],
                    y_in=np.log((a["inflow"][t] + st["c_in"]) / (st["L_in"] + st["c_in"])),
                    y_out=np.log((a["out"][t] + st["c_out"]) / (st["L_out"] + st["c_out"])),
                    act_in=a["inflow"][t], act_out=a["out"][t], act_debt=a["debt"][t],
                    mode=history_mode(o + 1),
                )
                out.append(r)
    return pd.DataFrame(out)


def reconstruct(df: pd.DataFrame, y_in: np.ndarray, y_out: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    pin = np.maximum(np.exp(y_in) * (df["L_in"] + df["c_in"]) - df["c_in"], 0).to_numpy()
    pout = np.maximum(np.exp(y_out) * (df["L_out"] + df["c_out"]) - df["c_out"], 0).to_numpy()
    return pin, pout


def conformal_tables(df: pd.DataFrame, pin: np.ndarray, pout: np.ndarray) -> dict:
    """Квантили нормированных остатков по группам (горизонт × режим) и запасная (горизонт × *)."""
    free_act = df["act_in"] - df["act_out"] - df["act_debt"]
    free_hat = pin - pout - df["debt_cur"]
    s_free = ((free_act - free_hat) / df["scale"]).to_numpy()
    s_in = ((df["act_in"] - pin) / df["scale"]).to_numpy()
    hbs = df["h"].map(hb).to_numpy()
    modes = df["mode"].to_numpy()
    tabs = {"free": {}, "in": {}, "counts": {}}
    for h_ in ("1-3", "4-6", "7-12"):
        for m_ in ("no_seasonality", "reduced_seasonality", "full", "*"):
            mask = (hbs == h_) & ((modes == m_) if m_ != "*" else True)
            n = int(mask.sum())
            tabs["counts"][f"{h_}|{m_}"] = n
            if n >= 150:
                tabs["free"][f"{h_}|{m_}"] = np.quantile(s_free[mask], LEVELS).round(5).tolist()
                tabs["in"][f"{h_}|{m_}"] = np.quantile(s_in[mask], LEVELS).round(5).tolist()
    return tabs
