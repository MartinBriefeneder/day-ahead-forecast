from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

BASE_URL = "http://localhost:8080"
DEFAULT_TARGET = "generation"
DEFAULT_TRAIN_START = "2025-06-11T00:00:00Z"
DEFAULT_TRAIN_DAYS = 90
DEFAULT_FORECAST_DAYS = 7
DEFAULT_CONTEXT_DAYS = 14
OUTPUT_DIR = (Path(__file__).resolve().parent / "../reports/forecast-runs").resolve()

SAMPLE_INTERVAL = "PT15M"
HORIZON = "PT36H"
WEATHER_FEATURES = (
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "shortwave_radiation",
    "surface_pressure",
)


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def run_id_for_model(target: str, model: str, forecast_start: datetime) -> str:
    timestamp = forecast_start.strftime("%Y%m%dT%H%M%SZ")
    return f"{target}-{model}-{timestamp}"


def none_if_nan(value: object) -> float | None:
    if pd.isna(value):
        return None
    return float(value)


def metric_items(metrics: dict[str, Any]) -> list[dict[str, float]]:
    return [
        {"name": name, "value": float(value)}
        for name, value in metrics.items()
        if isinstance(value, int | float) and pd.notna(value)
    ]


def require_positive_int(name: str, value: int) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive")


def prediction_context_start(forecast_start: datetime, context_days: int = DEFAULT_CONTEXT_DAYS) -> datetime:
    require_positive_int("context-days", context_days)
    return forecast_start - timedelta(days=context_days)
