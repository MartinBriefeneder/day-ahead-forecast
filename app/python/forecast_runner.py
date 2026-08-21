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
FORECAST_WEATHER_FEATURES = (
    "temperature_2m",
    "wind_speed_10m",
    "shortwave_radiation",
)
OPENSTEF_WEATHER_COLUMNS = {
    "temperature_2m": "temperature_column",
    "relative_humidity_2m": "relative_humidity_column",
    "wind_speed_10m": "wind_speed_column",
    "shortwave_radiation": "radiation_column",
    "surface_pressure": "pressure_column",
}


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def log_step(message: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    print(f"[forecast-python] {timestamp} {message}", flush=True)


def run_id_for_model(target: str, model: str, forecast_start: datetime) -> str:
    timestamp = forecast_start.strftime("%Y%m%dT%H%M%SZ")
    return f"{target}-{model}-{timestamp}"


def report_timestamp(value: datetime | str | None = None) -> str:
    if value is None:
        parsed = datetime.now(timezone.utc)
    elif isinstance(value, datetime):
        parsed = value
    else:
        parsed = parse_utc(value)
    return parsed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def timestamped_report_path(
    output_dir: Path,
    stem: str,
    suffix: str = ".html",
    generated_at: datetime | str | None = None,
) -> Path:
    return output_dir / f"{stem}-{report_timestamp(generated_at)}{suffix}"


def none_if_nan(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def metric_items(metrics: dict[str, Any]) -> list[dict[str, float]]:
    items = []
    for name, value in metrics.items():
        try:
            numeric_value = none_if_nan(value)
        except (TypeError, ValueError):
            continue
        if numeric_value is not None:
            items.append({"name": name, "value": numeric_value})
    return items


def metric_summary(model: str, metrics: dict[str, Any]) -> str:
    if metrics.get("aligned_intervals", 0):
        return (
            f"{model}: MAE={metrics['mae_kwh']:.4f} kWh, "
            f"RMSE={metrics['rmse_kwh']:.4f} kWh, aligned={metrics['aligned_intervals']}"
        )
    return (
        f"{model}: total forecast={metrics['total_forecast_kwh']:.4f} kWh, "
        f"aligned=0, missing actual={metrics['missing_actual_intervals']}"
    )


def require_positive_int(name: str, value: int) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive")


def prediction_context_start(forecast_start: datetime, context_days: int = DEFAULT_CONTEXT_DAYS) -> datetime:
    require_positive_int("context-days", context_days)
    return forecast_start - timedelta(days=context_days)


def forecast_start_is_future(forecast_start: datetime, now: datetime | None = None) -> bool:
    reference = datetime.now(timezone.utc) if now is None else now.astimezone(timezone.utc)
    return forecast_start.astimezone(timezone.utc) >= reference


def openstef_weather_config_kwargs(weather_features: tuple[str, ...]) -> dict[str, str]:
    unknown = [feature for feature in weather_features if feature not in OPENSTEF_WEATHER_COLUMNS]
    if unknown:
        raise ValueError("Unsupported OpenSTEF weather feature(s): " + ", ".join(unknown))
    return {OPENSTEF_WEATHER_COLUMNS[feature]: feature for feature in weather_features}


def resolve_training_window_for_forecast(
    *,
    train_start: str | None,
    train_days: int,
    forecast_start: datetime,
) -> tuple[datetime, datetime]:
    require_positive_int("train-days", train_days)
    if train_start:
        resolved_train_start = parse_utc(train_start)
    elif forecast_start_is_future(forecast_start):
        resolved_train_start = parse_utc(DEFAULT_TRAIN_START)
    else:
        resolved_train_start = forecast_start - timedelta(days=train_days)
    resolved_train_end = resolved_train_start + timedelta(days=train_days)
    if forecast_start_is_future(forecast_start) and resolved_train_end > forecast_start:
        raise ValueError("Training window must end before or at forecast-start for a future forecast.")
    if not forecast_start_is_future(forecast_start):
        resolved_train_end = forecast_start
    if not resolved_train_end > resolved_train_start:
        raise ValueError("Training window must end after train-start")
    return resolved_train_start, resolved_train_end


def resolve_forecast_window(
    *,
    train_start: str | None,
    train_days: int,
    forecast_start: str | None,
    forecast_days: int,
) -> tuple[datetime, datetime, datetime, datetime]:
    require_positive_int("train-days", train_days)
    require_positive_int("forecast-days", forecast_days)
    if forecast_start:
        resolved_forecast_start = parse_utc(forecast_start)
        resolved_train_start, resolved_train_end = resolve_training_window_for_forecast(
            train_start=train_start,
            train_days=train_days,
            forecast_start=resolved_forecast_start,
        )
    else:
        resolved_train_start = parse_utc(train_start) if train_start else parse_utc(DEFAULT_TRAIN_START)
        resolved_train_end = resolved_train_start + timedelta(days=train_days)
        resolved_forecast_start = resolved_train_end

    if not resolved_train_end > resolved_train_start:
        raise ValueError("Training window must end after train-start")
    return (
        resolved_train_start,
        resolved_train_end,
        resolved_forecast_start,
        resolved_forecast_start + timedelta(days=forecast_days),
    )
