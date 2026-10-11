"""Reserve deterministic retrospective revenue targets without model inference.

No original data or split builder is changed. Targets are disjoint from all
original real training, development, and reported final target coordinates.
The same revised vintages, known eras, and trained geographies limit freshness.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np

from capacity_ml.evaluate_public import build_cases as build_public_baseline_cases
from capacity_ml.external_data import build_external_cases, load_external_series
from capacity_ml.forecasting import MonthlyHistory
from capacity_ml.international_data import (
    build_international_cases,
    load_international_series,
)
from capacity_ml.public_data import load_public_data
from capacity_ml.public_revenue import PublicCase, build_cases
from capacity_ml.revenue_data import load_revenue_series, parse_month

SERVICE = Path(__file__).resolve().parents[1]
MANIFEST_PATH = SERVICE / "data/real-comparison-unused-temporal.json"
PROTOCOL_VERSION = "real-comparison-unused-temporal-v1"
RESERVED_AT_UTC = "2026-10-11"
SOURCE_FILES = (
    "uzbekistan-retail.json",
    "revenue-series.json",
    "international-abs.json",
    "international-statcan.json",
    "external-protocol.json",
    "external-eurostat.json",
    "external-ons.json",
)


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _provider(case: PublicCase) -> str:
    prefix = case.identity.split(":")[0]
    return (
        prefix if prefix in {"abs", "statcan", "eurostat", "ons"} else "uzbekistan_siat"
    )


def _label(month: int) -> str:
    return f"{int(month) // 12:04d}-{int(month) % 12 + 1:02d}"


def _coordinates(cases: list[PublicCase]) -> set[tuple[str, int]]:
    return {
        (case.identity, case.history.forecast_start + horizon)
        for case in cases
        for horizon in range(len(case.actual))
    }


def _window(row, start, horizon, maximum_history, minimum_history, flags=None):
    first = max(int(row.months[0]), start - maximum_history)
    mapping = dict(zip(row.months, row.values, strict=True))
    values = np.asarray(
        [mapping.get(month, np.nan) for month in range(first, start + horizon)]
    )
    reason = (
        "insufficient_history"
        if start - first < minimum_history
        else "missing_suppressed_or_unreliable_month"
        if np.any(~np.isfinite(values))
        else "negative_actual_revenue"
        if np.any(values < 0)
        else "break_or_definition_change_inside_window"
        if any(
            first < month < start + horizon and ("b" in flag or "d" in flag)
            for month, flag in (flags or {}).items()
        )
        else "all_zero_history"
        if np.mean(values[:-horizon][-12:]) <= 0
        else None
    )
    if reason:
        return None, reason
    observed = values[:-horizon]
    return (
        PublicCase(
            row.identity,
            row.sector,
            row.group,
            MonthlyHistory(
                np.arange(first, start), observed, np.zeros(len(observed)), start
            ),
            values[-horizon:],
        ),
        None,
    )


def reserve_cases() -> tuple[list[PublicCase], dict]:
    """Construct count/hash-only reservation metadata; never load a model."""
    uz = load_revenue_series()
    intl = load_international_series()
    ext = load_external_series()
    old_uz, _ = build_cases(*uz)
    originals = sum(old_uz.values(), [])
    original_panels = {"uzbekistan_" + name: rows for name, rows in old_uz.items()}
    for name in ("train", "validation", "test"):
        rows, _ = build_international_cases(name, intl)
        originals.extend(rows)
        original_panels["international_" + name] = rows
    for name in ("train", "validation", "audit"):
        rows, _ = build_external_cases(name, ext)
        originals.extend(rows)
        original_panels["external_" + name] = rows
    original_public, _ = build_public_baseline_cases(load_public_data())
    public_coordinates = {
        ("retail:" + case.code, case.history.forecast_start + offset)
        for rows in original_public.values()
        for case in rows
        for offset in range(len(case.actual))
    }
    forbidden = _coordinates(originals) | public_coordinates
    seen_as_history = {
        (case.identity, int(month))
        for case in originals
        for month in case.history.months
    }
    cases, exclusions, selectors = [], [], []

    def append(row, start, horizon, cap, minimum, original_split, flags=None):
        case, reason = _window(row, start, horizon, cap, minimum, flags)
        if reason:
            exclusions.append(
                {
                    "identity": row.identity,
                    "group": row.group,
                    "original_geographic_split": original_split,
                    "target_start": _label(start),
                    "target_end": _label(start + horizon - 1),
                    "reason": reason,
                }
            )
        else:
            cases.append(case)

    for split in ("train", "validation"):
        groups = uz[1]["geographic_groups"][split]
        selectors.append(
            {
                "provider": "uzbekistan_siat",
                "original_geographic_split": split,
                "groups": groups,
                "target_start": "2026-01",
                "target_end": "2026-08",
                "horizon": 8,
                "minimum_history": 3,
                "maximum_history": 48,
            }
        )
        for row in uz[0]:
            if row.group in groups:
                append(row, parse_month("2026-01"), 8, 48, 3, split)
    for provider, plan in intl[1]["protocols"].items():
        groups = plan["geographic_groups"]["train"]
        selectors.append(
            {
                "provider": provider,
                "original_geographic_split": "train",
                "groups": groups,
                "target_start": plan["test_target_start"],
                "target_end": plan["test_target_end"],
                "horizon": 12,
                "minimum_history": plan["minimum_history_months"],
                "maximum_history": plan["maximum_case_history_months"],
            }
        )
        for row in intl[0]:
            if row.source["provider"] == provider and row.group in groups:
                append(
                    row,
                    parse_month(plan["test_target_start"]),
                    12,
                    plan["maximum_case_history_months"],
                    plan["minimum_history_months"],
                    "train",
                )
    plan = ext[1]["protocol"]
    groups = plan["geographic_groups"]["train"]
    selectors.append(
        {
            "provider": "eurostat",
            "original_geographic_split": "train",
            "groups": groups,
            "target_start": plan["audit_target_start"],
            "target_end": plan["audit_target_end"],
            "horizon": 12,
            "minimum_history": plan["minimum_history_months"],
            "maximum_history": plan["maximum_case_history_months"],
        }
    )
    for row in ext[0]:
        if row.source["provider"] == "eurostat" and row.group in groups:
            append(
                row,
                parse_month(plan["audit_target_start"]),
                12,
                plan["maximum_case_history_months"],
                plan["minimum_history_months"],
                "train",
                ext[1]["flags"].get(row.identity, {}),
            )
    cases.sort(key=lambda case: (case.identity, case.history.forecast_start))
    targets = _coordinates(cases)
    overlap = targets & forbidden
    if overlap:
        raise ValueError(
            f"Reserved targets overlap {len(overlap)} original target coordinates"
        )
    if any(
        np.any(case.history.months >= case.history.forecast_start) for case in cases
    ):
        raise ValueError("Reserved case history includes future target dates")
    if len(targets) != sum(len(case.actual) for case in cases):
        raise ValueError("Reserved target coordinates must be unique")
    identities = [
        {
            "identity": case.identity,
            "provider": _provider(case),
            "group": case.group,
            "sector": case.sector,
            "history_start": _label(case.history.months[0]),
            "history_end": _label(case.history.months[-1]),
            "history_months": len(case.history.months),
            "target_start": _label(case.history.forecast_start),
            "target_end": _label(case.history.forecast_start + len(case.actual) - 1),
            "observed_target_months": len(case.actual),
        }
        for case in cases
    ]
    providers = {}
    for provider in sorted({_provider(case) for case in cases}):
        rows = [case for case in cases if _provider(case) == provider]
        omitted = [
            entry
            for entry in exclusions
            if (
                entry["identity"].split(":")[0]
                if entry["identity"].startswith(("abs:", "statcan:", "eurostat:"))
                else "uzbekistan_siat"
            )
            == provider
        ]
        providers[provider] = {
            "cases": len(rows),
            "months": sum(len(case.actual) for case in rows),
            "series": len({case.identity for case in rows}),
            "groups": len({case.group for case in rows}),
            "excluded_cases": len(omitted),
            "exclusion_reasons": dict(Counter(entry["reason"] for entry in omitted)),
        }
    sorted_targets = [[identity, _label(month)] for identity, month in sorted(targets)]
    manifest = {
        "protocol_version": PROTOCOL_VERSION,
        "reserved_at_utc": RESERVED_AT_UTC,
        "reservation_stage": "fixed_target_coordinates_before_comparative_error_measurement",
        "evidence_status": "newly_reserved_retrospective_temporal_check_known_eras_trained_geographies",
        "selection_rule": selectors,
        "source_sha256": {
            name: hashlib.sha256((SERVICE / "data" / name).read_bytes()).hexdigest()
            for name in SOURCE_FILES
        },
        "cases": len(cases),
        "months": len(targets),
        "providers": providers,
        "case_identities_sha256": _hash(identities),
        "sorted_target_coordinates_sha256": _hash(sorted_targets),
        "actual_targets_sha256": _hash(
            [
                [
                    case.identity,
                    _label(case.history.forecast_start),
                    case.actual.tolist(),
                ]
                for case in cases
            ]
        ),
        "original_target_coordinates_sha256": _hash(sorted(forbidden)),
        "original_target_coordinates_count": len(forbidden),
        "overlap_with_original_target_coordinates": len(overlap),
        "overlap_with_original_case_history_coordinates": len(
            targets & seen_as_history
        ),
        "verified_original_panels": {
            name: {"cases": len(rows), "target_coordinates": len(_coordinates(rows))}
            for name, rows in original_panels.items()
        },
        "verified_public_baseline_panels": {
            name: {
                "cases": len(rows),
                "target_coordinates": len(
                    {
                        (case.code, case.history.forecast_start + offset)
                        for case in rows
                        for offset in range(len(case.actual))
                    }
                ),
            }
            for name, rows in original_public.items()
        },
        "case_identities": identities,
        "sorted_target_coordinates": sorted_targets,
        "exclusions": sorted(
            exclusions, key=lambda row: (row["identity"], row["target_start"])
        ),
        "limitations": [
            "Current revised published vintages, known economic eras and original trained/validation geographies; not new providers or independent borrower labels.",
            "Target coordinates were absent from all original real train/development/final builders and the original public retail baseline builders, including ONS audit targets.",
            "Prior ad hoc label access outside committed builders is not proven absent; reservation is retrospective and comparison remains exploratory.",
            "No real expenses, capacity, repayment or default outcomes; no currency conversion is declared.",
        ],
    }
    return cases, manifest


def load_reserved_cases() -> tuple[list[PublicCase], dict]:
    """Return validated frozen cases and exclusions/provenance from the reservation."""
    if not MANIFEST_PATH.exists():
        raise ValueError(
            "Reserve target coordinates and save manifest before evaluation"
        )
    recorded = json.loads(MANIFEST_PATH.read_text())
    cases, actual = reserve_cases()
    if recorded != actual:
        raise ValueError("Reserved temporal targets, source data or protocol changed")
    return cases, recorded
