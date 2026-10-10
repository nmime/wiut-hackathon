"""Offline new nominal revenue corpus with explicit untouched country audit.

ONS is audit-only at every date. Loading metadata does not construct audit
cases. Train/validation builders never inspect final country target values.
"""

import hashlib
import json
from pathlib import Path

import numpy as np

from .revenue_data import RevenueSeries, parse_month

DATA_PATHS = tuple(
    Path(__file__).resolve().parent.parent / "data" / f"external-{name}.json"
    for name in ("protocol", "eurostat", "ons")
)
EXPECTED_LICENSES = {
    "eurostat": "Eurostat reuse policy (Decision 2011/833/EU)",
    "ons": "Open Government Licence v3.0",
}
COUNTRIES = "AT BE BG HR CY CZ DK EE FI FR DE EL HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE IS NO CH".split()
SECTORS = (
    [f"G45{i}" for i in range(1, 5)]
    + [f"G46{i}" for i in (*range(1, 8), 9)]
    + ["G4711", "G4719"]
    + [f"G47{i}" for i in range(2, 10)]
)
ONS_CODES = "CY3X CY45 CY4B EAGB EAGE EAGH EAPG EAPH EAPI EAPK EAPM EAPN EAPO EAPQ J43J JJ8J JKO6 JOF2 J43H".split()
MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024


def read_snapshot(path: Path) -> dict:
    if path.stat().st_size > MAX_SNAPSHOT_BYTES:
        raise ValueError("External snapshot exceeds 8 MiB bound")
    raw = path.read_bytes()
    if len(raw) > MAX_SNAPSHOT_BYTES:
        raise ValueError("External snapshot exceeds 8 MiB bound")
    return json.loads(raw)


def external_data_digest() -> str:
    digest = hashlib.sha256()
    for path in DATA_PATHS:
        digest.update(path.read_bytes())
    return digest.hexdigest()


def load_external_series() -> tuple[list[RevenueSeries], dict]:
    plan = read_snapshot(DATA_PATHS[0])
    if (
        plan["countries"] != COUNTRIES
        or plan["sectors"] != SECTORS
        or plan["ons_leaf_cdid"] != ONS_CODES
    ):
        raise ValueError(
            "External taxonomy differs from frozen country/category protocol"
        )
    groups = plan["geographic_groups"]
    if not plan["frozen_before_import_and_training"] or set(groups) != {
        "train",
        "validation",
        "audit",
    }:
        raise ValueError("External country audit protocol must be frozen")
    if len(set(sum(groups.values(), []))) != sum(map(len, groups.values())):
        raise ValueError("External geographic partitions overlap")
    ordered_groups = sorted(
        ["eurostat:" + country for country in COUNTRIES],
        key=lambda group: hashlib.sha256(
            ("external-country-v1:" + group).encode()
        ).hexdigest(),
    )
    if groups != {
        "train": ordered_groups[:18],
        "validation": ordered_groups[18:24],
        "audit": ordered_groups[24:] + ["ons:GB"],
    }:
        raise ValueError("External country partition differs from frozen hash protocol")
    if any(
        group.startswith("ons:")
        for split in ("train", "validation")
        for group in groups[split]
    ):
        raise ValueError("ONS is an entirely unseen provider and country")
    series, sources, flags = [], [], {}
    for path in DATA_PATHS[1:]:
        snapshot = read_snapshot(path)
        source = snapshot["source"]
        provider = source["provider"]
        if snapshot["format"] != 1 or source["license"] != EXPECTED_LICENSES[provider]:
            raise ValueError("Unrecognized external source/license/format")
        if any(snapshot["protocol"].get(key) != value for key, value in plan.items()):
            raise ValueError("External source differs from frozen protocol")
        sources.append(source)
        for row in snapshot["series"]:
            months = np.asarray([parse_month(value) for value in row["months"]])
            if (
                len(months) != len(row["values"])
                or not 1 <= len(months) <= 240
                or np.any(np.diff(months) != 1)
            ):
                raise ValueError(
                    "External calendar arrays must be aligned, contiguous and bounded"
                )
            if row["group"] not in sum(groups.values(), []) or not row[
                "identity"
            ].startswith(provider + ":"):
                raise ValueError("External series lacks frozen geographic membership")
            if row["group"] != f"{provider}:{row['geography']}" or row["identity"] != (
                f"{row['group']}:{row['sector']}"
                if provider == "eurostat"
                else f"ons:{row['sector']}"
            ):
                raise ValueError("External provider/geography/identity mismatch")
            if row["sector"] not in (SECTORS if provider == "eurostat" else ONS_CODES):
                raise ValueError("External series not in frozen sector taxonomy")
            if any(
                v is not None
                and (
                    isinstance(v, bool)
                    or not isinstance(v, (int, float))
                    or not np.isfinite(v)
                )
                for v in row["values"]
            ):
                raise ValueError(
                    "External values must be finite numbers or explicit null"
                )
            values = np.asarray(
                [np.nan if v is None else v for v in row["values"]], dtype=float
            )
            series.append(
                RevenueSeries(
                    row["identity"], row["sector"], row["group"], months, values, source
                )
            )
            flags[row["identity"]] = {
                parse_month(label): flag for label, flag in row.get("flags", {}).items()
            }
    expected_identities = {
        f"eurostat:{country}:{sector}" for country in COUNTRIES for sector in SECTORS
    } | {f"ons:{code}" for code in ONS_CODES}
    if {row.identity for row in series} != expected_identities:
        raise ValueError("External snapshot does not preserve entire frozen taxonomy")
    if not 1 <= len(series) <= 720 or len({row.identity for row in series}) != len(
        series
    ):
        raise ValueError("External series exceeds bounds or contains duplicates")
    return series, {
        "data_sha256": external_data_digest(),
        "protocol": plan,
        "protocols": {source["provider"]: plan for source in sources},
        "sources": sources,
        "providers": {source["provider"]: source for source in sources},
        "training_sources": [
            source
            for source in sources
            if source["provider"] not in plan["audit_only_providers"]
        ],
        "audit_only_sources": [
            source
            for source in sources
            if source["provider"] in plan["audit_only_providers"]
        ],
        "geographic_groups": groups,
        "flags": flags,
        "series": len(series),
        "observations": sum(len(row.months) for row in series),
        "nonnull_published_observations": sum(
            source["nonnull_published_observations"] for source in sources
        ),
        "missing_suppressed_or_unreliable_observations": sum(
            source["missing_suppressed_or_unreliable_observations"]
            for source in sources
        ),
        "currency_policy": "Eurostat nominal turnover index2021=100 and ONS nominal sales value index2024=100 are index points, not currencies, bank receipts or borrower amount indices. No conversion to UZS. Raw errors remain provider-specific; only dimensionless normalized errors may be pooled.",
        "limitations": "Seven frozen country audit groups, not independent firms. Within-provider industries share national shocks/revisions; current-vintage rather than historical-vintage evaluation. Missing/suppressed/unreliable/imputed/forecast values are not invented zeros. Other legacy providers have provider-specific later development cutoffs, so cross-provider experiment is not globally chronological; no absolute calendar year is a learned feature.",
    }


