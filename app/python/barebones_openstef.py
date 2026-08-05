from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from forecast_dataset_api import fetch_forecast_dataset, save_forecast_run
from forecast_runner import (
    BASE_URL,
    DEFAULT_FORECAST_DAYS,
    DEFAULT_TARGET,
    DEFAULT_TRAIN_DAYS,
    DEFAULT_TRAIN_START,
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
from persisted_model import DEFAULT_MODEL_ROOT, artifact_directory, openstef_feature_schema, openstef_metadata, write_artifact
from weather_features import DEFAULT_WEATHER_PATH

MODEL_NAME = "openstef-barebones"
MODEL_FAMILY = "openstef-xgboost"


def run_id(target: str, forecast_start: datetime) -> str:
    return run_id_for_model(target, MODEL_NAME, forecast_start)


def create_barebones_workflow(target: str):
    from openstef_core.types import LeadTime, Q
    from openstef_models.models.forecasting.xgboost_forecaster import XGBoostHyperParams
    from openstef_models.presets import ForecastingWorkflowConfig, create_forecasting_workflow

    config = ForecastingWorkflowConfig(
        model_id=f"{target}_barebones_xgboost",
        model="xgboost",
        horizons=[LeadTime.from_string(HORIZON)],
        quantiles=[Q(0.5), Q(0.1), Q(0.9)],
        target_column=target,
        temperature_column="temperature_2m",
        relative_humidity_column="relative_humidity_2m",
        wind_speed_column="wind_speed_10m",
        radiation_column="shortwave_radiation",
        pressure_column="surface_pressure",
        xgboost_hyperparams=XGBoostHyperParams(),
        mlflow_storage=None,
        verbosity=0,
    )
    return create_forecasting_workflow(config), config


def api_payload(
    *,
    target: str,
    generated_at: datetime,
    train_start: datetime | None = None,
    train_end: datetime | None = None,
    forecast_start: datetime,
    forecast_end: datetime,
    comparison: pd.DataFrame,
    metrics: dict[str, Any],
    report_path: str | Path | None = None,
) -> dict[str, Any]:
    return {
        "runId": run_id(target, forecast_start),
        "model": MODEL_NAME,
        "target": target,
        "modelFamily": MODEL_FAMILY,
        "generatedAt": format_utc(generated_at),
        "trainStart": format_utc(train_start) if train_start is not None else None,
        "trainEnd": format_utc(train_end) if train_end is not None else None,
        "forecastStart": format_utc(forecast_start),
        "forecastEnd": format_utc(forecast_end),
        "sampleInterval": SAMPLE_INTERVAL,
        "horizon": HORIZON,
        "reportPath": str(report_path) if report_path is not None else None,
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


def forecast_payload(
    *,
    workflow,
    target: str,
    predict_dataset,
    generated_at: datetime,
    train_start: datetime,
    train_end: datetime,
    forecast_start: datetime,
    forecast_end: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    forecast = workflow.predict(predict_dataset, forecast_start=forecast_start)
    actual = predict_dataset.data[target].sort_index()
    actual = actual[(actual.index >= forecast_start) & (actual.index < forecast_end)]
    metrics, comparison = compute_metrics(forecast.median_series.rename("forecast_kwh"), actual)
    return (
        api_payload(
            target=target,
            generated_at=generated_at,
            train_start=train_start,
            train_end=train_end,
            forecast_start=forecast_start,
            forecast_end=forecast_end,
            comparison=comparison,
            metrics=metrics,
        ),
        metrics,
    )


def write_run_files(output_dir: Path, payload: dict[str, Any], metadata: dict[str, Any]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    plot_path = write_comparison_plot(output_dir, payload, metadata)
    metadata["comparisonPlot"] = plot_path.name
    return plot_path


def write_comparison_plot(output_dir: Path, payload: dict[str, Any], metadata: dict[str, Any]) -> Path:
    from plotly import graph_objects as go

    plot_path = output_dir / "openstef-barebones-comparison.html"
    target_label = str(metadata["target"]).capitalize()
    points = payload["points"]

    fig = go.Figure()
    actual_values = [point.get("actualKwh") for point in points]
    if any(value is not None for value in actual_values):
        fig.add_trace(
            go.Scatter(
                x=[point["timestamp"] for point in points],
                y=actual_values,
                mode="lines",
                name=f"Actual {target_label}",
                line={"color": "#111827", "width": 2},
            )
        )
    fig.add_trace(
        go.Scatter(
            x=[point["timestamp"] for point in points],
            y=[point.get("forecastKwh") for point in points],
            mode="lines",
            name=MODEL_NAME,
        )
    )

    fig.update_layout(
        title=f"OpenSTEF {target_label} Barebones Forecast vs Actual",
        xaxis_title="Time (UTC)",
        yaxis_title=f"{target_label} energy (kWh per 15-minute interval)",
        hovermode="x unified",
        template="plotly_white",
        height=540,
    )
    fig.write_html(plot_path, include_plotlyjs=True)
    return plot_path


def format_metric(value: object) -> str:
    if value is None:
        return ""
    return f"{float(value):.4f}"


def save_payload(payload: dict[str, Any], *, base_url: str) -> None:
    response = save_forecast_run(payload, base_url=base_url)
    point_count = response.get("forecastPoints", response.get("pointCount", len(payload["points"])))
    metric_count = response.get("metrics", response.get("metricCount", len(payload["metrics"])))
    print(f"Saved {response['runId']} to backend ({point_count} points, {metric_count} metrics)")


def persist_workflow(
    *,
    workflow,
    config,
    model_root: str | Path,
    target: str,
    train_start: datetime,
    train_end: datetime,
    created_at: datetime,
    weather_path: str,
) -> Path:
    artifact_dir = artifact_directory(model_root, target=target, model=MODEL_NAME, created_at=created_at)
    schema = openstef_feature_schema(target=target, weather_features=WEATHER_FEATURES, sample_interval=SAMPLE_INTERVAL)
    metadata = openstef_metadata(
        target=target,
        model=MODEL_NAME,
        model_family=MODEL_FAMILY,
        train_start=train_start,
        train_end=train_end,
        created_at=created_at,
        weather_path=weather_path,
        artifact_dir=artifact_dir,
        sample_interval=SAMPLE_INTERVAL,
        horizon=HORIZON,
        xgboost_hyperparameters=config.xgboost_hyperparams.model_dump(mode="json"),
    )
    write_artifact(artifact_dir, model=workflow, metadata=metadata, feature_schema=schema)
    return artifact_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a barebones OpenSTEF XGBoost forecast.")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--target", default=DEFAULT_TARGET, choices=("generation", "consumption"))
    parser.add_argument("--train-start", default=DEFAULT_TRAIN_START)
    parser.add_argument("--train-days", type=int, default=DEFAULT_TRAIN_DAYS)
    parser.add_argument("--forecast-days", type=int, default=DEFAULT_FORECAST_DAYS)
    parser.add_argument("--weather-path", default=str(DEFAULT_WEATHER_PATH))
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--persist-model", action="store_true", help="Write the trained model as a local artifact.")
    parser.add_argument("--model-root", default=str(DEFAULT_MODEL_ROOT))
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    require_positive_int("train-days", args.train_days)
    require_positive_int("forecast-days", args.forecast_days)
    train_start = parse_utc(args.train_start)
    train_end = train_start + timedelta(days=args.train_days)
    forecast_start = train_end
    forecast_end = forecast_start + timedelta(days=args.forecast_days)

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
    if dataset.data.empty:
        raise ValueError("Dataset is empty. Check that imported energy data and weather data are available.")

    train_dataset = dataset.filter_by_range(start=train_start, end=train_end)
    predict_dataset = dataset.filter_by_range(start=prediction_context_start(train_end), end=forecast_end)
    train_dataset.data.attrs["target"] = args.target

    print(f"Training rows: {len(train_dataset.data):,}")
    print(f"Prediction rows: {len(predict_dataset.data):,}")

    workflow, config = create_barebones_workflow(args.target)
    workflow.fit(train_dataset)

    generated_at = datetime.now(timezone.utc)
    payload, metrics = forecast_payload(
        workflow=workflow,
        target=args.target,
        predict_dataset=predict_dataset,
        generated_at=generated_at,
        train_start=train_start,
        train_end=train_end,
        forecast_start=forecast_start,
        forecast_end=forecast_end,
    )

    weather_diagnostics = dataset.data.attrs.get("weather_diagnostics", {})
    metadata = {
        "generatedAt": format_utc(generated_at),
        "target": args.target,
        "model": MODEL_NAME,
        "modelFamily": MODEL_FAMILY,
        "trainStart": format_utc(train_start),
        "trainEnd": format_utc(train_end),
        "forecastStart": format_utc(forecast_start),
        "forecastEnd": format_utc(forecast_end),
        "sampleInterval": SAMPLE_INTERVAL,
        "horizon": HORIZON,
        "weatherPath": str(args.weather_path),
        "weatherAlignment": weather_diagnostics.get("alignment", {}),
        "xgboostHyperparameters": config.xgboost_hyperparams.model_dump(mode="json"),
    }

    plot_path = write_run_files(Path(args.output_dir), payload, metadata)
    if args.persist_model:
        artifact_dir = persist_workflow(
            workflow=workflow,
            config=config,
            model_root=args.model_root,
            target=args.target,
            train_start=train_start,
            train_end=train_end,
            created_at=generated_at,
            weather_path=args.weather_path,
        )
        print(f"Wrote model artifact to {artifact_dir}")
    save_payload(payload, base_url=args.base_url)

    print(f"Wrote barebones comparison plot to {plot_path}")
    print(f"{MODEL_NAME}: MAE={metrics['mae_kwh']:.4f} kWh, RMSE={metrics['rmse_kwh']:.4f} kWh")


if __name__ == "__main__":
    main()
