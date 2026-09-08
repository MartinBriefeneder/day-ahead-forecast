from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from compare_forecasts import expected_interval_count, fetch_run_summaries, select_summaries
from forecast_dataset_api import DEFAULT_TIMEOUT_SECONDS
from forecast_runner import BASE_URL, OUTPUT_DIR, timestamped_report_path

RUN_LIMIT = 100
POINT_LIMIT = 10000
TIMEOUT_SECONDS = DEFAULT_TIMEOUT_SECONDS

TABLE_COLUMNS = [
    "run_id",
    "target",
    "model",
    "model_family",
    "weather_source",
    "train_start",
    "train_end",
    "forecast_start",
    "forecast_end",
    "sample_interval",
    "horizon",
    "forecast_intervals",
    "actual_intervals",
    "aligned_intervals",
    "missing_actual_intervals",
    "mae_kwh",
    "rmse_kwh",
    "bias_kwh",
    "total_forecast_kwh",
    "total_actual_kwh",
    "total_energy_error_kwh",
    "mean_abs_daily_energy_error_kwh",
    "wape_percent",
    "report_path",
]

AGGREGATE_COLUMNS = [
    "target",
    "model",
    "model_family",
    "run_count",
    "total_aligned_intervals",
    "mean_mae_kwh",
    "mean_rmse_kwh",
    "mean_bias_kwh",
    "mean_wape_percent",
    "total_forecast_kwh",
    "total_actual_kwh",
    "total_energy_error_kwh",
]


