import argparse
import math
import html
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from forecast_dataset_api import fetch_forecast_dataframe

BASE_URL = "http://localhost:8080"
TARGET = "consumption"
TRAIN_START = datetime(2025, 6, 1, tzinfo=timezone.utc)
TRAIN_DAYS = 90
DEFAULT_FORECAST_WEEKS = 1
MAX_FORECAST_WEEKS = 4
MODELS = ("weekly-persistence",)
OUTPUT_DIR = (Path(__file__).resolve().parent / "../reports/forecast-runs").resolve()
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
    if args.forecast_weeks <= 0 or args.forecast_weeks > MAX_FORECAST_WEEKS:
        raise ValueError(f"forecast-weeks must be between 1 and {MAX_FORECAST_WEEKS}")

    horizon = timedelta(weeks=args.forecast_weeks)
    if args.forecast_start:
        forecast_start = parse_utc_argument(args.forecast_start)
        train_start = parse_utc_argument(args.train_start) if args.train_start else forecast_start - timedelta(days=args.train_days)
    else:
        train_start = parse_utc_argument(args.train_start) if args.train_start else TRAIN_START
        forecast_start = train_start + timedelta(days=args.train_days)

    return train_start, forecast_start, forecast_start + horizon, horizon


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


def write_reports(output_dir: Path, payloads: list[dict], actual: pd.Series | None = None) -> Path | None:
    output_dir.mkdir(parents=True, exist_ok=True)
    include_dashboard = actual is not None and payloads
    if include_dashboard:
        dashboard_path = output_dir / "forecast-backtest-dashboard.html"
        dashboard_path.write_text(backtest_dashboard_html(payloads, actual), encoding="utf-8")
        return dashboard_path
    return None


