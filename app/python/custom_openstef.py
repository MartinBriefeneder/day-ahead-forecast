from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from forecast_dataset_api import fetch_forecast_dataset, save_forecast_run
from default_openstef_xgboost import needs_future_prediction_data
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
    forecast_start_is_future,
    log_step,
    metric_items,
    metric_summary,
    none_if_nan,
    openstef_weather_config_kwargs,
    parse_utc,
    prediction_context_start,
    resolve_forecast_window,
    run_id_for_model,
    timestamped_report_path,
)
from future_openstef_xgboost import build_prediction_frame as build_future_prediction_frame
from future_openstef_xgboost import build_training_frame as build_future_training_frame
from future_openstef_xgboost import time_series_dataset
from main import compute_metrics
from weather_features import DEFAULT_GRIDOO_LOCATION_ID, DEFAULT_WEATHER_PATH

MODEL_NAME = "openstef-custom-ensemble"
MODEL_FAMILY = "openstef-ensemble"
EXTENSION_POINT = "EnsembleForecastingWorkflowConfig"
DEFAULT_BASE_MODELS = "lgbm,gblinear"
DEFAULT_COMBINER_MODEL = "lgbm"
DEFAULT_ENSEMBLE_TYPE = "learned_weights"


def parse_base_models(value: str) -> list[str]:
    models = [item.strip() for item in value.split(",") if item.strip()]
    if not models:
        raise ValueError("At least one base model must be provided")
    return models


def run_id(target: str, forecast_start: datetime, forecast_end: datetime) -> str:
    return run_id_for_model(target, MODEL_NAME, forecast_start, forecast_end)


def create_custom_workflow(target: str, *, base_models: list[str], combiner_model: str, ensemble_type: str, weather_features: tuple[str, ...] = WEATHER_FEATURES):
    from openstef_core.types import LeadTime, Q
    from openstef_meta.presets import EnsembleForecastingWorkflowConfig, create_ensemble_forecasting_workflow

    config = EnsembleForecastingWorkflowConfig(
        model_id=f"{target}_custom_ensemble",
        ensemble_type=ensemble_type,
        base_models=base_models,
        combiner_model=combiner_model,
        horizons=[LeadTime.from_string(HORIZON)],
        quantiles=[Q(0.1), Q(0.5), Q(0.9)],
        target_column=target,
        **openstef_weather_config_kwargs(weather_features),
        mlflow_storage=None,
    )
    return create_ensemble_forecasting_workflow(config), config


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
        "runId": run_id(target, forecast_start, forecast_end),
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


def validation_metrics(fit_result) -> dict[str, float]:
    from openstef_core.types import Q

    metrics = {}
    try:
        for name, child_result in fit_result.component_fit_results.items():
            metrics[f"{name}_r2"] = float(child_result.metrics_val.get_metric(quantile=Q(0.5), metric_name="R2"))
        metrics["ensemble_r2"] = float(fit_result.metrics_val.get_metric(quantile=Q(0.5), metric_name="R2"))
    except (AttributeError, KeyError, TypeError, ValueError):
        return {}
    return metrics


def write_run_files(output_dir: Path, payload: dict[str, Any], metadata: dict[str, Any]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    plot_path = write_comparison_plot(output_dir, payload, metadata)
    metadata["comparisonPlot"] = plot_path.name
    return plot_path


def write_comparison_plot(output_dir: Path, payload: dict[str, Any], metadata: dict[str, Any]) -> Path:
    from plotly import graph_objects as go

    plot_path = timestamped_report_path(
        output_dir,
        f"{metadata['target']}-openstef-custom-ensemble-comparison",
        generated_at=metadata.get("generatedAt"),
    )
    target_label = str(metadata["target"]).capitalize()
    points = payload["points"]
    has_actual = any(point.get("actualKwh") is not None for point in points)

    fig = go.Figure()
    actual_values = [point.get("actualKwh") for point in points]
    if has_actual:
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
        title=f"Custom OpenSTEF {target_label} Ensemble Forecast"
        f"{' vs Actual' if has_actual else ''}",
        xaxis_title="Time (UTC)",
        yaxis_title=f"{target_label} energy (kWh per 15-minute interval)",
        hovermode="x unified",
        template="plotly_white",
        height=540,
    )
    fig.write_html(plot_path, include_plotlyjs=True)
    return plot_path