def fetch_comparison_response(base_url: str, run_id: str, *, limit: int, timeout_seconds: int | None) -> dict[str, Any]:
    response = requests.get(
        f"{base_url}/api/forecast-runs/{quote(run_id, safe='')}/comparison",
        params={"limit": limit},
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    return response.json()


def metric_table_rows(
    base_url: str,
    summaries: list[dict[str, Any]],
    *,
    point_limit: int,
    timeout_seconds: int | None,
    require_complete: bool = False,
) -> list[dict[str, Any]]:
    rows = []
    for summary in deduplicate_summaries(summaries):
        comparison = fetch_comparison_response(
            base_url,
            summary["runId"],
            limit=point_limit,
            timeout_seconds=timeout_seconds,
        )
        points = comparison.get("points", [])
        expected_count = expected_interval_count(summary)
        if require_complete and expected_count is not None and len(points) < expected_count:
            continue
        rows.append(build_metric_row(summary, comparison))
    return sorted(rows, key=lambda row: (str(row["target"]), str(row["model"]), str(row["run_id"])))


def deduplicate_summaries(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_run_id: dict[str, dict[str, Any]] = {}
    for summary in summaries:
        run_id = str(summary.get("runId", ""))
        if not run_id:
            continue
        existing = by_run_id.get(run_id)
        if existing is None or str(summary.get("generatedAt", "")) > str(existing.get("generatedAt", "")):
            by_run_id[run_id] = summary
    return list(by_run_id.values())


def build_metric_row(summary: dict[str, Any], comparison: dict[str, Any]) -> dict[str, Any]:
    metrics = compute_metrics(comparison.get("points", []), comparison.get("diagnostics", {}))
    return {
        "run_id": summary.get("runId"),
        "target": summary.get("target"),
        "model": summary.get("model"),
        "model_family": summary.get("modelFamily"),
        "weather_source": weather_source(summary.get("model")),
        "train_start": summary.get("trainStart"),
        "train_end": summary.get("trainEnd"),
        "forecast_start": summary.get("forecastStart"),
        "forecast_end": summary.get("forecastEnd"),
        "sample_interval": summary.get("sampleInterval"),
        "horizon": summary.get("horizon"),
        "report_path": summary.get("reportPath"),
        **metrics,
    }


def compute_metrics(points: list[dict[str, Any]], diagnostics: dict[str, Any] | None = None) -> dict[str, Any]:
    diagnostics = diagnostics or {}
    forecast_values = [float(point["forecastKwh"]) for point in points if point.get("forecastKwh") is not None]
    aligned = [
        point
        for point in points
        if point.get("forecastKwh") is not None and point.get("actualKwh") is not None
    ]
    errors = [float(point["forecastKwh"]) - float(point["actualKwh"]) for point in aligned]
    actual_values = [float(point["actualKwh"]) for point in aligned]

    result: dict[str, Any] = {
        "forecast_intervals": len(points),
        "actual_intervals": diagnostics.get("actualPointCount"),
        "aligned_intervals": len(aligned),
        "missing_actual_intervals": len(points) - len(aligned),
        "total_forecast_kwh": sum(forecast_values),
    }
    if not aligned:
        return result

    result.update(
        {
            "mae_kwh": sum(abs(error) for error in errors) / len(errors),
            "rmse_kwh": math.sqrt(sum(error * error for error in errors) / len(errors)),
            "bias_kwh": sum(errors) / len(errors),
            "total_actual_kwh": sum(actual_values),
            "total_energy_error_kwh": sum(errors),
            "mean_abs_daily_energy_error_kwh": mean_abs_daily_energy_error(aligned),
        }
    )
    wape_denominator = sum(abs(value) for value in actual_values)
    if wape_denominator > 1e-9:
        result["wape_percent"] = sum(abs(error) for error in errors) / wape_denominator * 100
    return result


def mean_abs_daily_energy_error(points: list[dict[str, Any]]) -> float:
    errors_by_day: dict[str, float] = defaultdict(float)
    for point in points:
        timestamp = parse_utc(str(point["timestamp"]))
        errors_by_day[timestamp.date().isoformat()] += float(point["forecastKwh"]) - float(point["actualKwh"])
    return sum(abs(error) for error in errors_by_day.values()) / len(errors_by_day)


def weather_source(model: object) -> str:
    model_name = str(model or "")
    if model_name == "weekly-persistence":
        return "energy-only"
    if model_name == "openstef-future-xgboost":
        return "Gridoo forecast weather"
    if model_name.startswith("openstef"):
        return "observed historical weather"
    return "unknown"


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def write_metric_table_files(output_dir: Path, target: str, rows: list[dict[str, Any]], *, all_saved: bool = False) -> tuple[Path, Path]:
    require_rows(rows)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{target}-{'all-saved-' if all_saved else ''}forecast-metric-table"
    markdown_path = timestamped_report_path(output_dir, stem, suffix=".md")
    csv_path = markdown_path.with_suffix(".csv")
    markdown_path.write_text(markdown_table(rows), encoding="utf-8")
    write_csv(csv_path, rows)
    return markdown_path, csv_path


def aggregate_metric_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(str(row.get("target") or ""), str(row.get("model") or ""))].append(row)

    aggregates = []
    for (target, model), group in sorted(groups.items()):
        aggregates.append(
            {
                "target": target,
                "model": model,
                "model_family": first_present(group, "model_family"),
                "run_count": len(group),
                "total_aligned_intervals": sum_numeric(group, "aligned_intervals"),
                "mean_mae_kwh": mean_numeric(group, "mae_kwh"),
                "mean_rmse_kwh": mean_numeric(group, "rmse_kwh"),
                "mean_bias_kwh": mean_numeric(group, "bias_kwh"),
                "mean_wape_percent": mean_numeric(group, "wape_percent"),
                "total_forecast_kwh": sum_numeric(group, "total_forecast_kwh"),
                "total_actual_kwh": sum_numeric(group, "total_actual_kwh"),
                "total_energy_error_kwh": sum_numeric(group, "total_energy_error_kwh"),
            }
        )
    return aggregates


def write_aggregate_metric_files(output_dir: Path, target: str, rows: list[dict[str, Any]], *, all_saved: bool = False) -> tuple[Path, Path]:
    aggregates = aggregate_metric_rows(rows)
    require_rows(aggregates)
    stem = f"{target}-{'all-saved-' if all_saved else ''}forecast-aggregate-metrics"
    markdown_path = timestamped_report_path(output_dir, stem, suffix=".md")
    csv_path = markdown_path.with_suffix(".csv")
    markdown_path.write_text(markdown_table_for_columns(aggregates, AGGREGATE_COLUMNS, "# Forecast Aggregate Metrics"), encoding="utf-8")
    write_csv_for_columns(csv_path, aggregates, AGGREGATE_COLUMNS)
    return markdown_path, csv_path


def markdown_table(rows: list[dict[str, Any]]) -> str:
    require_rows(rows)
    return markdown_table_for_columns(rows, TABLE_COLUMNS, "# Forecast Metric Table")


def markdown_table_for_columns(rows: list[dict[str, Any]], columns: list[str], title: str) -> str:
    lines = [
        title,
        "",
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(format_cell(row.get(column)) for column in columns) + " |")
    lines.append("")
    return "\n".join(lines)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    write_csv_for_columns(path, rows, TABLE_COLUMNS)


def write_csv_for_columns(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: format_csv_cell(row.get(column)) for column in columns})


