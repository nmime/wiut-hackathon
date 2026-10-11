"""Загрузка артефактов при старте сервиса."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from config import ARTIFACTS_DIR
from models.forecast import ForecastModel


@dataclass
class ModelBundle:
    forecast: ForecastModel
    buffer_k: float
    buffer_k_risk: float | None
    ref_load: float
    population: dict
    calibration: dict
    meta: dict

    @property
    def version(self) -> str:
        return self.meta.get("model_version", "unknown")


def load_bundle(d: Path = ARTIFACTS_DIR) -> ModelBundle:
    if not (d / "meta.json").exists():
        raise FileNotFoundError(
            f"нет артефактов модели в {d}. Запустите: python -m generator.cli --seed 42 && "
            f"python -m models.train --data data/synthetic/seed_42")
    rd = lambda n: json.loads((d / n).read_text(encoding="utf-8"))  # noqa: E731
    meta = rd("meta.json")
    calib = rd("calibration.json")
    return ModelBundle(ForecastModel.load(d, meta), calib["buffer_k"], calib.get("buffer_k_risk"),
                       calib["ref_load"],
                       rd("population.json"), calib, meta)
