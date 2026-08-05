from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from barebones_openstef import write_comparison_plot
from forecast_dataset_api import fetch_forecast_dataset, save_forecast_run
from forecast_runner import (
    BASE_URL,
    DEFAULT_CONTEXT_DAYS,
    HORIZON,
    OUTPUT_DIR,
    SAMPLE_INTERVAL,
    WEATHER_FEATURES,
    format_utc,
    metric_items,
    none_if_nan,
    parse_utc,
    prediction_context_start,
    require_positive_int,
    run_id_for_model,
)
from main import compute_metrics
from persisted_model import load_artifact, validate_required_columns
from weather_features import DEFAULT_WEATHER_PATH

DEFAULT_FORECAST_DAYS = 1


def run_id(target: str, model: str, forecast_start: datetime) -> str:
    return run_id_for_model(target, model, forecast_start)


def payload_from_forecast(
    *,
    run_id_value: str,
    model: str,
    model_family: str,
    target: str,
    generated_at: datetime,
    train_start: datetime | None,
    train_end: datetime | None,
    forecast_start: datetime,
    forecast_end: datetime,
    comparison: pd.DataFrame,
    metrics: dict[str, Any],
    artifact_dir: Path,
) -> dict[str, Any]:
    return {
        "runId": run_id_value,
        "model": model,
        "target": target,
        "modelFamily": model_family,
        "generatedAt": format_utc(generated_at),
        "trainStart": format_utc(train_start) if train_start is not None else None,
        "trainEnd": format_utc(train_end) if train_end is not None else None,
        "forecastStart": format_utc(forecast_start),
        "forecastEnd": format_utc(forecast_end),
        "sampleInterval": SAMPLE_INTERVAL,
        "horizon": HORIZON,
        "reportPath": str(artifact_dir),
        "points": [
            {
                "timestamp": format_utc(index.to_pydatetime()),
                "forecastKwh": none_if_nan(row.forecast_kwh),
                "actualKwh": none_if_nan(row.actual_kwh),
            }
            for index, row in comparison.iterrows()
        ],
        "metrics": metric_items(metrics),
    }


def save_payload(payload: dict[str, Any], *, base_url: str) -> None:
    response = save_forecast_run(payload, base_url=base_url)
    point_count = response.get("forecastPoints", response.get("pointCount", len(payload["points"])))
    metric_count = response.get("metrics", response.get("metricCount", len(payload["metrics"])))
    print(f"Saved {response['runId']} to backend ({point_count} points, {metric_count} metrics)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load a persisted forecast model and save a forecast run.")
    parser.add_argument("artifact_dir")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--forecast-start", required=True)
    parser.add_argument("--forecast-days", type=int, default=DEFAULT_FORECAST_DAYS)
    parser.add_argument("--context-days", type=int, default=DEFAULT_CONTEXT_DAYS)
    parser.add_argument(
        "--allow-in-sample-forecast",
        action="store_true",
        help="Allow forecasts before the artifact trainEnd. Use only for inspection, not for unbiased evaluation.",
    )
    parser.add_argument("--weather-path", default=str(DEFAULT_WEATHER_PATH))
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    require_positive_int("forecast-days", args.forecast_days)
    require_positive_int("context-days", args.context_days)

    artifact_dir = Path(args.artifact_dir).resolve()
    workflow, metadata, schema = load_artifact(artifact_dir)
    target = metadata["target"]
    model = f"{metadata['model']}-persisted"
    model_family = metadata.get("modelFamily", "openstef-xgboost")
    train_start = parse_utc(metadata["trainStart"]) if metadata.get("trainStart") else None
    train_end = parse_utc(metadata["trainEnd"]) if metadata.get("trainEnd") else None
    forecast_start = parse_utc(args.forecast_start)
    if train_end is not None and train_end > forecast_start:
        if not args.allow_in_sample_forecast:
            raise ValueError(
                "forecast-start is before the persisted model trainEnd "
                f"({format_utc(train_end)}). This is an in-sample forecast. "
                "Use --allow-in-sample-forecast to run it anyway, or choose a later forecast-start for a true future forecast."
            )
        print(
            "Warning: forecast-start is before the persisted model trainEnd. "
            "This run is in-sample and is not valid as an unbiased backtest."
        )
    forecast_end = forecast_start + timedelta(days=args.forecast_days)
    input_start = prediction_context_start(forecast_start, args.context_days)

    dataset = fetch_forecast_dataset(
        base_url=args.base_url,
        target=target,
        start=format_utc(input_start),
        end=format_utc(forecast_end),
        include_weather=True,
        weather_path=args.weather_path,
        weather_features=WEATHER_FEATURES,
        require_complete_weather=True,
    )
    dataset.data.attrs["target"] = target
    validate_required_columns(list(dataset.data.columns), schema)
    if dataset.data.empty:
        raise ValueError("Prediction dataset is empty. Check that imported energy data and weather data are available.")

    forecast = workflow.predict(dataset, forecast_start=forecast_start)
    forecast_series = forecast.median_series.sort_index().rename("forecast_kwh")
    forecast_series = forecast_series[(forecast_series.index >= forecast_start) & (forecast_series.index < forecast_end)]
    actual = dataset.data[target].sort_index()
    actual = actual[(actual.index >= forecast_start) & (actual.index < forecast_end)]
    metrics, comparison = compute_metrics(forecast_series, actual)
    generated_at = datetime.now(timezone.utc)
    payload = payload_from_forecast(
        run_id_value=run_id(target, model, forecast_start),
        model=model,
        model_family=model_family,
        target=target,
        generated_at=generated_at,
        train_start=None if args.allow_in_sample_forecast and train_end is not None and train_end > forecast_start else train_start,
        train_end=None if args.allow_in_sample_forecast and train_end is not None and train_end > forecast_start else train_end,
        forecast_start=forecast_start,
        forecast_end=forecast_end,
        comparison=comparison,
        metrics=metrics,
        artifact_dir=artifact_dir,
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    plot_path = write_comparison_plot(output_dir, payload, {"target": target})
    save_payload(payload, base_url=args.base_url)
    print(f"Wrote persisted-model comparison plot to {plot_path}")


if __name__ == "__main__":
    main()
