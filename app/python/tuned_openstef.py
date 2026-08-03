from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from forecast_dataset_api import fetch_forecast_dataset, save_forecast_run
from main import compute_metrics
from weather_features import DEFAULT_WEATHER_PATH

BASE_URL = "http://localhost:8080"
DEFAULT_TARGET = "generation"
DEFAULT_TRAIN_START = "2025-06-11T00:00:00Z"
DEFAULT_TRAIN_DAYS = 90
DEFAULT_FORECAST_DAYS = 7
DEFAULT_N_TRIALS = 10
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
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def run_id(target: str, model: str, forecast_start: datetime) -> str:
    timestamp = forecast_start.strftime("%Y%m%dT%H%M%SZ")
    return f"{target}-{model}-{timestamp}"


def none_if_nan(value: object) -> float | None:
    if pd.isna(value):
        return None
    return float(value)


def create_xgboost_config(target: str, *, tuned: bool):
    from openstef_beam.evaluation.metric_providers import ObservedProbabilityProvider, R2Provider, RCRPSProvider
    from openstef_core.mixins.param_ranges import FloatRange, IntRange
    from openstef_core.types import LeadTime, Q
    from openstef_models.models.forecasting.xgboost_forecaster import XGBoostHyperParams
    from openstef_models.presets import ForecastingWorkflowConfig

    if tuned:
        hyperparams = XGBoostHyperParams(
            learning_rate=FloatRange(0.03, 0.3, log=True, tune=True),
            n_estimators=IntRange(50, 300, tune=True),
            max_depth=IntRange(1, 8, tune=True),
            subsample=FloatRange(0.6, 1.0, tune=True),
        )
    else:
        hyperparams = XGBoostHyperParams()

    return ForecastingWorkflowConfig(
        model_id=f"{target}_openstef_xgboost",
        model="xgboost",
        horizons=[LeadTime.from_string(HORIZON)],
        quantiles=[Q(0.5), Q(0.1), Q(0.9)],
        target_column=target,
        temperature_column="temperature_2m",
        relative_humidity_column="relative_humidity_2m",
        wind_speed_column="wind_speed_10m",
        radiation_column="shortwave_radiation",
        pressure_column="surface_pressure",
        xgboost_hyperparams=hyperparams,
        evaluation_metrics=[R2Provider(), ObservedProbabilityProvider(), RCRPSProvider()],
        mlflow_storage=None,
        verbosity=0,
    )


def fit_default(train_dataset):
    from openstef_models.presets import create_forecasting_workflow

    config = create_xgboost_config(train_dataset.data.attrs["target"], tuned=False)
    workflow = create_forecasting_workflow(config)
    workflow.fit(train_dataset)
    return workflow, config, None


def fit_tuned(train_dataset, *, n_trials: int, show_progress_bar: bool):
    import optuna
    from openstef_models.integrations.optuna import HyperparameterTuner
    from openstef_models.presets import create_forecasting_workflow

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    config = create_xgboost_config(train_dataset.data.attrs["target"], tuned=True)
    tuner = HyperparameterTuner(
        config=config,
        train_dataset=train_dataset,
        create_workflow=create_forecasting_workflow,
        target_quantile="global",
        metric_name="rCRPS",
        direction="minimize",
        n_trials=n_trials,
        seed=42,
    )
    result = tuner.fit_with_tuning(show_progress_bar=show_progress_bar)
    return result.workflow, result.best_config, result.study


def api_payload(
    *,
    run_id_value: str,
    model: str,
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
        "runId": run_id_value,
        "model": model,
        "target": target,
        "modelFamily": "openstef-xgboost",
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
        "metrics": [
            {"name": name, "value": float(value)}
            for name, value in metrics.items()
            if isinstance(value, int | float) and pd.notna(value)
        ],
    }