def format_metric(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return f"{float(value):.4f}"


def save_payload(payload: dict[str, Any], *, base_url: str) -> None:
    response = save_forecast_run(payload, base_url=base_url)
    point_count = response.get("forecastPoints", response.get("pointCount", len(payload["points"])))
    metric_count = response.get("metrics", response.get("metricCount", len(payload["metrics"])))
    print(f"Saved {response['runId']} to backend ({point_count} points, {metric_count} metrics)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a custom OpenSTEF ensemble forecast.")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--target", default=DEFAULT_TARGET, choices=("generation", "consumption"))
    parser.add_argument("--train-start")
    parser.add_argument("--train-days", type=int, default=DEFAULT_TRAIN_DAYS)
    parser.add_argument("--forecast-start", help="UTC ISO timestamp. Defaults to train-start plus train-days.")
    parser.add_argument("--forecast-days", type=int, default=DEFAULT_FORECAST_DAYS)
    parser.add_argument("--base-models", default=DEFAULT_BASE_MODELS)
    parser.add_argument("--combiner-model", default=DEFAULT_COMBINER_MODEL)
    parser.add_argument("--ensemble-type", default=DEFAULT_ENSEMBLE_TYPE)
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
    base_models = parse_base_models(args.base_models)
    log_step(
        f"{MODEL_NAME} start target={args.target} train_start={format_utc(train_start)} "
        f"train_end={format_utc(train_end)} forecast_start={format_utc(forecast_start)} "
        f"forecast_end={format_utc(forecast_end)} base_models={','.join(base_models)} "
        f"combiner_model={args.combiner_model} ensemble_type={args.ensemble_type}"
    )

    log_step(f"{MODEL_NAME} check forecast data availability")
    future_run = needs_future_prediction_data(
        base_url=args.base_url,
        target=args.target,
        forecast_start=forecast_start,
        forecast_end=forecast_end,
    )
    weather_features = FORECAST_WEATHER_FEATURES if future_run else WEATHER_FEATURES
    log_step(f"{MODEL_NAME} data mode={'future' if future_run else 'backtest'} weather_features={','.join(weather_features)}")
    if future_run:
        log_step(f"{MODEL_NAME} build future training frame")
        train_dataset = time_series_dataset(
            build_future_training_frame(
                base_url=args.base_url,
                target=args.target,
                train_start=train_start,
                train_end=train_end,
                weather_path=args.weather_path,
            )
        )
        log_step(f"{MODEL_NAME} build future prediction frame")
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
        log_step(f"{MODEL_NAME} fetch backtest dataset with weather")
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
        predict_dataset = dataset.filter_by_range(start=prediction_context_start(forecast_start), end=forecast_end)
        train_dataset.data.attrs["target"] = args.target

    print(f"Training rows: {len(train_dataset.data):,}")
    print(f"Prediction rows: {len(predict_dataset.data):,}")

    log_step(f"{MODEL_NAME} create workflow")
    workflow, _ = create_custom_workflow(
        args.target,
        base_models=base_models,
        combiner_model=args.combiner_model,
        ensemble_type=args.ensemble_type,
        weather_features=weather_features,
    )
    log_step(f"{MODEL_NAME} fit workflow")
    fit_result = workflow.fit(train_dataset)

    generated_at = datetime.now(timezone.utc)
    log_step(f"{MODEL_NAME} predict and build payload")
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

    weather_diagnostics = train_dataset.data.attrs.get("weather_diagnostics", {})
    metadata = {
        "generatedAt": format_utc(generated_at),
        "target": args.target,
        "model": MODEL_NAME,
        "modelFamily": MODEL_FAMILY,
        "extensionPoint": EXTENSION_POINT,
        "baseModels": base_models,
        "combinerModel": args.combiner_model,
        "ensembleType": args.ensemble_type,
        "trainStart": format_utc(train_start),
        "trainEnd": format_utc(train_end),
        "forecastStart": format_utc(forecast_start),
        "forecastEnd": format_utc(forecast_end),
        "sampleInterval": SAMPLE_INTERVAL,
        "horizon": HORIZON,
        "weatherPath": str(args.weather_path),
        "weatherAlignment": weather_diagnostics.get("alignment", {}),
        "validationMetrics": validation_metrics(fit_result),
    }

    log_step(f"{MODEL_NAME} write report files")
    plot_path = write_run_files(Path(args.output_dir), payload, metadata)
    payload["reportPath"] = str(plot_path)
    log_step(f"{MODEL_NAME} save run_id={payload['runId']}")
    save_payload(payload, base_url=args.base_url)

    print(f"Wrote custom OpenSTEF comparison plot to {plot_path}")
    print(metric_summary(MODEL_NAME, metrics))


if __name__ == "__main__":
    main()