def backtest_dashboard_html(payloads: list[dict], actual: pd.Series) -> str:
    from plotly import graph_objects as go
    from plotly.subplots import make_subplots

    frames = [(payload, payload_comparison_frame(payload)) for payload in payloads]
    first = payloads[0]
    train_start = parse_utc(first["trainStart"])
    forecast_start = parse_utc(first["forecastStart"])
    forecast_end = parse_utc(first["forecastEnd"])
    actual = actual.sort_index()
    actual_context = actual[(actual.index >= train_start) & (actual.index < forecast_end)]
    actual_forecast = actual[(actual.index >= forecast_start) & (actual.index < forecast_end)]

    fig = make_subplots(
        rows=4,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        subplot_titles=(
            "Actuals and forecasts",
            "Interval error (forecast minus actual)",
            "Daily energy totals",
            "Cumulative energy error",
        ),
    )

    fig.add_trace(
        go.Scatter(
            x=actual_context.index,
            y=actual_context.values,
            mode="lines",
            name="Actual history",
            line={"color": "rgba(100,116,139,0.45)", "width": 1},
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=actual_forecast.index,
            y=actual_forecast.values,
            mode="lines",
            name="Actual test window",
            line={"color": "#111827", "width": 2},
        ),
        row=1,
        col=1,
    )

    for payload, frame in frames:
        model = payload["model"]
        fig.add_trace(
            go.Scatter(
                x=frame.index,
                y=frame["forecast_kwh"],
                mode="lines",
                name=f"{model} forecast",
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=frame.index,
                y=frame["error_kwh"],
                mode="lines",
                name=f"{model} error",
            ),
            row=2,
            col=1,
        )

        daily = frame.dropna(subset=["forecast_kwh"]).resample("1D").sum(numeric_only=True)
        fig.add_trace(
            go.Bar(
                x=daily.index,
                y=daily["forecast_kwh"],
                name=f"{model} daily forecast",
                opacity=0.72,
            ),
            row=3,
            col=1,
        )
        cumulative_error = frame.dropna(subset=["error_kwh"])["error_kwh"].cumsum()
        fig.add_trace(
            go.Scatter(
                x=cumulative_error.index,
                y=cumulative_error.values,
                mode="lines",
                name=f"{model} cumulative error",
            ),
            row=4,
            col=1,
        )

    if not actual_forecast.empty:
        actual_daily = actual_forecast.resample("1D").sum()
        fig.add_trace(
            go.Bar(
                x=actual_daily.index,
                y=actual_daily.values,
                name="Actual daily energy",
                marker={"color": "#111827"},
                opacity=0.45,
            ),
            row=3,
            col=1,
        )

    fig.add_vrect(
        x0=train_start,
        x1=forecast_start,
        fillcolor="rgba(148,163,184,0.12)",
        line_width=0,
        annotation_text="training window",
        annotation_position="top left",
        row=1,
        col=1,
    )
    fig.add_vrect(
        x0=forecast_start,
        x1=forecast_end,
        fillcolor="rgba(59,130,246,0.08)",
        line_width=0,
        annotation_text="forecast window",
        annotation_position="top left",
        row=1,
        col=1,
    )
    fig.add_hline(y=0, line_color="#64748b", line_dash="dash", row=2, col=1)
    fig.add_hline(y=0, line_color="#64748b", line_dash="dash", row=4, col=1)
    fig.update_layout(
        title=f"{first['target'].capitalize()} Forecast Dashboard",
        template="plotly_white",
        hovermode="x unified",
        height=1180,
        barmode="group",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0},
        margin={"l": 70, "r": 30, "t": 130, "b": 60},
    )
    fig.update_yaxes(title_text="kWh / 15 min", row=1, col=1)
    fig.update_yaxes(title_text="kWh", row=2, col=1)
    fig.update_yaxes(title_text="kWh / day", row=3, col=1)
    fig.update_yaxes(title_text="kWh", row=4, col=1)
    fig.update_xaxes(title_text="Time (UTC)", row=4, col=1)

    return "\n".join(
        [
            "<!doctype html>",
            "<html lang=\"en\">",
            "<head>",
            "<meta charset=\"utf-8\">",
            "<title>Forecast Dashboard</title>",
            "<style>",
            "body{font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:24px;background:#f8fafc;color:#0f172a}",
            ".shell{max-width:1440px;margin:0 auto}",
            ".card{background:#fff;border:1px solid #e2e8f0;border-radius:16px;padding:18px 20px;margin-bottom:18px;box-shadow:0 1px 2px rgba(15,23,42,.04)}",
            ".meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin-top:12px}",
            ".metric-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}",
            ".metric{border:1px solid #e2e8f0;border-radius:12px;padding:12px;background:#f8fafc}",
            ".label{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:#64748b}",
            ".value{font-size:24px;font-weight:700;margin-top:4px}",
            "table{width:100%;border-collapse:collapse;font-size:14px}",
            "th,td{padding:8px 10px;border-bottom:1px solid #e2e8f0;text-align:right}",
            "th:first-child,td:first-child{text-align:left}",
            "th{color:#475569;font-weight:600;background:#f8fafc}",
            "</style>",
            "</head>",
            "<body><main class=\"shell\">",
            "<section class=\"card\">",
            f"<h1>{html.escape(first['target'].capitalize())} Forecast Dashboard</h1>",
            "<p>This report shows the training window, forecast window, forecast quality when actual values exist, and expected energy totals.</p>",
            "<div class=\"meta\">",
            meta_item("Training start", first["trainStart"]),
            meta_item("Forecast start", first["forecastStart"]),
            meta_item("Forecast end", first["forecastEnd"]),
            meta_item("Sample interval", first["sampleInterval"]),
            meta_item("Horizon", first["horizon"]),
            "</div></section>",
            "<section class=\"card\"><h2>Metric Summary</h2>",
            metric_cards(payloads),
            metric_table(payloads),
            "</section>",
            "<section class=\"card\"><h2>Expected Energy Totals</h2>",
            aggregate_tables(payloads),
            "</section>",
            "<section class=\"card\">",
            fig.to_html(full_html=False, include_plotlyjs=True),
            "</section>",
            "</main></body></html>",
        ]
    )


def payload_comparison_frame(payload: dict) -> pd.DataFrame:
    frame = pd.DataFrame(payload["points"])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.set_index("timestamp").rename(
        columns={
            "forecastKwh": "forecast_kwh",
            "actualKwh": "actual_kwh",
            "errorKwh": "error_kwh",
        }
    )
    if "error_kwh" not in frame.columns and {"forecast_kwh", "actual_kwh"}.issubset(frame.columns):
        frame["error_kwh"] = frame["forecast_kwh"] - frame["actual_kwh"]
    return frame


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def meta_item(label: str, value: object) -> str:
    return f"<div class=\"metric\"><div class=\"label\">{html.escape(label)}</div><div>{html.escape(str(value))}</div></div>"