def build_external_cases(
    split: str, dataset: tuple[list[RevenueSeries], dict] | None = None
) -> tuple[list, list[dict]]:
    from .forecasting import MonthlyHistory
    from .public_revenue import PublicCase

    if split not in {"train", "validation", "audit"}:
        raise ValueError("Specify train, validation or audit explicitly")
    series, metadata = dataset if dataset is not None else load_external_series()
    plan = metadata["protocol"]
    cases, exclusions = [], []
    for row in series:
        if row.group not in plan["geographic_groups"][split]:
            continue
        if split != "audit" and row.source["provider"] in plan["audit_only_providers"]:
            raise ValueError("Attempted to use unseen provider for development")
        if split == "train":
            latest = parse_month(plan["training_target_end"]) - 11
            origins = range(
                int(row.months[0]) + plan["minimum_history_months"],
                latest + 1,
                plan["training_origin_stride_months"],
            )
        else:
            origins = [parse_month(plan[split + "_target_start"])]
        # Build a mapping only for the requested country's allowed window; never
        # consume terminal targets during development even on its own countries.
        target_end = parse_month(
            plan["training_target_end"]
            if split == "train"
            else plan[split + "_target_end"]
        )
        allowed_end = np.searchsorted(row.months, target_end, side="right")
        mapping = {
            int(month): float(value)
            for month, value in zip(
                row.months[:allowed_end], row.values[:allowed_end], strict=True
            )
        }
        for origin in origins:
            start = max(
                int(row.months[0]), origin - plan["maximum_case_history_months"]
            )
            values = np.asarray(
                [mapping.get(int(month), np.nan) for month in range(start, origin + 12)]
            )
            window_flags = metadata.get("flags", {}).get(row.identity, {})
            reason = (
                "insufficient_history"
                if origin - start < plan["minimum_history_months"]
                else "missing_suppressed_or_unreliable_month"
                if np.any(~np.isfinite(values))
                else "negative_actual_revenue"
                if np.any(values < 0)
                else "break_or_definition_change_inside_window"
                if any(
                    start < month < origin + 12 and ("b" in flag or "d" in flag)
                    for month, flag in window_flags.items()
                )
                else "all_zero_history"
                if np.mean(values[:-12][-12:]) <= 0
                else None
            )
            if reason:
                exclusions.append(
                    {
                        "identity": row.identity,
                        "group": row.group,
                        "split": split,
                        "target_start": origin,
                        "reason": reason,
                    }
                )
                continue
            if split == "train" and origin + 11 > parse_month(
                plan["training_target_end"]
            ):
                raise ValueError("External training targets cross frozen boundary")
            observed = values[:-12]
            cases.append(
                PublicCase(
                    row.identity,
                    row.sector,
                    row.group,
                    MonthlyHistory(
                        np.arange(start, origin),
                        observed,
                        np.zeros(len(observed)),
                        origin,
                    ),
                    values[-12:],
                )
            )
    return cases, exclusions
