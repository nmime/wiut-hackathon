"""Offline original retail revenue and frozen geographic/terminal holdouts.

Build each split explicitly. Merely loading the corpus never constructs test
cases or computes final-label statistics; training calls train/validation only.
"""

import hashlib
import json
from pathlib import Path

import numpy as np

from .revenue_data import RevenueSeries, parse_month

DATA_PATHS = tuple(
    Path(__file__).resolve().parent.parent / "data" / f"international-{provider}.json"
    for provider in ("abs", "statcan")
)
EXPECTED_LICENSES = {"abs": "CC BY 4.0", "statcan": "Statistics Canada Open Licence"}


def international_data_digest() -> str:
    digest = hashlib.sha256()
    for path in DATA_PATHS:
        digest.update(path.read_bytes())
    return digest.hexdigest()


def load_international_series() -> tuple[list[RevenueSeries], dict]:
    series, sources, protocols = [], [], {}
    for path in DATA_PATHS:
        snapshot = json.loads(path.read_text())
        source, protocol = snapshot["source"], snapshot["protocol"]
        provider = source["provider"]
        if snapshot["format"] != 1 or source["license"] != EXPECTED_LICENSES[provider]:
            raise ValueError("Unrecognized international source/license/format")
        if not protocol["frozen_before_training"]:
            raise ValueError("International evaluation protocol must be frozen")
        groups = protocol["geographic_groups"]
        if set(groups) != {"train", "validation", "test"} or len(
            set(sum(groups.values(), []))
        ) != sum(map(len, groups.values())):
            raise ValueError("International geographic partitions must be disjoint")
        sources.append(source)
        protocols[provider] = protocol
        for row in snapshot["series"]:
            months = np.asarray([parse_month(value) for value in row["months"]])
            if (
                len(months) != len(row["values"])
                or not 1 <= len(months) <= 240
                or np.any(np.diff(months) <= 0)
            ):
                raise ValueError(
                    "International monthly arrays must be aligned and ordered uniquely"
                )
            if row["group"] not in sum(groups.values(), []):
                raise ValueError(
                    "International series lacks frozen geographic membership"
                )
            if any(
                value is not None
                and (isinstance(value, bool) or not isinstance(value, (int, float)))
                for value in row["values"]
            ):
                raise ValueError(
                    "International values must be numeric or explicitly null"
                )
            values = np.asarray(
                [np.nan if value is None else value for value in row["values"]],
                dtype=float,
            )
            series.append(
                RevenueSeries(
                    row["identity"], row["sector"], row["group"], months, values, source
                )
            )
    if len({row.identity for row in series}) != len(series):
        raise ValueError("Duplicate international source series identity")
    return series, {
        "data_sha256": international_data_digest(),
        "sources": sources,
        "providers": {source["provider"]: source for source in sources},
        "protocols": protocols,
        "geographic_groups": {
            split: sum(
                [
                    protocol["geographic_groups"][split]
                    for protocol in protocols.values()
                ],
                [],
            )
            for split in ("train", "validation", "test")
        },
        "series": len(series),
        "observations": sum(len(row.months) for row in series),
        "nonnull_published_observations": sum(
            source["nonnull_published_observations"] for source in sources
        ),
        "missing_suppressed_or_unreliable_observations": sum(
            source["missing_suppressed_or_unreliable_observations"]
            for source in sources
        ),
        "currency_policy": "ABS million AUD and StatCan thousand CAD remain separate native units; only dimensionless normalized errors may be pooled. No conversion to borrower amount indices or UZS is declared.",
        "limitations": "Independent geographic groups, not independent businesses. Within-provider geography/industry estimates share survey revisions and economic shocks. Current-vintage data are not a historical-vintage backtest. Missing or suppressed values are not sales zeros.",
    }


def build_international_cases(
    split: str,
    dataset: tuple[list[RevenueSeries], dict] | None = None,
) -> tuple[list, list[dict]]:
    # Local imports avoid a training/forecasting/module digest import cycle.
    from .forecasting import MonthlyHistory
    from .public_revenue import PublicCase

    if split not in {"train", "validation", "test"}:
        raise ValueError("Specify one international split explicitly")
    series, metadata = dataset if dataset is not None else load_international_series()
    cases, exclusions = [], []
    for row in series:
        protocol = metadata["protocols"][row.source["provider"]]
        if row.group not in protocol["geographic_groups"][split]:
            continue
        if split == "train":
            latest_origin = parse_month(protocol["training_target_end"]) - 11
            origins = range(
                int(row.months[0]) + protocol["minimum_history_months"],
                latest_origin + 1,
                protocol["training_origin_stride_months"],
            )
        else:
            origins = [parse_month(protocol[split + "_target_start"])]
        mapping = dict(zip(row.months, row.values, strict=True))
        for origin in origins:
            start = max(
                int(row.months[0]), origin - protocol["maximum_case_history_months"]
            )
            months = np.arange(start, origin + 12)
            values = np.asarray([mapping.get(int(month), np.nan) for month in months])
            reason = (
                "insufficient_history"
                if origin - start < protocol["minimum_history_months"]
                else "missing_suppressed_or_unreliable_month"
                if np.any(~np.isfinite(values))
                else "negative_actual_revenue"
                if np.any(values < 0)
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
                protocol["training_target_end"]
            ):
                raise ValueError(
                    "International training targets cross their frozen boundary"
                )
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
