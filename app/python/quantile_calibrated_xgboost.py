from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from default_openstef_xgboost import create_default_openstef_xgboost_workflow, needs_future_prediction_data
from forecast_dataset_api import fetch_forecast_dataset
from forecast_runner import (
    BASE_URL,
    DEFAULT_FORECAST_DAYS,
    DEFAULT_TARGET,
    DEFAULT_TRAIN_DAYS,
    FORECAST_WEATHER_FEATURES,
    HORIZON,
    OUTPUT_DIR,
    SAMPLE_INTERVAL,
    WEATHER_FEATURES,
    format_utc,
    log_step,
    prediction_context_start,
    resolve_forecast_window,
    timestamped_report_path,
)
from future_openstef_xgboost import build_prediction_frame as build_future_prediction_frame
from future_openstef_xgboost import build_training_frame as build_future_training_frame
from future_openstef_xgboost import time_series_dataset
from main import compute_metrics
from weather_features import DEFAULT_GRIDOO_LOCATION_ID, DEFAULT_WEATHER_PATH

MODEL_NAME = "openstef-xgboost-quantile-calibrated"
MODEL_FAMILY = "openstef-xgboost"
QUANTILES = (0.1, 0.5, 0.9)


def quantile_column(quantile: float) -> str:
    return f"p{int(quantile * 100):02d}_kwh"


def extract_quantile_series(forecast: Any, quantiles: tuple[float, ...] = QUANTILES) -> dict[float, pd.Series]:
    result: dict[float, pd.Series] = {}
    candidates = [
        getattr(forecast, "quantile_series", None),
        getattr(forecast, "quantile_forecasts", None),
        getattr(forecast, "quantiles", None),
    ]
    for candidate in candidates:
        if isinstance(candidate, dict):
            for quantile in quantiles:
                value = candidate.get(quantile, candidate.get(str(quantile)))
                if isinstance(value, pd.Series):
                    result[quantile] = value.sort_index()
    quantiles_data = getattr(forecast, "quantiles_data", None)
    if isinstance(quantiles_data, pd.DataFrame):
        for quantile in quantiles:
            column = f"quantile_P{int(quantile * 100):02d}"
            if column in quantiles_data.columns:
                result[quantile] = quantiles_data[column].sort_index()
    if not result and hasattr(forecast, "median_series"):
        result[0.5] = forecast.median_series.sort_index()
    missing = [quantile for quantile in quantiles if quantile not in result]
    if missing:
        raise ValueError("Forecast output is missing quantile series: " + ", ".join(map(str, missing)))
    return result


def quantile_frame(quantiles: dict[float, pd.Series], actual: pd.Series) -> pd.DataFrame:
    frame = pd.DataFrame({quantile_column(quantile): series for quantile, series in quantiles.items()}).sort_index()
    if not actual.empty:
        frame["actual_kwh"] = actual.sort_index()
    else:
        frame["actual_kwh"] = pd.NA
    frame["forecast_kwh"] = frame[quantile_column(0.5)]
    return frame


def quantile_metrics(frame: pd.DataFrame) -> dict[str, float | int | None]:
    aligned = frame.dropna(subset=["actual_kwh", quantile_column(0.1), quantile_column(0.9)])
    result: dict[str, float | int | None] = {
        "quantile_interval_count": int(len(frame)),
        "quantile_aligned_intervals": int(len(aligned)),
        "p10_p90_coverage_percent": None,
        "mean_prediction_interval_width_kwh": None,
    }
    if aligned.empty:
        return result
    within_band = (aligned["actual_kwh"] >= aligned[quantile_column(0.1)]) & (
        aligned["actual_kwh"] <= aligned[quantile_column(0.9)]
    )
    result["p10_p90_coverage_percent"] = float(within_band.mean() * 100)
    result["mean_prediction_interval_width_kwh"] = float(
        (aligned[quantile_column(0.9)] - aligned[quantile_column(0.1)]).mean()
    )
    return result


def write_quantile_csv(output_dir: Path, target: str, frame: pd.DataFrame, generated_at: datetime) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = timestamped_report_path(output_dir, f"{target}-xgboost-quantile-forecast", suffix=".csv", generated_at=generated_at)
    rows = frame.reset_index().rename(columns={"index": "timestamp"})
    rows.to_csv(path, index=False, quoting=csv.QUOTE_MINIMAL)
    return path


