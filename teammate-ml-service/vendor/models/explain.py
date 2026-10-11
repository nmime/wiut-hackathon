"""Объяснимость: вклад факторов, причины по месяцам графика, советы предпринимателю.

Всё детерминировано и локально. Советы — шаблоны (ru/uz), срабатывающие по слабым
факторам профиля относительно популяции обучающих бизнесов.
"""
from __future__ import annotations

import math

import numpy as np

from features.calendar import month_name, ramadan_fraction
from models.forecast import FEATURE_GROUPS, ForecastResult


def fmt_sum(v: float) -> str:
    return f"{v / 1e6:,.1f} млн сум".replace(",", " ")


def fmt_sum_uz(v: float) -> str:
    return f"{v / 1e6:,.1f} mln so'm".replace(",", " ")


# ---------------------------------------------------------------- сезонные метки

def season_labels(fr: ForecastResult, thr: float = 0.07) -> tuple[list[str], np.ndarray]:
    """weak/normal/strong по детрендированному прогнозу притока."""
    if fr.mode == "no_seasonality":
        return ["normal"] * len(fr.months), np.zeros(len(fr.months))
    y = np.log(fr.in_p50 + 0.05 * fr.in_p50.mean() + 1)
    x = np.arange(len(y))
    r = y - np.polyval(np.polyfit(x, y, 1), x)
    lab = ["weak" if v <= -thr else ("strong" if v >= thr else "normal") for v in r]
    return lab, r


# ---------------------------------------------------------------- топ факторов

def top_factors(shap: dict, n: int = 5, target: str = "inflow") -> list[dict]:
    """SHAP LightGBM, агрегированный по группам признаков и усреднённый по 12 месяцам.

    Вклад в лог-пространстве цели переводится в % изменения прогноза относительно
    базового уровня (среднее за последние 12 мес.).
    """
    t_ru, t_uz = ("притока", "tushum") if target == "inflow" else ("оттока", "xarajat")
    items = sorted(shap.items(), key=lambda kv: -abs(kv[1]))[:n]
    out = []
    for g, v in items:
        ru, uz = FEATURE_GROUPS[g]
        pct = math.exp(v) - 1
        out.append(dict(
            factor=g, name_ru=ru, name_uz=uz, contribution_log=round(v, 4),
            effect_pct=round(100 * pct, 1),
            direction="up" if v > 0 else "down",
            text_ru=f"{ru}: {'повышает' if v > 0 else 'снижает'} прогноз {t_ru} на {abs(pct):.1%}",
            text_uz=f"{uz}: {t_uz} prognozini {abs(pct):.1%} ga {'oshiradi' if v > 0 else 'kamaytiradi'}",
        ))
    return out


def profile_benchmarks(pf: dict, population: dict) -> list[dict]:
    """Положение бизнеса относительно популяции (перцентильная полоса)."""
    names = {
        "inflow_cv": "Коэффициент вариации притока", "trend_annual": "Годовой тренд выручки",
        "share_qr": "Доля QR-поступлений", "share_card": "Доля карточных поступлений",
        "net_margin": "Нетто-маржа", "fixed_share": "Доля фиксированных расходов",
        "debt_share": "Долговая нагрузка", "top_payer_share": "Доля крупнейшего плательщика",
        "active_days_mean": "Дней с поступлениями в месяц", "months_history": "Длина истории",
    }
    out = []
    for k, name in names.items():
        v = pf.get(k)
        q = population.get(k)
        if v is None or q is None or (isinstance(v, float) and math.isnan(v)):
            continue
        band = ("ниже p10" if v < q["p10"] else "p10–p25" if v < q["p25"] else
                "p25–p75" if v <= q["p75"] else "p75–p90" if v <= q["p90"] else "выше p90")
        out.append(dict(feature=k, name=name, value=round(float(v), 4),
                        population_median=round(q["p50"], 4), band=band))
    return out


# ---------------------------------------------------------------- советы

