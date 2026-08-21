import argparse
import math
from datetime import datetime, timedelta, timezone

import pandas as pd

from forecast_dataset_api import fetch_forecast_dataframe, save_forecast_run

BASE_URL = "http://localhost:8080"
TARGET = "consumption"
TRAIN_START = datetime(2025, 6, 1, tzinfo=timezone.utc)
TRAIN_DAYS = 90
DEFAULT_FORECAST_WEEKS = 1
MAX_FORECAST_WEEKS = 4
MAX_FORECAST_DAYS = MAX_FORECAST_WEEKS * 7
MODELS = ("weekly-persistence",)
MODEL_FAMILY = "simple-benchmark"

SAMPLE_INTERVAL = timedelta(minutes=15)


def format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def format_iso8601_duration(value: timedelta) -> str:
    seconds = int(value.total_seconds())
    if seconds % 60 != 0:
        raise ValueError("Sample interval must use whole minutes")
    return f"PT{seconds // 60}M"


def format_iso8601_days(value: timedelta) -> str:
    days = value.days
    if value != timedelta(days=days):
        raise ValueError("Horizon must use whole days")
    return f"P{days}D"


def parse_utc_argument(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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


def resolve_windows(args: argparse.Namespace) -> tuple[datetime, datetime, datetime, timedelta]:
    if args.train_days <= 0:
        raise ValueError("train-days must be positive")
    if args.forecast_days is not None and args.forecast_weeks is not None:
        raise ValueError("Use forecast-days or forecast-weeks, not both")
    if args.forecast_days is not None and (args.forecast_days <= 0 or args.forecast_days > MAX_FORECAST_DAYS):
        raise ValueError(f"forecast-days must be between 1 and {MAX_FORECAST_DAYS}")
    forecast_weeks = args.forecast_weeks if args.forecast_weeks is not None else DEFAULT_FORECAST_WEEKS
    if args.forecast_days is None and (forecast_weeks <= 0 or forecast_weeks > MAX_FORECAST_WEEKS):
        raise ValueError(f"forecast-weeks must be between 1 and {MAX_FORECAST_WEEKS}")

    horizon = timedelta(days=args.forecast_days) if args.forecast_days is not None else timedelta(weeks=forecast_weeks)
    if args.forecast_start:
        forecast_start = parse_utc_argument(args.forecast_start)
        if args.train_start:
            train_start = parse_utc_argument(args.train_start)
        elif forecast_start >= datetime.now(timezone.utc):
            train_start = TRAIN_START
        else:
            train_start = forecast_start - timedelta(days=args.train_days)
    else:
        train_start = parse_utc_argument(args.train_start) if args.train_start else TRAIN_START
        forecast_start = train_start + timedelta(days=args.train_days)

    return train_start, forecast_start, forecast_start + horizon, horizon


def resolve_data_query_end(
    train_start: datetime,
    forecast_start: datetime,
    forecast_end: datetime,
    train_days: int,
    now: datetime | None = None,
) -> datetime:
    reference = datetime.now(timezone.utc) if now is None else now.astimezone(timezone.utc)
    if forecast_start >= reference:
        return min(train_start + timedelta(days=train_days), forecast_start)
    return forecast_end


def compute_metrics(forecast: pd.Series, actual: pd.Series) -> tuple[dict, pd.DataFrame]:
    comparison = pd.DataFrame({"forecast_kwh": forecast, "actual_kwh": actual.reindex(forecast.index)})
    comparison["error_kwh"] = comparison["forecast_kwh"] - comparison["actual_kwh"]
    aligned = comparison.dropna(subset=["forecast_kwh", "actual_kwh"])

    metrics = {
        "forecast_intervals": int(len(comparison)),
        "aligned_intervals": int(len(aligned)),
        "missing_actual_intervals": int(comparison["actual_kwh"].isna().sum()),
        "total_forecast_kwh": float(comparison["forecast_kwh"].sum()),
    }
    if aligned.empty:
        return metrics, comparison

    error = aligned["error_kwh"]
    actual_abs = aligned["actual_kwh"].abs()
    percentage_base = actual_abs > 1e-9
    smape_denominator = (aligned["forecast_kwh"].abs() + actual_abs) / 2
    smape_base = smape_denominator > 1e-9
    daily_error = aligned.resample("1D").sum(numeric_only=True)
    daily_energy_error = daily_error["forecast_kwh"] - daily_error["actual_kwh"]

    metrics.update({
        "mae_kwh": float(error.abs().mean()),
        "rmse_kwh": float(math.sqrt((error ** 2).mean())),
        "bias_kwh": float(error.mean()),
        "total_actual_kwh": float(aligned["actual_kwh"].sum()),
        "total_energy_error_kwh": float(error.sum()),
        "mean_abs_daily_energy_error_kwh": float(daily_energy_error.abs().mean()),
    })
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
    train_end: datetime,
    forecast_start: datetime,
    forecast_end: datetime,
    horizon: timedelta,
    metrics: dict,
    comparison: pd.DataFrame,
) -> dict:
    return {
        "runId": run_id,
        "model": model,
        "target": target,
        "modelFamily": MODEL_FAMILY,
        "generatedAt": format_utc(generated_at),
        "trainStart": format_utc(train_start),
        "trainEnd": format_utc(train_end),
        "forecastStart": format_utc(forecast_start),
        "forecastEnd": format_utc(forecast_end),
        "sampleInterval": format_iso8601_duration(SAMPLE_INTERVAL),
        "horizon": format_iso8601_days(horizon),
        "reportPath": None,
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


def backend_payload(payload: dict) -> dict:
    return {
        **payload,
        "metrics": metric_items(payload["metrics"]),
    }


def none_if_nan(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def metric_items(metrics: dict) -> list[dict[str, float]]:
    items = []
    for name, value in metrics.items():
        try:
            numeric_value = none_if_nan(value)
        except (TypeError, ValueError):
            continue
        if numeric_value is not None:
            items.append({"name": name, "value": numeric_value})
    return items


def build_run_id(target: str, model: str, forecast_start: datetime) -> str:
    timestamp = forecast_start.strftime("%Y%m%dT%H%M%SZ")
    return f"{target}-{model}-{timestamp}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run simple benchmark energy forecasts.")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--target", choices=("consumption", "generation"), default=TARGET)
    parser.add_argument("--train-start", help="UTC ISO-8601 timestamp. Defaults to forecast-start minus train-days when forecast-start is set.")
    parser.add_argument("--train-days", type=int, default=TRAIN_DAYS)
    parser.add_argument("--forecast-start", help="UTC ISO-8601 timestamp. Defaults to train-start plus train-days.")
    parser.add_argument("--forecast-days", type=int, help="Forecast horizon in whole days. Use this for shared batch windows.")
    parser.add_argument("--forecast-weeks", type=int, help="Forecast horizon in whole weeks. Defaults to 1 when forecast-days is not set.")
    parser.add_argument("--save", action="store_true", help="Persist the forecast run to the backend for later comparison.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    train_start, forecast_start, forecast_end, horizon = resolve_windows(args)
    data_query_end = resolve_data_query_end(train_start, forecast_start, forecast_end, args.train_days)
    data = fetch_forecast_dataframe(
        base_url=args.base_url,
        target=args.target,
        start=format_utc(train_start),
        end=format_utc(data_query_end),
    )
    if data.empty:
        raise ValueError("Dataset is empty. Check that InfluxDB contains imported energy data for the selected range.")

    actual = data[args.target].sort_index()
    train = actual[(actual.index >= train_start) & (actual.index < forecast_start)].dropna()
    if train.empty:
        raise ValueError("Training dataset is empty for the selected range.")

    forecast_index = pd.date_range(forecast_start, forecast_end, freq=SAMPLE_INTERVAL, tz="UTC", inclusive="left")
    generated_at = datetime.now(timezone.utc)
    payloads = []
    for model in MODELS:
        if model == "weekly-persistence":
            forecast = weekly_persistence_forecast(actual, forecast_index)
        else:
            raise ValueError(f"Unknown model: {model}")

        metrics, comparison = compute_metrics(forecast, actual)
        payloads.append(
            report_payload(
                build_run_id(args.target, model, forecast_start),
                model,
                args.target,
                generated_at,
                train_start,
                forecast_start,
                forecast_start,
                forecast_end,
                horizon,
                metrics,
                comparison,
            )
        )

    for payload in payloads:
        if args.save:
            response = save_forecast_run(backend_payload(payload), base_url=args.base_url)
            point_count = response.get("forecastPoints", response.get("pointCount", len(payload["points"])))
            metric_count = response.get("metrics", response.get("metricCount", len(payload["metrics"])))
            print(f"Saved {response['runId']} to backend ({point_count} points, {metric_count} metrics)")
        metrics = payload["metrics"]
        if metrics.get("aligned_intervals", 0):
            print(
                f"{payload['model']}: MAE={metrics['mae_kwh']:.4f} kWh, "
                f"RMSE={metrics['rmse_kwh']:.4f} kWh, aligned={metrics['aligned_intervals']}"
            )
        else:
            print(
                f"{payload['model']}: total forecast={metrics['total_forecast_kwh']:.4f} kWh, "
                f"aligned=0, missing actual={metrics['missing_actual_intervals']}"
            )


if __name__ == "__main__":
    main()