def write_quantile_plot(output_dir: Path, target: str, frame: pd.DataFrame, metrics: dict[str, Any], generated_at: datetime) -> Path:
    from plotly import graph_objects as go

    output_dir.mkdir(parents=True, exist_ok=True)
    path = timestamped_report_path(output_dir, f"{target}-xgboost-quantile-calibrated", generated_at=generated_at)
    target_label = target.capitalize()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=frame.index, y=frame[quantile_column(0.9)], line={"width": 0}, name="p90"))
    fig.add_trace(
        go.Scatter(
            x=frame.index,
            y=frame[quantile_column(0.1)],
            fill="tonexty",
            line={"width": 0},
            name="p10-p90 interval",
        )
    )
    fig.add_trace(go.Scatter(x=frame.index, y=frame[quantile_column(0.5)], mode="lines", name="median forecast"))
    if frame["actual_kwh"].notna().any():
        fig.add_trace(go.Scatter(x=frame.index, y=frame["actual_kwh"], mode="lines", name=f"Actual {target_label}"))
    coverage = metrics.get("p10_p90_coverage_percent")
    title_suffix = "" if coverage is None else f" p10-p90 coverage={coverage:.2f}%"
    fig.update_layout(
        title=f"OpenSTEF {target_label} Quantile-Calibrated XGBoost{title_suffix}",
        xaxis_title="Time (UTC)",
        yaxis_title=f"{target_label} energy (kWh per 15-minute interval)",
        hovermode="x unified",
        template="plotly_white",
        height=540,
    )
    fig.write_html(path, include_plotlyjs=True)
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run local report-only OpenSTEF XGBoost quantile forecast output.")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--target", default=DEFAULT_TARGET, choices=("generation", "consumption"))
    parser.add_argument("--train-start")
    parser.add_argument("--train-days", type=int, default=DEFAULT_TRAIN_DAYS)
    parser.add_argument("--forecast-start", help="UTC ISO timestamp. Defaults to train-start plus train-days.")
    parser.add_argument("--forecast-days", type=int, default=DEFAULT_FORECAST_DAYS)
    parser.add_argument("--weather-path", default=str(DEFAULT_WEATHER_PATH))
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    train_start, train_end, forecast_start, forecast_end = resolve_forecast_window(
        train_start=args.train_start,
        train_days=args.train_days,
        forecast_start=args.forecast_start,
        forecast_days=args.forecast_days,
    )
    future_run = needs_future_prediction_data(
        base_url=args.base_url,
        target=args.target,
        forecast_start=forecast_start,
        forecast_end=forecast_end,
    )
    weather_features = FORECAST_WEATHER_FEATURES if future_run else WEATHER_FEATURES
    log_step(f"{MODEL_NAME} output mode=local-report-only quantiles=p10,p50,p90")
    if future_run:
        train_dataset = time_series_dataset(
            build_future_training_frame(
                base_url=args.base_url,
                target=args.target,
                train_start=train_start,
                train_end=train_end,
                weather_path=args.weather_path,
            )
        )
        predict_dataset = time_series_dataset(
            build_future_prediction_frame(
                base_url=args.base_url,
                target=args.target,
                context_start=prediction_context_start(forecast_start),
                forecast_start=forecast_start,
                forecast_end=forecast_end,
                weather_path=args.weather_path,
                gridoo_location_id=DEFAULT_GRIDOO_LOCATION_ID,
            )
        )
    else:
        dataset = fetch_forecast_dataset(
            base_url=args.base_url,
            target=args.target,
            start=format_utc(train_start),
            end=format_utc(forecast_end),
            include_weather=True,
            weather_path=args.weather_path,
            weather_features=WEATHER_FEATURES,
            require_complete_weather=True,
        )
        dataset.data.attrs["target"] = args.target
        train_dataset = dataset.filter_by_range(start=train_start, end=train_end)
        predict_dataset = dataset.filter_by_range(start=prediction_context_start(forecast_start), end=forecast_end)

    workflow, _ = create_default_openstef_xgboost_workflow(args.target, weather_features)
    workflow.fit(train_dataset)
    forecast = workflow.predict(predict_dataset, forecast_start=forecast_start)
    actual = predict_dataset.data[args.target].sort_index()
    actual = actual[(actual.index >= forecast_start) & (actual.index < forecast_end)]
    frame = quantile_frame(extract_quantile_series(forecast), actual)
    point_metrics, _ = compute_metrics(frame["forecast_kwh"], actual)
    metrics = {**point_metrics, **quantile_metrics(frame)}
    generated_at = datetime.now(timezone.utc)
    csv_path = write_quantile_csv(Path(args.output_dir), args.target, frame, generated_at)
    plot_path = write_quantile_plot(Path(args.output_dir), args.target, frame, metrics, generated_at)
    print(f"Wrote quantile forecast CSV to {csv_path}")
    print(f"Wrote quantile forecast plot to {plot_path}")
    print("Quantile forecasts are local report-only; backend quantile persistence is not implemented.")


if __name__ == "__main__":
    main()
