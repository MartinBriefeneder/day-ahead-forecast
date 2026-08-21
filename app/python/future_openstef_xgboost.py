from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from forecast_dataset_api import fetch_forecast_dataframe, save_forecast_run
from forecast_runner import (
    BASE_URL,
    DEFAULT_CONTEXT_DAYS,
    DEFAULT_FORECAST_DAYS,
    DEFAULT_TARGET,
    DEFAULT_TRAIN_DAYS,
    DEFAULT_TRAIN_START,
    HORIZON,
    OUTPUT_DIR,
    SAMPLE_INTERVAL,
    format_utc,
    metric_items,
    none_if_nan,
    parse_utc,
    prediction_context_start,
    require_positive_int,
    run_id_for_model,
    timestamped_report_path,
)
from weather_features import DEFAULT_GRIDOO_LOCATION_ID, DEFAULT_WEATHER_PATH, add_weather_features, fetch_gridoo_forecast

MODEL_NAME = "openstef-future-xgboost"
MODEL_FAMILY = "openstef-xgboost"
FUTURE_WEATHER_FEATURES = (
    "temperature_2m",
    "wind_speed_10m",
    "shortwave_radiation",
)


def run_id(target: str, forecast_start: datetime) -> str:
    return run_id_for_model(target, MODEL_NAME, forecast_start)