ADVICE = {
    "volatility": (
        "Поступления сильно колеблются от месяца к месяцу (CV {v:.0%}). Волатильность снижает "
        "посильную сумму: стабилизация выручки (регулярные договоры, подписки, предоплата) повысит лимит.",
        "Tushumlar oydan-oyga keskin o'zgaradi (CV {v:.0%}). Bu kredit limitini kamaytiradi: "
        "barqaror shartnomalar va oldindan to'lovlar limitni oshiradi."),
    "decline": (
        "Выручка снижается (тренд {v:+.0%} в год). Банк закладывает продолжение снижения; "
        "остановка спада или новые каналы продаж улучшат оценку.",
        "Tushum kamaymoqda (yillik trend {v:+.0%}). Pasayishni to'xtatish yoki yangi savdo "
        "kanallari bahoni yaxshilaydi."),
    "cashless": (
        "Низкая доля безналичных поступлений (QR + карта {v:.0%}). Подключение QR-оплаты делает "
        "выручку прозрачной для банка, и посильная сумма оценивается точнее.",
        "Naqdsiz tushumlar ulushi past (QR + karta {v:.0%}). QR-to'lovni ulash tushumni bank uchun "
        "shaffof qiladi va limit aniqroq baholanadi."),
    "concentration": (
        "{v:.0%} поступлений приходит от одного плательщика. Зависимость от одного клиента — риск; "
        "диверсификация клиентской базы повысит устойчивость оценки.",
        "Tushumlarning {v:.0%} bitta mijozdan keladi. Mijozlar bazasini kengaytirish bahoning "
        "barqarorligini oshiradi."),
    "fixed_costs": (
        "Фиксированные расходы составляют {v:.0%} притока и не снижаются в слабые месяцы. "
        "Пересмотр аренды или гибкий график зарплат увеличит свободный поток в межсезонье.",
        "Doimiy xarajatlar tushumning {v:.0%} qismini tashkil etadi va kuchsiz oylarda kamaymaydi. "
        "Ijara yoki ish haqi jadvalini qayta ko'rib chiqish erkin pul oqimini oshiradi."),
    "debt_load": (
        "Текущие платежи по кредитам — {v:.0%} притока. Они вычитаются из посильной выплаты; "
        "досрочное погашение дорогих кредитов освободит лимит.",
        "Joriy kredit to'lovlari tushumning {v:.0%} qismi. Ular to'lov qobiliyatidan ayiriladi; "
        "qimmat kreditlarni muddatidan oldin yopish limitni bo'shatadi."),
    "short_history": (
        "История операций — {v:.0f} мес. Через {w:.0f} мес. банк сможет учесть сезонность, "
        "и оценка станет точнее.",
        "Operatsiyalar tarixi — {v:.0f} oy. {w:.0f} oydan so'ng bank mavsumiylikni hisobga oladi "
        "va baho aniqroq bo'ladi."),
    "seasonality": (
        "Выраженная сезонность: слабые месяцы — {months}. Адаптивный график снижает платёж в эти "
        "месяцы; резерв из сильных месяцев дополнительно защитит бизнес.",
        "Mavsumiylik aniq: kuchsiz oylar — {months_uz}. Moslashuvchan jadval bu oylarda to'lovni "
        "kamaytiradi; kuchli oylardan zaxira biznesni himoya qiladi."),
    "low_margin": (
        "Нетто-маржа {v:.0%} ниже типичной для МСБ. Рост наценки или снижение закупочных цен "
        "увеличит свободный поток и посильную выплату.",
        "Sof marja {v:.0%} — o'rtachadan past. Ustama yoki xarid narxlarini optimallashtirish "
        "to'lov qobiliyatini oshiradi."),
    "irregular": (
        "Поступления нерегулярны: в среднем {v:.0f} дней с поступлениями в месяц. Регулярная "
        "выручка через счёт повышает уверенность оценки.",
        "Tushumlar notekis: oyiga o'rtacha {v:.0f} kun. Hisob orqali muntazam tushum baho "
        "ishonchliligini oshiradi."),
    "negative_months": (
        "Прогноз показывает месяцы, где расходы превышают поступления. В эти месяцы любой платёж "
        "по кредиту придётся покрывать из резерва — стоит заранее его сформировать.",
        "Prognozda xarajatlar tushumdan oshadigan oylar bor. Bu oylar uchun oldindan zaxira "
        "yaratish tavsiya etiladi."),
}


