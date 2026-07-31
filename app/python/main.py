import argparse
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from forecast_dataset_api import fetch_forecast_dataframe, save_forecast_run

SAMPLE_INTERVAL = "PT15M"
SAMPLE_FREQUENCY = "15min"
WEATHER_COLUMN_MAP = {
    "all_sky_global_horizontal_irradiance": "shortwave_radiation",
    "2m_temperature": "temperature_2m",
    "2m_relative_humidity": "relative_humidity_2m",
    "10m_wind_speed": "wind_speed_10m",
    "surface_pressure": "surface_pressure",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run reproducible day-ahead forecast backtests.")
    parser.add_argument("--base-url", default="http://localhost:8080", help="Quarkus backend URL.")
    parser.add_argument("--target", choices=["consumption", "generation"], default="consumption")
    parser.add_argument("--train-start", default="2025-06-01T00:00:00Z", help="Training start timestamp in UTC.")
    parser.add_argument("--train-days", type=int, default=200)
    parser.add_argument("--forecast-days", type=int, default=7)
    parser.add_argument("--models", default="historical-average,weekly-persistence", help="Comma-separated models: historical-average, weekly-persistence, openstef-xgboost.")
    parser.add_argument("--weather-file", help="Optional historical weather XLSX file to align with the energy dataset.")
    parser.add_argument("--weather-timezone", default="Europe/Vienna", help="Timezone for naive weather timestamps.")
    parser.add_argument("--output-dir", default="../reports/forecast-runs")
    parser.add_argument("--persist", action="store_true", help="Persist forecast points and metrics through the Quarkus API.")
    parser.add_argument("--run-id-prefix", help="Optional stable prefix for persisted/report run IDs.")
    parser.add_argument("--show-plot", action="store_true", help="Open a Plotly forecast-vs-actual chart.")
    return parser.parse_args()


def parse_utc(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError(f"Timestamp must include a timezone: {value}")
    return parsed.astimezone(timezone.utc)


def format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def model_names(value: str) -> list[str]:
    names = [name.strip() for name in value.split(",") if name.strip()]
    allowed = {"historical-average", "weekly-persistence", "openstef-xgboost"}
    unknown = sorted(set(names) - allowed)
    if unknown:
        raise ValueError(f"Unknown model(s): {', '.join(unknown)}")
    if not names:
        raise ValueError("At least one model must be selected")
    return names


def load_weather(path: Path, timezone_name: str) -> tuple[pd.DataFrame, dict]:
    raw = pd.read_excel(path)
    if "timestamp" not in raw.columns:
        raise ValueError("Weather workbook must contain a timestamp column")

    timestamps = pd.to_datetime(raw["timestamp"])
    ambiguous_count = 0
    if timestamps.dt.tz is None:
        timestamps = timestamps.dt.tz_localize(timezone_name, ambiguous="NaT", nonexistent="shift_forward")
        ambiguous_count = int(timestamps.isna().sum())
        raw = raw.loc[~timestamps.isna()].copy()
        timestamps = timestamps.dropna()
    timestamps = timestamps.dt.tz_convert("UTC")

    weather = raw.rename(columns=WEATHER_COLUMN_MAP).copy()
    weather.index = timestamps
    weather.index.name = "timestamp"
    selected_columns = [column for column in WEATHER_COLUMN_MAP.values() if column in weather.columns]
    weather = weather[selected_columns].apply(pd.to_numeric, errors="coerce").sort_index()

    duplicate_count = int(weather.index.duplicated().sum())
    if duplicate_count:
        weather = weather[~weather.index.duplicated(keep="first")]

    expected = pd.date_range(weather.index.min(), weather.index.max(), freq=SAMPLE_FREQUENCY, tz="UTC") if not weather.empty else pd.DatetimeIndex([], tz="UTC")
    missing_count = int(len(expected.difference(weather.index)))
    diagnostics = {
        "path": str(path),
        "rows": int(len(weather)),
        "columns": selected_columns,
        "firstTimestamp": format_utc(weather.index.min().to_pydatetime()) if not weather.empty else None,
        "lastTimestamp": format_utc(weather.index.max().to_pydatetime()) if not weather.empty else None,
        "duplicateTimestamps": duplicate_count,
        "missingQuarterHours": missing_count,
        "ambiguousLocalTimestampsDropped": ambiguous_count,
        "unmappedColumns": [column for column in raw.columns if column not in WEATHER_COLUMN_MAP and column != "timestamp"],
    }
    return weather, diagnostics


def historical_average_forecast(train: pd.Series, forecast_index: pd.DatetimeIndex) -> pd.Series:
    train_frame = train.to_frame("actual")
    train_frame["weekday"] = train_frame.index.weekday
    train_frame["time"] = train_frame.index.strftime("%H:%M")
    by_weekday_time = train_frame.groupby(["weekday", "time"])["actual"].mean()
    by_time = train_frame.groupby("time")["actual"].mean()
    fallback = float(train.mean())

    values = []
    for timestamp in forecast_index:
        key = (timestamp.weekday(), timestamp.strftime("%H:%M"))
        if key in by_weekday_time.index:
            values.append(float(by_weekday_time.loc[key]))
        elif timestamp.strftime("%H:%M") in by_time.index:
            values.append(float(by_time.loc[timestamp.strftime("%H:%M")]))
        else:
            values.append(fallback)
    return pd.Series(values, index=forecast_index, name="forecast_kwh")


def weekly_persistence_forecast(history: pd.Series, forecast_index: pd.DatetimeIndex) -> pd.Series:
    fallback = historical_average_forecast(history.loc[history.index < forecast_index.min()], forecast_index)
    values = []
    for timestamp in forecast_index:
        source = timestamp - timedelta(days=7)
        if source in history.index and pd.notna(history.loc[source]):
            values.append(float(history.loc[source]))
        else:
            values.append(float(fallback.loc[timestamp]))
    return pd.Series(values, index=forecast_index, name="forecast_kwh")


def openstef_forecast(data: pd.DataFrame, target: str, forecast_start: datetime, forecast_end: datetime) -> pd.Series:
    required = {"temperature_2m", "relative_humidity_2m", "wind_speed_10m", "shortwave_radiation", "surface_pressure"}
    missing = sorted(required - set(data.columns))
    if missing:
        raise ValueError(f"openstef-xgboost requires weather columns: {', '.join(missing)}")

    from openstef_core.datasets import TimeSeriesDataset
    from openstef_core.types import LeadTime, Q
    from openstef_models.presets import ForecastingWorkflowConfig, create_forecasting_workflow

    dataset = TimeSeriesDataset(data=data, sample_interval=timedelta(minutes=15), check_frequency=False)
    train_dataset = dataset.filter_by_range(start=data.index.min().to_pydatetime(), end=forecast_start)
    predict_dataset = dataset.filter_by_range(start=forecast_start - timedelta(days=14), end=forecast_end)
    config = ForecastingWorkflowConfig(
        model_id=f"{target}_xgboost",
        quantiles=[Q(0.5)],
        model="xgboost",
        horizons=[LeadTime.from_string("PT36H")],
        target_column=target,
        temperature_column="temperature_2m",
        relative_humidity_column="relative_humidity_2m",
        wind_speed_column="wind_speed_10m",
        radiation_column="shortwave_radiation",
        pressure_column="surface_pressure",
        verbosity=0,
        mlflow_storage=None,
        sample_interval=timedelta(minutes=15),
    )
    workflow = create_forecasting_workflow(config)
    workflow.fit(train_dataset)
    forecast = workflow.predict(predict_dataset, forecast_start=forecast_start)
    forecast_series = forecast.median_series.loc[forecast_start:forecast_end]
    forecast_series = forecast_series[forecast_series.index < forecast_end]
    forecast_series.name = "forecast_kwh"
    return forecast_series


def compute_metrics(forecast: pd.Series, actual: pd.Series) -> tuple[dict, pd.DataFrame]:
    comparison = pd.DataFrame({"forecast_kwh": forecast, "actual_kwh": actual.reindex(forecast.index)})
    comparison["error_kwh"] = comparison["forecast_kwh"] - comparison["actual_kwh"]
    aligned = comparison.dropna(subset=["forecast_kwh", "actual_kwh"])
    if aligned.empty:
        raise ValueError("No aligned forecast/actual intervals are available for evaluation")

    error = aligned["error_kwh"]
    actual_abs = aligned["actual_kwh"].abs()
    percentage_base = actual_abs > 1e-9
    smape_denominator = (aligned["forecast_kwh"].abs() + actual_abs) / 2
    smape_base = smape_denominator > 1e-9
    daily_error = aligned.resample("1D").sum(numeric_only=True)
    daily_energy_error = daily_error["forecast_kwh"] - daily_error["actual_kwh"]

    metrics = {
        "forecast_intervals": int(len(comparison)),
        "aligned_intervals": int(len(aligned)),
        "missing_actual_intervals": int(comparison["actual_kwh"].isna().sum()),
        "mae_kwh": float(error.abs().mean()),
        "rmse_kwh": float(math.sqrt((error ** 2).mean())),
        "bias_kwh": float(error.mean()),
        "total_forecast_kwh": float(aligned["forecast_kwh"].sum()),
        "total_actual_kwh": float(aligned["actual_kwh"].sum()),
        "total_energy_error_kwh": float(error.sum()),
        "mean_abs_daily_energy_error_kwh": float(daily_energy_error.abs().mean()),
    }
    if percentage_base.any():
        metrics["mape_percent"] = float((error[percentage_base].abs() / actual_abs[percentage_base]).mean() * 100)
    if smape_base.any():
        metrics["smape_percent"] = float((error[smape_base].abs() / smape_denominator[smape_base]).mean() * 100)
    return metrics, comparison


def report_payload(
    run_id: str,
    model: str,
    target: str,
    generated_at: datetime,
    train_start: datetime,
    forecast_start: datetime,
    forecast_end: datetime,
    metrics: dict,
    comparison: pd.DataFrame,
    weather_diagnostics: dict | None,
) -> dict:
    return {
        "runId": run_id,
        "model": model,
        "target": target,
        "generatedAt": format_utc(generated_at),
        "trainStart": format_utc(train_start),
        "forecastStart": format_utc(forecast_start),
        "forecastEnd": format_utc(forecast_end),
        "sampleInterval": SAMPLE_INTERVAL,
        "metrics": metrics,
        "weather": weather_diagnostics,
        "points": [
            {
                "timestamp": format_utc(index.to_pydatetime()),
                "forecastKwh": none_if_nan(row.forecast_kwh),
                "actualKwh": none_if_nan(row.actual_kwh),
                "errorKwh": none_if_nan(row.error_kwh),
            }
            for index, row in comparison.iterrows()
        ],
    }


def persistence_payload(payload: dict) -> dict:
    return {
        "runId": payload["runId"],
        "model": payload["model"],
        "target": payload["target"],
        "generatedAt": payload["generatedAt"],
        "forecastStart": payload["forecastStart"],
        "forecastEnd": payload["forecastEnd"],
        "sampleInterval": payload["sampleInterval"],
        "points": [
            {
                "timestamp": point["timestamp"],
                "forecastKwh": point["forecastKwh"],
                "actualKwh": point["actualKwh"],
            }
            for point in payload["points"]
            if point["forecastKwh"] is not None
        ],
        "metrics": [
            {"name": name, "value": value}
            for name, value in payload["metrics"].items()
            if isinstance(value, (int, float)) and math.isfinite(float(value))
        ],
    }


def write_reports(output_dir: Path, payloads: list[dict]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for payload in payloads:
        json_path = output_dir / f"{payload['runId']}.json"
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    markdown_path = output_dir / "forecast-backtest-report.md"
    markdown_path.write_text(markdown_report(payloads), encoding="utf-8")


def markdown_report(payloads: list[dict]) -> str:
    lines = ["# Forecast Backtest Report", ""]
    if not payloads:
        return "# Forecast Backtest Report\n\nNo forecast runs were produced.\n"

    first = payloads[0]
    lines.extend([
        f"- Target: `{first['target']}`",
        f"- Forecast window: `{first['forecastStart']}` to `{first['forecastEnd']}`",
        f"- Sample interval: `{first['sampleInterval']}`",
        "",
        "## Metrics",
        "",
        "| Model | Aligned intervals | MAE kWh | RMSE kWh | Bias kWh | Total error kWh | MAPE % | sMAPE % |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for payload in payloads:
        metrics = payload["metrics"]
        lines.append(
            "| "
            + " | ".join([
                payload["model"],
                str(metrics.get("aligned_intervals", "")),
                format_metric(metrics.get("mae_kwh")),
                format_metric(metrics.get("rmse_kwh")),
                format_metric(metrics.get("bias_kwh")),
                format_metric(metrics.get("total_energy_error_kwh")),
                format_metric(metrics.get("mape_percent")),
                format_metric(metrics.get("smape_percent")),
            ])
            + " |"
        )

    weather = first.get("weather")
    if weather:
        lines.extend([
            "",
            "## Weather Alignment",
            "",
            f"- File: `{weather['path']}`",
            f"- Rows: `{weather['rows']}`",
            f"- Columns: `{', '.join(weather['columns'])}`",
            f"- Range: `{weather['firstTimestamp']}` to `{weather['lastTimestamp']}`",
            f"- Duplicate timestamps: `{weather['duplicateTimestamps']}`",
            f"- Missing quarter-hour timestamps: `{weather['missingQuarterHours']}`",
            f"- Ambiguous local timestamps dropped: `{weather['ambiguousLocalTimestampsDropped']}`",
        ])

    lines.extend(["", "## Run Files", ""])
    for payload in payloads:
        lines.append(f"- `{payload['runId']}.json`")
    lines.append("")
    return "\n".join(lines)


def format_metric(value: object) -> str:
    if value is None:
        return ""
    return f"{float(value):.4f}"


def none_if_nan(value: object) -> float | None:
    if pd.isna(value):
        return None
    return float(value)


def build_run_id(prefix: str | None, target: str, model: str, forecast_start: datetime) -> str:
    base = prefix or f"{target}-{model}-{format_utc(forecast_start)}"
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", base).strip("-")


def resolve_output_dir(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return Path(__file__).resolve().parent / path


def plot_payloads(payloads: list[dict]) -> None:
    import plotly.graph_objects as go

    fig = go.Figure()
    for payload in payloads:
        frame = pd.DataFrame(payload["points"])
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        if "Actual" not in [trace.name for trace in fig.data]:
            fig.add_trace(go.Scatter(x=frame["timestamp"], y=frame["actualKwh"], name="Actual", mode="lines"))
        fig.add_trace(go.Scatter(x=frame["timestamp"], y=frame["forecastKwh"], name=payload["model"], mode="lines"))
    fig.update_layout(title="Forecast vs Actual", xaxis_title="Time", yaxis_title="Energy (kWh)", height=600)
    fig.show()


def main() -> None:
    args = parse_args()
    train_start = parse_utc(args.train_start)
    forecast_start = train_start + timedelta(days=args.train_days)
    forecast_end = forecast_start + timedelta(days=args.forecast_days)
    names = model_names(args.models)

    data = fetch_forecast_dataframe(
        base_url=args.base_url,
        target=args.target,
        start=format_utc(train_start),
        end=format_utc(forecast_end),
    )
    if data.empty:
        raise ValueError("Dataset is empty. Check that InfluxDB contains imported energy data for the selected range.")

    weather_diagnostics = None
    if args.weather_file:
        weather, weather_diagnostics = load_weather(Path(args.weather_file), args.weather_timezone)
        data = data.join(weather, how="left")

    actual = data[args.target].sort_index()
    train = actual[(actual.index >= train_start) & (actual.index < forecast_start)].dropna()
    forecast_index = pd.date_range(forecast_start, forecast_end, freq=SAMPLE_FREQUENCY, tz="UTC", inclusive="left")
    if train.empty:
        raise ValueError("Training dataset is empty for the selected range.")

    generated_at = datetime.now(timezone.utc)
    payloads = []
    for name in names:
        if name == "historical-average":
            forecast = historical_average_forecast(train, forecast_index)
        elif name == "weekly-persistence":
            forecast = weekly_persistence_forecast(actual, forecast_index)
        elif name == "openstef-xgboost":
            forecast = openstef_forecast(data, args.target, forecast_start, forecast_end).reindex(forecast_index)
        else:
            raise AssertionError(f"Unhandled model: {name}")

        metrics, comparison = compute_metrics(forecast, actual)
        run_id = build_run_id(args.run_id_prefix, args.target, name, forecast_start)
        if len(names) > 1 and args.run_id_prefix:
            run_id = build_run_id(f"{args.run_id_prefix}-{name}", args.target, name, forecast_start)
        payload = report_payload(run_id, name, args.target, generated_at, train_start, forecast_start, forecast_end, metrics, comparison, weather_diagnostics)
        payloads.append(payload)

        if args.persist:
            response = save_forecast_run(persistence_payload(payload), base_url=args.base_url)
            print(f"Persisted {response['forecastPoints']} points and {response['metrics']} metrics for {response['runId']}")

    output_dir = resolve_output_dir(args.output_dir)
    write_reports(output_dir, payloads)
    print(f"Wrote forecast reports to {output_dir.resolve()}")
    for payload in payloads:
        metrics = payload["metrics"]
        print(
            f"{payload['model']}: MAE={metrics['mae_kwh']:.4f} kWh, "
            f"RMSE={metrics['rmse_kwh']:.4f} kWh, aligned={metrics['aligned_intervals']}"
        )

    if args.show_plot:
        plot_payloads(payloads)


if __name__ == "__main__":
    main()