def metric_cards(payloads: list[dict]) -> str:
    cards = []
    for payload in payloads:
        metrics = payload["metrics"]
        cards.append(
            "".join(
                [
                    "<div class=\"metric\">",
                    f"<div class=\"label\">{html.escape(payload['model'])} MAE</div>",
                    f"<div class=\"value\">{format_metric(metrics.get('mae_kwh'))}</div>",
                    "<div class=\"label\">kWh per interval</div>",
                    "</div>",
                    "<div class=\"metric\">",
                    f"<div class=\"label\">{html.escape(payload['model'])} Bias</div>",
                    f"<div class=\"value\">{format_metric(metrics.get('bias_kwh'))}</div>",
                    "<div class=\"label\">kWh per interval</div>",
                    "</div>",
                ]
            )
        )
    return "<div class=\"metric-grid\">" + "".join(cards) + "</div>"


def metric_table(payloads: list[dict]) -> str:
    rows = []
    for payload in payloads:
        metrics = payload["metrics"]
        rows.append(
            "<tr>"
            f"<td>{html.escape(payload['model'])}</td>"
            f"<td>{metrics.get('aligned_intervals', '')}</td>"
            f"<td>{format_metric(metrics.get('mae_kwh'))}</td>"
            f"<td>{format_metric(metrics.get('rmse_kwh'))}</td>"
            f"<td>{format_metric(metrics.get('bias_kwh'))}</td>"
            f"<td>{format_metric(metrics.get('total_energy_error_kwh'))}</td>"
            f"<td>{format_metric(metrics.get('mean_abs_daily_energy_error_kwh'))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr>"
        "<th>Model</th><th>Aligned</th><th>MAE kWh</th><th>RMSE kWh</th><th>Bias kWh</th><th>Total error kWh</th><th>Mean abs daily error kWh</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def aggregate_tables(payloads: list[dict]) -> str:
    sections = []
    for payload in payloads:
        frame = payload_comparison_frame(payload)
        daily = frame.dropna(subset=["forecast_kwh"]).resample("1D").sum(numeric_only=True)
        weekly = frame.dropna(subset=["forecast_kwh"]).resample("W-MON", label="left", closed="left").sum(numeric_only=True)
        sections.append(f"<h3>{html.escape(payload['model'])}</h3>")
        sections.append(aggregate_table("Daily", daily))
        sections.append(aggregate_table("Weekly", weekly))
    return "".join(sections)


def aggregate_table(label: str, frame: pd.DataFrame) -> str:
    rows = []
    for timestamp, row in frame.iterrows():
        actual = row.get("actual_kwh")
        rows.append(
            "<tr>"
            f"<td>{html.escape(timestamp.isoformat())}</td>"
            f"<td>{format_metric(row.get('forecast_kwh'))}</td>"
            f"<td>{format_metric(actual) if pd.notna(actual) else ''}</td>"
            "</tr>"
        )
    return (
        f"<h4>{html.escape(label)} totals</h4>"
        "<table><thead><tr><th>Start</th><th>Forecast kWh</th><th>Actual kWh</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def format_metric(value: object) -> str:
    if value is None:
        return ""
    return f"{float(value):.4f}"


def none_if_nan(value: object) -> float | None:
    if pd.isna(value):
        return None
    return float(value)


def build_run_id(target: str, model: str, forecast_start: datetime) -> str:
    timestamp = forecast_start.strftime("%Y%m%dT%H%M%SZ")
    return f"{target}-{model}-{timestamp}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run simple benchmark energy forecasts.")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--target", choices=("consumption", "generation"), default=TARGET)
    parser.add_argument("--train-start", help="UTC ISO-8601 timestamp. Defaults to forecast-start minus train-days when forecast-start is set.")
    parser.add_argument("--train-days", type=int, default=TRAIN_DAYS)
    parser.add_argument("--forecast-start", help="UTC ISO-8601 timestamp. Defaults to train-start plus train-days.")
    parser.add_argument("--forecast-weeks", type=int, default=DEFAULT_FORECAST_WEEKS)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    output_dir = Path(args.output_dir)
    train_start, forecast_start, forecast_end, horizon = resolve_windows(args)
    data = fetch_forecast_dataframe(
        base_url=args.base_url,
        target=args.target,
        start=format_utc(train_start),
        end=format_utc(forecast_start if args.forecast_start else forecast_end),
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

    dashboard_path = write_reports(output_dir, payloads, actual)
    if dashboard_path is not None:
        print(f"Wrote forecast dashboard to {dashboard_path}")
    for payload in payloads:
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