def next_quarter_hour(now: datetime | None = None) -> datetime:
    value = datetime.now(timezone.utc) if now is None else now.astimezone(timezone.utc)
    minute = (value.minute // 15 + 1) * 15
    rounded = value.replace(second=0, microsecond=0)
    if minute == 60:
        return rounded.replace(minute=0) + timedelta(hours=1)
    return rounded.replace(minute=minute)


def create_future_openstef_xgboost_workflow(target: str):
    from openstef_core.types import LeadTime, Q
    from openstef_models.models.forecasting.xgboost_forecaster import XGBoostHyperParams
    from openstef_models.presets import ForecastingWorkflowConfig, create_forecasting_workflow

    config = ForecastingWorkflowConfig(
        model_id=f"{target}_future_openstef_xgboost",
        model="xgboost",
        horizons=[LeadTime.from_string(HORIZON)],
        quantiles=[Q(0.5), Q(0.1), Q(0.9)],
        target_column=target,
        temperature_column="temperature_2m",
        wind_speed_column="wind_speed_10m",
        radiation_column="shortwave_radiation",
        xgboost_hyperparams=XGBoostHyperParams(),
        mlflow_storage=None,
        verbosity=0,
    )
    return create_forecasting_workflow(config), config


def build_training_frame(
    *,
    base_url: str,
    target: str,
    train_start: datetime,
    train_end: datetime,
    weather_path: str | Path,
) -> pd.DataFrame:
    data = fetch_forecast_dataframe(
        base_url=base_url,
        target=target,
        start=format_utc(train_start),
        end=format_utc(train_end),
    )
    if data.empty:
        raise ValueError("Training dataset is empty. Import historical energy data or choose another training window.")
    data, diagnostics = add_weather_features(
        data,
        path=weather_path,
        requested_features=FUTURE_WEATHER_FEATURES,
        require_complete=True,
    )
    data.attrs["weather_diagnostics"] = {"historical": diagnostics}
    data.attrs["target"] = target
    return data


def build_prediction_frame(
    *,
    base_url: str,
    target: str,
    context_start: datetime,
    forecast_start: datetime,
    forecast_end: datetime,
    weather_path: str | Path,
    gridoo_location_id: int,
) -> pd.DataFrame:
    context = fetch_forecast_dataframe(
        base_url=base_url,
        target=target,
        start=format_utc(context_start),
        end=format_utc(forecast_start),
    )
    if not context.empty:
        context, context_diagnostics = add_weather_features(
            context,
            path=weather_path,
            requested_features=FUTURE_WEATHER_FEATURES,
            require_complete=True,
        )
    else:
        context_diagnostics = {"alignment": {"alignedWeatherIntervalCount": 0}}

    forecast_weather = fetch_gridoo_forecast(
        start=forecast_start,
        end=forecast_end,
        location_id=gridoo_location_id,
        requested_features=FUTURE_WEATHER_FEATURES,
    )
    future_weather = complete_future_weather_frame(forecast_weather.data, forecast_start, forecast_end)
    future = future_weather.copy()
    future[target] = pd.NA
    future = future[[target, *FUTURE_WEATHER_FEATURES]]

    prediction = pd.concat([context, future]).sort_index()
    prediction.attrs["target"] = target
    prediction.attrs["weather_diagnostics"] = {
        "historicalContext": context_diagnostics,
        "forecast": forecast_weather.metadata,
    }
    return prediction


def complete_future_weather_frame(data: pd.DataFrame, forecast_start: datetime, forecast_end: datetime) -> pd.DataFrame:
    expected_index = pd.date_range(
        start=pd.Timestamp(forecast_start),
        end=pd.Timestamp(forecast_end),
        freq="15min",
        inclusive="left",
    )
    if data.empty:
        raise ValueError("Gridoo forecast weather response is empty for the requested forecast window.")
    missing = expected_index.difference(data.index)
    if not missing.empty:
        examples = ", ".join(timestamp.isoformat().replace("+00:00", "Z") for timestamp in missing[:5])
        raise ValueError(f"Gridoo forecast weather is missing {len(missing)} interval(s), for example: {examples}")
    return data.reindex(expected_index)[list(FUTURE_WEATHER_FEATURES)]


def time_series_dataset(data: pd.DataFrame):
    from datetime import timedelta

    from openstef_core.datasets import TimeSeriesDataset

    return TimeSeriesDataset(data=data, sample_interval=timedelta(minutes=15), check_frequency=False)


def api_payload(
    *,
    target: str,
    generated_at: datetime,
    train_start: datetime,
    train_end: datetime,
    forecast_start: datetime,
    forecast_end: datetime,
    forecast: pd.Series,
    report_path: str | Path | None = None,
) -> dict[str, Any]:
    forecast = forecast.sort_index()
    forecast = forecast[(forecast.index >= forecast_start) & (forecast.index < forecast_end)]
    if forecast.empty:
        raise ValueError("Forecast output is empty for the requested forecast window.")
    if forecast.isna().any():
        raise ValueError("Forecast output contains missing values and cannot be saved as a future forecast.")
    metrics = {
        "forecast_intervals": int(len(forecast)),
        "total_forecast_kwh": float(forecast.sum()),
    }
    return {
        "runId": run_id(target, forecast_start),
        "model": MODEL_NAME,
        "target": target,
        "modelFamily": MODEL_FAMILY,
        "generatedAt": format_utc(generated_at),
        "trainStart": format_utc(train_start),
        "trainEnd": format_utc(train_end),
        "forecastStart": format_utc(forecast_start),
        "forecastEnd": format_utc(forecast_end),
        "sampleInterval": SAMPLE_INTERVAL,
        "horizon": HORIZON,
        "reportPath": str(report_path) if report_path is not None else None,
        "points": [
            {
                "timestamp": format_utc(index.to_pydatetime()),
                "forecastKwh": none_if_nan(value),
                "actualKwh": None,
            }
            for index, value in forecast.items()
        ],
        "metrics": metric_items(metrics),
    }


def write_forecast_plot(output_dir: Path, payload: dict[str, Any]) -> Path:
    from plotly import graph_objects as go

    output_dir.mkdir(parents=True, exist_ok=True)
    plot_path = timestamped_report_path(
        output_dir,
        f"{payload['target']}-openstef-future-xgboost-forecast",
        generated_at=payload.get("generatedAt"),
    )
    target_label = str(payload["target"]).capitalize()
    points = payload["points"]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=[point["timestamp"] for point in points],
            y=[point.get("forecastKwh") for point in points],
            mode="lines",
            name=MODEL_NAME,
        )
    )
    fig.update_layout(
        title=f"Future OpenSTEF {target_label} Forecast With Gridoo Weather",
        xaxis_title="Time (UTC)",
        yaxis_title=f"{target_label} energy (kWh per 15-minute interval)",
        hovermode="x unified",
        template="plotly_white",
        height=540,
    )
    fig.write_html(plot_path, include_plotlyjs=True)
    return plot_path