def forecast_payload(
    *,
    workflow,
    model: str,
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
    payload = api_payload(
        run_id_value=run_id(target, model, forecast_start),
        model=model,
        target=target,
        generated_at=generated_at,
        train_start=train_start,
        train_end=train_end,
        forecast_start=forecast_start,
        forecast_end=forecast_end,
        comparison=comparison,
        metrics=metrics,
    )
    return payload, metrics


def write_run_files(output_dir: Path, payloads: list[dict[str, Any]], metadata: dict[str, Any]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    for payload in payloads:
        (output_dir / f"{payload['runId']}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    plot_path = write_comparison_plot(output_dir, payloads, metadata)
    metadata["comparisonPlot"] = plot_path.name

    metadata_path = output_dir / "openstef-xgboost-tuning-metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    report_path = output_dir / "openstef-xgboost-tuning-report.md"
    report_path.write_text(markdown_report(payloads, metadata), encoding="utf-8")
    return report_path


def write_comparison_plot(output_dir: Path, payloads: list[dict[str, Any]], metadata: dict[str, Any]) -> Path:
    from plotly import graph_objects as go

    plot_path = output_dir / "openstef-xgboost-forecast-comparison.html"
    target_label = str(metadata["target"]).capitalize()

    fig = go.Figure()
    if payloads:
        actual_points = payloads[0]["points"]
        actual_values = [point.get("actualKwh") for point in actual_points]
        if any(value is not None for value in actual_values):
            fig.add_trace(
                go.Scatter(
                    x=[point["timestamp"] for point in actual_points],
                    y=actual_values,
                    mode="lines",
                    name=f"Actual {target_label}",
                    line={"color": "#111827", "width": 2},
                )
            )

    for payload in payloads:
        fig.add_trace(
            go.Scatter(
                x=[point["timestamp"] for point in payload["points"]],
                y=[point.get("forecastKwh") for point in payload["points"]],
                mode="lines",
                name=payload["model"],
            )
        )

    fig.update_layout(
        title=f"OpenSTEF {target_label} XGBoost Forecast vs Actual",
        xaxis_title="Time (UTC)",
        yaxis_title=f"{target_label} energy (kWh per 15-minute interval)",
        hovermode="x unified",
        template="plotly_white",
        height=540,
    )
    fig.write_html(plot_path, include_plotlyjs=True)
    return plot_path


def markdown_report(payloads: list[dict[str, Any]], metadata: dict[str, Any]) -> str:
    lines = [
        "# OpenSTEF XGBoost Tuning Report",
        "",
        f"- Target: `{metadata['target']}`",
        f"- Training window: `{metadata['trainStart']}` to `{metadata['trainEnd']}`",
        f"- Forecast window: `{metadata['forecastStart']}` to `{metadata['forecastEnd']}`",
        f"- Horizon: `{HORIZON}`",
        f"- Optuna trials: `{metadata['nTrials']}`",
        f"- Weather rows aligned: `{metadata['weatherAlignment'].get('alignedWeatherIntervalCount')}`",
        f"- Weather rows missing: `{metadata['weatherAlignment'].get('missingWeatherIntervalCount')}`",
        "",
        "## Metrics",
        "",
        "| Model | Aligned intervals | MAE kWh | RMSE kWh | Bias kWh | Total error kWh | MAPE % | sMAPE % |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for payload in payloads:
        metrics = {item["name"]: item["value"] for item in payload["metrics"]}
        lines.append(
            "| "
            + " | ".join(
                [
                    payload["model"],
                    str(int(metrics.get("aligned_intervals", 0))),
                    format_metric(metrics.get("mae_kwh")),
                    format_metric(metrics.get("rmse_kwh")),
                    format_metric(metrics.get("bias_kwh")),
                    format_metric(metrics.get("total_energy_error_kwh")),
                    format_metric(metrics.get("mape_percent")),
                    format_metric(metrics.get("smape_percent")),
                ]
            )
            + " |"
        )

    tuning = metadata.get("tuning", {})
    if tuning:
        lines.extend([
            "",
            "## Tuning",
            "",
            f"- Best validation rCRPS: `{format_metric(tuning.get('bestValue'))}`",
        ])
        lines.extend(f"- Best parameter `{name}`: `{value}`" for name, value in tuning.get("bestParams", {}).items())

    lines.extend(["", "## Run Files", ""])
    lines.extend(f"- `{payload['runId']}.json`" for payload in payloads)
    lines.extend([
        "- `openstef-xgboost-tuning-metadata.json`",
        f"- `{metadata['comparisonPlot']}`",
        "",
    ])
    return "\n".join(lines)


def format_metric(value: object) -> str:
    if value is None:
        return ""
    return f"{float(value):.4f}"


def save_payloads(payloads: list[dict[str, Any]], *, base_url: str) -> None:
    for payload in payloads:
        response = save_forecast_run(payload, base_url=base_url)
        point_count = response.get("forecastPoints", response.get("pointCount", len(payload["points"])))
        metric_count = response.get("metrics", response.get("metricCount", len(payload["metrics"])))
        print(f"Saved {response['runId']} to backend ({point_count} points, {metric_count} metrics)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an OpenSTEF XGBoost baseline and Optuna-tuned forecast.")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--target", default=DEFAULT_TARGET, choices=("generation", "consumption"))
    parser.add_argument("--train-start", default=DEFAULT_TRAIN_START)
    parser.add_argument("--train-days", type=int, default=DEFAULT_TRAIN_DAYS)
    parser.add_argument("--forecast-days", type=int, default=DEFAULT_FORECAST_DAYS)
    parser.add_argument("--n-trials", type=int, default=DEFAULT_N_TRIALS)
    parser.add_argument("--weather-path", default=str(DEFAULT_WEATHER_PATH))
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--no-progress", action="store_true", help="Hide the Optuna progress bar.")
    parser.add_argument("--no-save", action="store_true", help="Write reports without posting forecast runs to the backend.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
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
    predict_dataset = dataset.filter_by_range(start=train_end - timedelta(days=14), end=forecast_end)
    train_dataset.data.attrs["target"] = args.target

    generated_at = datetime.now(timezone.utc)
    print(f"Training rows: {len(train_dataset.data):,}")
    print(f"Prediction rows: {len(predict_dataset.data):,}")

    default_workflow, default_config, _ = fit_default(train_dataset)
    default_payload, default_metrics = forecast_payload(
        workflow=default_workflow,
        model="openstef-xgboost-default",
        target=args.target,
        predict_dataset=predict_dataset,
        generated_at=generated_at,
        train_start=train_start,
        train_end=train_end,
        forecast_start=forecast_start,
        forecast_end=forecast_end,
    )

    tuned_workflow, tuned_config, study = fit_tuned(
        train_dataset,
        n_trials=args.n_trials,
        show_progress_bar=not args.no_progress,
    )
    tuned_payload, tuned_metrics = forecast_payload(
        workflow=tuned_workflow,
        model="openstef-xgboost-tuned",
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
        "trainStart": format_utc(train_start),
        "trainEnd": format_utc(train_end),
        "forecastStart": format_utc(forecast_start),
        "forecastEnd": format_utc(forecast_end),
        "sampleInterval": SAMPLE_INTERVAL,
        "horizon": HORIZON,
        "nTrials": args.n_trials,
        "weatherPath": str(args.weather_path),
        "weatherAlignment": weather_diagnostics.get("alignment", {}),
        "defaultHyperparameters": default_config.xgboost_hyperparams.model_dump(mode="json"),
        "tunedHyperparameters": tuned_config.xgboost_hyperparams.model_dump(mode="json"),
        "tuning": {
            "bestValue": study.best_value,
            "bestParams": study.best_params,
            "trialCount": len(study.trials),
        },
    }

    payloads = [default_payload, tuned_payload]
    report_path = write_run_files(Path(args.output_dir), payloads, metadata)
    for payload in payloads:
        payload["reportPath"] = str(report_path)
    if args.no_save:
        print("Skipped backend save (--no-save)")
    else:
        save_payloads(payloads, base_url=args.base_url)

    print(f"Wrote tuning report to {report_path}")
    print(f"Default MAE: {default_metrics['mae_kwh']:.4f} kWh")
    print(f"Tuned MAE:   {tuned_metrics['mae_kwh']:.4f} kWh")
    print(f"Best rCRPS:  {study.best_value:.4f}")


if __name__ == "__main__":
    main()