def advice(pf: dict, population: dict, fr: ForecastResult, labels: list[str]) -> list[dict]:
    P = lambda k, q: population.get(k, {}).get(q, float("nan"))  # noqa: E731
    out = []

    def add(key, severity, **kw):
        ru, uz = ADVICE[key]
        out.append(dict(key=key, severity=severity, text_ru=ru.format(**kw), text_uz=uz.format(**kw)))

    g = lambda k: pf.get(k, float("nan"))  # noqa: E731
    if g("inflow_cv") > P("inflow_cv", "p75"):
        add("volatility", "high", v=g("inflow_cv"))
    if g("trend_annual") < -0.08:
        add("decline", "high", v=g("trend_annual"))
    cashless = g("share_qr") + g("share_card")
    if cashless < 0.15 and g("share_transfer") < 0.7:
        add("cashless", "medium", v=cashless)
    if g("top_payer_share") > 0.4:
        add("concentration", "medium", v=g("top_payer_share"))
    if g("fixed_share") > P("fixed_share", "p75"):
        add("fixed_costs", "medium", v=g("fixed_share"))
    if g("debt_share") > 0.06:
        add("debt_load", "medium", v=g("debt_share"))
    if g("months_history") < 12:
        add("short_history", "info", v=g("months_history"), w=12 - g("months_history"))
    weak = [m for m, lab in zip(fr.months, labels) if lab == "weak"]
    if len(weak) >= 2:
        add("seasonality", "info", months=", ".join(month_name(m) for m in weak[:4]),
            months_uz=", ".join(month_name(m, "uz") for m in weak[:4]))
    if g("net_margin") < P("net_margin", "p25"):
        add("low_margin", "medium", v=g("net_margin"))
    if g("active_days_mean") < P("active_days_mean", "p10"):
        add("irregular", "low", v=g("active_days_mean"))
    if (fr.free_p50 < 0).any():
        add("negative_months", "high")
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    return sorted(out, key=lambda a: order[a["severity"]])


# ---------------------------------------------------------------- причины по графику

def schedule_reasons(months: list[int], adaptive: np.ndarray, annuity: float, fr: ForecastResult,
                     labels_by_month: dict, free_by_month: dict) -> list[dict]:
    mean_free = float(np.mean(list(free_by_month.values())))
    out = []
    for m, p in zip(months, adaptive):
        diff = p / annuity - 1
        if abs(diff) < 0.03:
            continue
        free = free_by_month.get(m)
        lab = labels_by_month.get(m, "normal")
        extrap = m not in fr.months
        rel = (free / mean_free - 1) if (free is not None and mean_free) else 0.0
        ram = ramadan_fraction(m) > 0.3
        if diff < 0:
            why = (f"прогноз свободного потока {fmt_sum(free)} — на {abs(rel):.0%} "
                   f"{'ниже' if rel < 0 else 'выше'} среднего по сроку")
            if lab == "weak":
                why += "; месяц прогнозируется сезонно слабым"
            if ram:
                why += "; на месяц приходится Рамадан"
            text = f"{month_name(m)}: платёж снижен на {abs(diff):.0%} относительно аннуитета — {why}"
        else:
            why = f"прогноз свободного потока {fmt_sum(free)}"
            if lab == "strong":
                why += ", месяц прогнозируется сезонно сильным"
            text = (f"{month_name(m)}: платёж повышен на {diff:.0%}, чтобы компенсировать "
                    f"снижение в слабые месяцы — {why}")
        if extrap:
            text += " (за горизонтом 12 мес.: сезонный профиль повторён без роста)"
        out.append(dict(month=f"{m // 12:04d}-{m % 12 + 1:02d}", change_vs_annuity=round(diff, 4),
                        season_label=lab, forecast_free_cash_flow=round(float(free), 2),
                        ramadan=ram, extrapolated=extrap, text_ru=text))
    return out
