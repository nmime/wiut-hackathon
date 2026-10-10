"""Offline revenue corpus and geographic/temporal splits for direct training."""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .public_data import SNAPSHOT_PATH, load_public_data

REVENUE_PATH = Path(__file__).resolve().parent.parent / "data" / "revenue-series.json"


def parse_month(value: str) -> int:
    if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", value) or value[:4] == "0000":
        raise ValueError("Invalid revenue calendar month")
    year, month = map(int, value.split("-"))
    return year * 12 + month - 1


@dataclass
class RevenueSeries:
    identity: str
    sector: str
    group: str
    months: np.ndarray
    values: np.ndarray
    source: dict


def revenue_data_digest() -> str:
    digest = hashlib.sha256()
    for path in (SNAPSHOT_PATH, REVENUE_PATH):
        digest.update(path.read_bytes())
    return digest.hexdigest()


def load_revenue_series() -> tuple[list[RevenueSeries], dict]:
    retail = load_public_data()
    additional = json.loads(REVENUE_PATH.read_text())
    if additional["format"] != 1:
        raise ValueError("Unsupported revenue snapshot format")
    series = []
    for row in retail["series"]:
        if row["is_national_total"]:
            continue
        series.append(
            RevenueSeries(
                "retail:" + row["code"],
                "retail",
                row["code"],
                np.asarray(
                    [parse_month(value["month"]) for value in row["observations"]]
                ),
                np.asarray(
                    [value["monthly_million_uzs"] for value in row["observations"]],
                    dtype=float,
                ),
                retail["source"],
            )
        )
    for dataset in additional["datasets"]:
        source = dataset["source"]
        if source["license"] != "CC BY 4.0":
            raise ValueError("Revenue source license not declared")
        for row in dataset["series"]:
            eligible = row["level"] == (
                "region" if source["sector"] == "wholesale" else "district"
            )
            if not eligible:
                continue  # Exclude national/parent totals, never duplicate children.
            months = np.asarray([parse_month(value) for value in row["months"]])
            values = np.asarray(row["monthly_million_uzs"], dtype=float)
            if len(months) != len(values) or np.any(np.diff(months) <= 0):
                raise ValueError(
                    "Revenue series arrays must be aligned and ordered uniquely"
                )
            keep = months >= parse_month(source["usable_from"])
            series.append(
                RevenueSeries(
                    source["sector"] + ":" + row["code"],
                    source["sector"],
                    row["geographic_group"],
                    months[keep],
                    values[keep],
                    source,
                )
            )
    groups = sorted(
        {row.group for row in series},
        key=lambda code: hashlib.sha256(
            ("public-region-v1:" + code).encode()
        ).hexdigest(),
    )
    if len({row.identity for row in series}) != len(series):
        raise ValueError("Duplicate revenue series identity")
    if len(groups) != 14:
        raise ValueError(
            "Unexpected geographic classification; review split explicitly"
        )
    splits = {"train": groups[:8], "validation": groups[8:11], "test": groups[11:]}
    metadata = {
        "data_sha256": revenue_data_digest(),
        "sources": [retail["source"]]
        + [dataset["source"] for dataset in additional["datasets"]],
        "published_observations": sum(
            len(row["observations"]) for row in retail["series"]
        )
        + sum(
            len(row["months"])
            for dataset in additional["datasets"]
            for row in dataset["series"]
        ),
        "eligible_series": len(series),
        "eligible_observations_after_regime_filter": sum(
            len(row.months) for row in series
        ),
        "geographic_groups": splits,
        "quality_issues": [
            {"sector": dataset["source"]["sector"], **issue}
            for dataset in additional["datasets"]
            for issue in dataset["quality_issues"]
        ],
    }
    return series, metadata
