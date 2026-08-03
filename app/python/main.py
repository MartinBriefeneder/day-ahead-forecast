import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from forecast_dataset_api import fetch_forecast_dataframe

BASE_URL = "http://localhost:8080"
TARGET = "consumption"
TRAIN_START = datetime(2025, 6, 1, tzinfo=timezone.utc)
TRAIN_DAYS = 200
FORECAST_DAYS = 7
MODELS = ("historical-average", "weekly-persistence")
OUTPUT_DIR = (Path(__file__).resolve().parent / "../reports/forecast-runs").resolve()

SAMPLE_INTERVAL = "PT15M"
SAMPLE_FREQUENCY = "15min"


def format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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
    generated_at: datetime,
    train_start: datetime,
    forecast_start: datetime,
    forecast_end: datetime,
    metrics: dict,
    comparison: pd.DataFrame,
) -> dict:
    return {
        "runId": run_id,
        "model": model,
        "target": TARGET,
        "generatedAt": format_utc(generated_at),
        "trainStart": format_utc(train_start),
        "forecastStart": format_utc(forecast_start),
        "forecastEnd": format_utc(forecast_end),
        "sampleInterval": SAMPLE_INTERVAL,
        "metrics": metrics,
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


def build_run_id(model: str, forecast_start: datetime) -> str:
    timestamp = forecast_start.strftime("%Y%m%dT%H%M%SZ")
    return f"{TARGET}-{model}-{timestamp}"


def main() -> None:
    forecast_start = TRAIN_START + timedelta(days=TRAIN_DAYS)
    forecast_end = forecast_start + timedelta(days=FORECAST_DAYS)
    data = fetch_forecast_dataframe(
        base_url=BASE_URL,
        target=TARGET,
        start=format_utc(TRAIN_START),
        end=format_utc(forecast_end),
    )
    if data.empty:
        raise ValueError("Dataset is empty. Check that InfluxDB contains imported energy data for the selected range.")

    actual = data[TARGET].sort_index()
    train = actual[(actual.index >= TRAIN_START) & (actual.index < forecast_start)].dropna()
    if train.empty:
        raise ValueError("Training dataset is empty for the selected range.")

    forecast_index = pd.date_range(forecast_start, forecast_end, freq=SAMPLE_FREQUENCY, tz="UTC", inclusive="left")
    generated_at = datetime.now(timezone.utc)
    payloads = []
    for model in MODELS:
        if model == "historical-average":
            forecast = historical_average_forecast(train, forecast_index)
        elif model == "weekly-persistence":
            forecast = weekly_persistence_forecast(actual, forecast_index)
        else:
            raise ValueError(f"Unknown model: {model}")

        metrics, comparison = compute_metrics(forecast, actual)
        payloads.append(
            report_payload(
                build_run_id(model, forecast_start),
                model,
                generated_at,
                TRAIN_START,
                forecast_start,
                forecast_end,
                metrics,
                comparison,
            )
        )

    write_reports(OUTPUT_DIR, payloads)
    print(f"Wrote forecast reports to {OUTPUT_DIR}")
    for payload in payloads:
        metrics = payload["metrics"]
        print(
            f"{payload['model']}: MAE={metrics['mae_kwh']:.4f} kWh, "
            f"RMSE={metrics['rmse_kwh']:.4f} kWh, aligned={metrics['aligned_intervals']}"
        )


if __name__ == "__main__":
    main()