def save_payload(payload: dict[str, Any], *, base_url: str) -> None:
    response = save_forecast_run(payload, base_url=base_url)
    point_count = response.get("forecastPoints", response.get("pointCount", len(payload["points"])))
    metric_count = response.get("metrics", response.get("metricCount", len(payload["metrics"])))
    print(f"Saved {response['runId']} to backend ({point_count} points, {metric_count} metrics)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a future OpenSTEF XGBoost forecast with Gridoo forecast weather.")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--target", default=DEFAULT_TARGET, choices=("generation", "consumption"))
    parser.add_argument("--train-start", default=DEFAULT_TRAIN_START)
    parser.add_argument("--train-days", type=int, default=DEFAULT_TRAIN_DAYS)
    parser.add_argument("--forecast-start", help="UTC ISO timestamp. Defaults to the next quarter-hour.")
    parser.add_argument("--forecast-days", type=int, default=DEFAULT_FORECAST_DAYS)
    parser.add_argument("--context-days", type=int, default=DEFAULT_CONTEXT_DAYS)
    parser.add_argument("--weather-path", default=str(DEFAULT_WEATHER_PATH))
    parser.add_argument("--gridoo-location-id", type=int, default=DEFAULT_GRIDOO_LOCATION_ID)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--no-save", action="store_true", help="Write the local plot but do not save to the backend.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    require_positive_int("train-days", args.train_days)
    require_positive_int("forecast-days", args.forecast_days)
    require_positive_int("context-days", args.context_days)

    train_start = parse_utc(args.train_start)
    train_end = train_start + timedelta(days=args.train_days)
    forecast_start = parse_utc(args.forecast_start) if args.forecast_start else next_quarter_hour()
    forecast_end = forecast_start + timedelta(days=args.forecast_days)
    if train_end > forecast_start:
        raise ValueError("Training window must end before or at forecast-start for a true future forecast.")

    training_frame = build_training_frame(
        base_url=args.base_url,
        target=args.target,
        train_start=train_start,
        train_end=train_end,
        weather_path=args.weather_path,
    )
    prediction_frame = build_prediction_frame(
        base_url=args.base_url,
        target=args.target,
        context_start=prediction_context_start(forecast_start, args.context_days),
        forecast_start=forecast_start,
        forecast_end=forecast_end,
        weather_path=args.weather_path,
        gridoo_location_id=args.gridoo_location_id,
    )

    print(f"Training rows: {len(training_frame):,}")
    print(f"Prediction rows: {len(prediction_frame):,}")
    print(f"Forecast weather rows: {len(prediction_frame[prediction_frame.index >= forecast_start]):,}")

    workflow, _ = create_future_openstef_xgboost_workflow(args.target)
    workflow.fit(time_series_dataset(training_frame))
    forecast = workflow.predict(time_series_dataset(prediction_frame), forecast_start=forecast_start)

    generated_at = datetime.now(timezone.utc)
    payload = api_payload(
        target=args.target,
        generated_at=generated_at,
        train_start=train_start,
        train_end=train_end,
        forecast_start=forecast_start,
        forecast_end=forecast_end,
        forecast=forecast.median_series.rename("forecast_kwh"),
    )
    plot_path = write_forecast_plot(Path(args.output_dir), payload)
    payload["reportPath"] = str(plot_path)

    if not args.no_save:
        save_payload(payload, base_url=args.base_url)

    print(f"Wrote future forecast plot to {plot_path}")
    print(f"{MODEL_NAME}: {len(payload['points'])} intervals, total={dict((item['name'], item['value']) for item in payload['metrics'])['total_forecast_kwh']:.4f} kWh")


if __name__ == "__main__":
    main()