def numeric_values(rows: list[dict[str, Any]], column: str) -> list[float]:
    values = []
    for row in rows:
        value = row.get(column)
        if value is None or value == "":
            continue
        values.append(float(value))
    return values


def mean_numeric(rows: list[dict[str, Any]], column: str) -> float | None:
    values = numeric_values(rows, column)
    if not values:
        return None
    return sum(values) / len(values)


def sum_numeric(rows: list[dict[str, Any]], column: str) -> float | None:
    values = numeric_values(rows, column)
    if not values:
        return None
    return sum(values)


def first_present(rows: list[dict[str, Any]], column: str) -> object:
    for row in rows:
        value = row.get(column)
        if value not in (None, ""):
            return value
    return None


def format_cell(value: object) -> str:
    text = format_csv_cell(value)
    return text.replace("|", "\\|")


def format_csv_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def require_rows(rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("No metric rows to write")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export saved forecast-run metrics as Markdown and CSV tables.")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--target", default="generation", choices=("generation", "consumption"))
    parser.add_argument("--forecast-start")
    parser.add_argument("--forecast-end")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--run-limit", type=int, default=RUN_LIMIT)
    parser.add_argument("--point-limit", type=int, default=POINT_LIMIT)
    parser.add_argument("--all-saved", action="store_true")
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--aggregate", action="store_true", help="Also write aggregate metrics by target and model.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    summaries = select_summaries(
        fetch_run_summaries(args.base_url, target=args.target, limit=args.run_limit, timeout_seconds=TIMEOUT_SECONDS),
        target=args.target,
        forecast_start=args.forecast_start,
        forecast_end=args.forecast_end,
        all_saved=args.all_saved,
    )
    if not summaries:
        raise ValueError("No matching saved forecast runs found")

    rows = metric_table_rows(
        args.base_url,
        summaries,
        point_limit=args.point_limit,
        timeout_seconds=TIMEOUT_SECONDS,
        require_complete=args.require_complete,
    )
    markdown_path, csv_path = write_metric_table_files(
        Path(args.output_dir),
        args.target,
        rows,
        all_saved=args.all_saved,
    )
    print(f"Wrote forecast metric table to {markdown_path}")
    print(f"Wrote forecast metric CSV to {csv_path}")
    if args.aggregate:
        aggregate_markdown_path, aggregate_csv_path = write_aggregate_metric_files(
            Path(args.output_dir),
            args.target,
            rows,
            all_saved=args.all_saved,
        )
        print(f"Wrote forecast aggregate metrics to {aggregate_markdown_path}")
        print(f"Wrote forecast aggregate CSV to {aggregate_csv_path}")


if __name__ == "__main__":
    try:
        main()
    except ValueError as exception:
        print(f"error: {exception}", file=sys.stderr)
        raise SystemExit(1)
