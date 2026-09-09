from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OUTPUT_DIR = (Path(__file__).resolve().parent / "../reports/forecast-runs").resolve()

REQUIRED_COLUMNS = (
    "target",
    "model",
    "forecast_start",
    "forecast_end",
    "mae_kwh",
    "rmse_kwh",
    "bias_kwh",
    "mean_abs_daily_energy_error_kwh",
)
DEFAULT_WEIGHTS = {
    "mae": 0.30,
    "rmse": 0.20,
    "daily_energy": 0.25,
    "bias": 0.15,
    "stability": 0.10,
}
SEASONS = {
    "winter": (12, 1, 2),
    "spring": (3, 4, 5),
    "summer": (6, 7, 8),
    "autumn": (9, 10, 11),
}
OUTPUT_COLUMNS = [
    "target",
    "slice",
    "evidence_label",
    "rank",
    "model",
    "model_family",
    "weather_source",
    "run_count",
    "window_count",
    "recommendation_status",
    "selection_score",
    "mae_component",
    "rmse_component",
    "daily_energy_component",
    "bias_component",
    "stability_component",
    "mae_weight",
    "rmse_weight",
    "daily_energy_weight",
    "bias_weight",
    "stability_weight",
    "median_mae_kwh",
    "median_rmse_kwh",
    "mean_bias_kwh",
    "median_abs_bias_kwh",
    "median_mean_abs_daily_energy_error_kwh",
    "stability_cv_mae",
    "diagnostics",
]
QUANTILE_METRIC_TOKENS = ("quantile", "p10", "p50", "p90", "crps", "winkler", "coverage")


@dataclass(frozen=True)
class SelectionResult:
    target: str
    slice_name: str
    evidence_label: str
    rank: int | None
    model: str
    model_family: str
    weather_source: str
    run_count: int
    window_count: int
    recommendation_status: str
    selection_score: float | None
    mae_component: float | None
    rmse_component: float | None
    daily_energy_component: float | None
    bias_component: float | None
    stability_component: float | None
    median_mae_kwh: float | None
    median_rmse_kwh: float | None
    mean_bias_kwh: float | None
    median_abs_bias_kwh: float | None
    median_mean_abs_daily_energy_error_kwh: float | None
    stability_cv_mae: float | None
    diagnostics: tuple[str, ...]

    def as_row(self) -> dict[str, Any]:
        return self.__dict__.copy()


def read_metric_rows(paths: list[Path]) -> tuple[list[dict[str, str]], list[str]]:
    rows: list[dict[str, str]] = []
    diagnostics: list[str] = []
    for path in paths:
        if not path.exists():
            diagnostics.append(f"missing input file: {path}")
            continue
        with path.open(encoding="utf-8", newline="") as file:
            reader = csv.DictReader(file)
            missing_columns = [column for column in REQUIRED_COLUMNS if column not in (reader.fieldnames or [])]
            if missing_columns:
                diagnostics.append(f"{path}: missing required columns: {', '.join(missing_columns)}")
                continue
            for index, row in enumerate(reader, start=2):
                normalized = dict(row)
                normalized["source_file"] = str(path)
                normalized["source_line"] = str(index)
                rows.append(normalized)
    return rows, diagnostics


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def timestamped_report_path(output_dir: Path, stem: str, suffix: str) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return output_dir / f"{stem}-{timestamp}{suffix}"


def validate_metric_rows(rows: list[dict[str, str]]) -> list[str]:
    diagnostics = []
    for row in rows:
        location = f"{row.get('source_file', '<input>')}:{row.get('source_line', '?')}"
        for column in REQUIRED_COLUMNS:
            if not str(row.get(column, "")).strip():
                diagnostics.append(f"{location}: missing required value: {column}")
        for column in ("mae_kwh", "rmse_kwh", "bias_kwh", "mean_abs_daily_energy_error_kwh"):
            if str(row.get(column, "")).strip():
                try:
                    float(row[column])
                except ValueError:
                    diagnostics.append(f"{location}: invalid numeric value for {column}: {row[column]}")
        for column in ("forecast_start", "forecast_end"):
            if str(row.get(column, "")).strip():
                try:
                    parse_utc(row[column])
                except ValueError:
                    diagnostics.append(f"{location}: invalid timestamp for {column}: {row[column]}")
    return diagnostics


def filter_rows(
    rows: list[dict[str, str]],
    *,
    month: int | None = None,
    season: str | None = None,
    horizon: str | None = None,
) -> list[dict[str, str]]:
    filtered = []
    season_months = SEASONS.get(season or "")
    for row in rows:
        forecast_start = parse_utc(row["forecast_start"])
        if month is not None and forecast_start.month != month:
            continue
        if season_months is not None and forecast_start.month not in season_months:
            continue
        if horizon is not None and row.get("horizon") != horizon:
            continue
        filtered.append(row)
    return filtered


def slice_name(*, month: int | None = None, season: str | None = None, horizon: str | None = None) -> str:
    parts = []
    if month is not None:
        parts.append(f"month={month:02d}")
    if season:
        parts.append(f"season={season}")
    if horizon:
        parts.append(f"horizon={horizon}")
    return ";".join(parts) if parts else "full-period"


def parse_weights(value: str | None) -> dict[str, float]:
    weights = dict(DEFAULT_WEIGHTS)
    if not value:
        return weights
    for item in value.split(","):
        name, separator, raw_weight = item.partition("=")
        if not separator or name not in weights:
            raise ValueError(f"Unsupported weight override: {item}")
        weights[name] = float(raw_weight)
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("Weight total must be positive")
    return {name: weight / total for name, weight in weights.items()}


def select_models(
    rows: list[dict[str, str]],
    *,
    weights: dict[str, float] | None = None,
    min_windows: int = 2,
    current_slice: str = "full-period",
) -> list[SelectionResult]:
    weights = weights or DEFAULT_WEIGHTS
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row_is_complete(row):
            groups[(row["target"], row["model"])].append(row)

    by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (target, model), group in groups.items():
        summary = summarize_group(target, model, group)
        summary["recommendation_status"] = recommendation_status(summary["window_count"], min_windows)
        by_target[target].append(summary)

    results = []
    for target, summaries in sorted(by_target.items()):
        eligible = [summary for summary in summaries if summary["recommendation_status"] != "insufficient-sample"]
        components = score_components(eligible, weights) if eligible else {}
        ranked = sorted(
            eligible,
            key=lambda summary: (components[summary["model"]]["selection_score"], summary["model"]),
        )
        rank_by_model = {summary["model"]: index for index, summary in enumerate(ranked, start=1)}

        for summary in sorted(summaries, key=lambda item: (rank_by_model.get(item["model"], 9999), item["model"])):
            component = components.get(summary["model"], {})
            results.append(
                SelectionResult(
                    target=target,
                    slice_name=current_slice,
                    evidence_label="rolling" if summary["window_count"] > 1 else "fixed-window-only",
                    rank=rank_by_model.get(summary["model"]),
                    model=summary["model"],
                    model_family=summary["model_family"],
                    weather_source=summary["weather_source"],
                    run_count=summary["run_count"],
                    window_count=summary["window_count"],
                    recommendation_status=summary["recommendation_status"],
                    selection_score=component.get("selection_score"),
                    mae_component=component.get("mae"),
                    rmse_component=component.get("rmse"),
                    daily_energy_component=component.get("daily_energy"),
                    bias_component=component.get("bias"),
                    stability_component=component.get("stability"),
                    median_mae_kwh=summary["median_mae_kwh"],
                    median_rmse_kwh=summary["median_rmse_kwh"],
                    mean_bias_kwh=summary["mean_bias_kwh"],
                    median_abs_bias_kwh=summary["median_abs_bias_kwh"],
                    median_mean_abs_daily_energy_error_kwh=summary["median_mean_abs_daily_energy_error_kwh"],
                    stability_cv_mae=summary["stability_cv_mae"],
                    diagnostics=tuple(summary["diagnostics"]),
                )
            )
    return results


def row_is_complete(row: dict[str, str]) -> bool:
    return all(str(row.get(column, "")).strip() for column in REQUIRED_COLUMNS)


def summarize_group(target: str, model: str, group: list[dict[str, str]]) -> dict[str, Any]:
    mae_values = float_values(group, "mae_kwh")
    rmse_values = float_values(group, "rmse_kwh")
    bias_values = float_values(group, "bias_kwh")
    daily_values = float_values(group, "mean_abs_daily_energy_error_kwh")
    windows = {f"{row['forecast_start']}|{row['forecast_end']}" for row in group}
    diagnostics = []
    stability = coefficient_of_variation(mae_values)
    if stability is None:
        diagnostics.append("stability unavailable: fewer than two MAE values or zero mean MAE")
    return {
        "target": target,
        "model": model,
        "model_family": first_present(group, "model_family"),
        "weather_source": first_present(group, "weather_source"),
        "run_count": len(group),
        "window_count": len(windows),
        "median_mae_kwh": median(mae_values),
        "median_rmse_kwh": median(rmse_values),
        "mean_bias_kwh": mean(bias_values),
        "median_abs_bias_kwh": median([abs(value) for value in bias_values]),
        "median_mean_abs_daily_energy_error_kwh": median(daily_values),
        "stability_cv_mae": stability,
        "diagnostics": diagnostics,
    }


def recommendation_status(window_count: int, min_windows: int) -> str:
    if window_count <= 1:
        return "fixed-window-only"
    if window_count < min_windows:
        return "insufficient-sample"
    return "primary"


def score_components(summaries: list[dict[str, Any]], weights: dict[str, float]) -> dict[str, dict[str, float]]:
    metric_values = {
        "mae": {summary["model"]: summary["median_mae_kwh"] for summary in summaries},
        "rmse": {summary["model"]: summary["median_rmse_kwh"] for summary in summaries},
        "daily_energy": {summary["model"]: summary["median_mean_abs_daily_energy_error_kwh"] for summary in summaries},
        "bias": {summary["model"]: summary["median_abs_bias_kwh"] for summary in summaries},
        "stability": {summary["model"]: summary["stability_cv_mae"] for summary in summaries},
    }
    ranks = {name: dense_ranks(values) for name, values in metric_values.items()}
    result: dict[str, dict[str, float]] = {}
    for summary in summaries:
        model = summary["model"]
        component = {}
        for name, weight in weights.items():
            rank = ranks[name].get(model, len(summaries) + 1)
            component[name] = rank * weight
        component["selection_score"] = sum(component.values())
        result[model] = component
    return result


def dense_ranks(values: dict[str, float | None]) -> dict[str, int]:
    present = sorted({value for value in values.values() if value is not None})
    rank_by_value = {value: index for index, value in enumerate(present, start=1)}
    return {model: rank_by_value[value] for model, value in values.items() if value is not None}


def coefficient_of_variation(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    average = mean(values)
    if average is None or abs(average) < 1e-12:
        return None
    variance = sum((value - average) ** 2 for value in values) / len(values)
    return math.sqrt(variance) / abs(average)


def float_values(rows: list[dict[str, str]], column: str) -> list[float]:
    return [float(row[column]) for row in rows if str(row.get(column, "")).strip()]


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def first_present(rows: list[dict[str, str]], column: str) -> str:
    for row in rows:
        value = str(row.get(column, "")).strip()
        if value:
            return value
    return "unknown"


def write_outputs(
    output_dir: Path,
    results: list[SelectionResult],
    *,
    input_paths: list[Path],
    diagnostics: list[str],
    weights: dict[str, float],
    current_slice: str,
    source_rows: list[dict[str, str]] | None = None,
) -> tuple[Path, Path]:
    if not results:
        raise ValueError("No eligible model-selection results to write")
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = timestamped_report_path(output_dir, "forecast-model-selection", suffix=".csv")
    markdown_path = csv_path.with_suffix(".md")
    quantile_columns = detect_quantile_columns(source_rows or [])
    write_csv(csv_path, results, weights)
    write_markdown(
        markdown_path,
        results,
        input_paths=input_paths,
        diagnostics=diagnostics,
        weights=weights,
        current_slice=current_slice,
        quantile_columns=quantile_columns,
    )
    return csv_path, markdown_path


def detect_quantile_columns(rows: list[dict[str, str]]) -> list[str]:
    columns = set()
    for row in rows:
        columns.update(row)
    return sorted(column for column in columns if any(token in column.lower() for token in QUANTILE_METRIC_TOKENS))


def write_csv(path: Path, results: list[SelectionResult], weights: dict[str, float]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for result in results:
            row = result.as_row()
            row["slice"] = result.slice_name
            row["diagnostics"] = "; ".join(result.diagnostics)
            for name, weight in weights.items():
                row[f"{name}_weight"] = weight
            writer.writerow({column: format_cell(row.get(column)) for column in OUTPUT_COLUMNS})


def write_markdown(
    path: Path,
    results: list[SelectionResult],
    *,
    input_paths: list[Path],
    diagnostics: list[str],
    weights: dict[str, float],
    current_slice: str,
    quantile_columns: list[str],
) -> None:
    lines = [
        "# Forecast Model Selection Report",
        "",
        f"Generated at: `{datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')}`",
        f"Evaluation slice: `{current_slice}`",
        "",
        "## Recommendations",
        "",
    ]
    for target in sorted({result.target for result in results}):
        target_results = [result for result in results if result.target == target]
        best = next((result for result in target_results if result.rank == 1), None)
        if best is None:
            lines.append(f"- `{target}`: no recommendation available.")
        else:
            label = "primary rolling evidence" if best.recommendation_status == "primary" else best.recommendation_status
            lines.append(f"- `{target}`: `{best.model}` ranked first from {label}.")
    lines.extend(["", "## Ranking Table", ""])
    lines.append("| Target | Rank | Model | Status | Score | Windows | MAE | RMSE | Bias | Daily Energy Error | Stability |")
    lines.append("|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for result in sorted(results, key=lambda item: (item.target, item.rank or 9999, item.model)):
        lines.append(
            "| "
            + " | ".join(
                [
                    result.target,
                    str(result.rank or ""),
                    f"`{result.model}`",
                    result.recommendation_status,
                    format_cell(result.selection_score),
                    str(result.window_count),
                    format_cell(result.median_mae_kwh),
                    format_cell(result.median_rmse_kwh),
                    format_cell(result.mean_bias_kwh),
                    format_cell(result.median_mean_abs_daily_energy_error_kwh),
                    format_cell(result.stability_cv_mae),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Scoring Method",
            "",
            "Lower scores are better. Components use dense ranks, where rank 1 is the best value for that metric.",
            "Stability is the coefficient of variation of rolling-window MAE: population standard deviation divided by mean MAE.",
            "Plain MAPE is not used as a primary score component because PV generation can contain zero or near-zero actual values.",
            "",
            "| Component | Weight |",
            "|---|---:|",
        ]
    )
    for name, weight in weights.items():
        lines.append(f"| `{name}` | {weight:.6g} |")
    weather_sources = sorted({result.weather_source for result in results if result.weather_source})
    lines.extend(
        [
            "",
            "## Weather Source Limitation",
            "",
            "Weather-dependent historical backtests in this project use observed historical weather unless a report explicitly states otherwise.",
            "Observed weather sources in this selection: " + ", ".join(f"`{source}`" for source in weather_sources) + ".",
            "",
            "## Uncertainty Evidence",
            "",
            "Quantile-specific metrics are not included in the default point-forecast score unless compatible p50 point metrics are present in the input metric table.",
        ]
    )
    if quantile_columns:
        lines.append("Detected quantile or uncertainty metric columns: " + ", ".join(f"`{column}`" for column in quantile_columns) + ".")
        lines.append("These columns are reported here as uncertainty evidence only, not as default point-score components.")
    else:
        lines.append("No quantile-specific score columns were detected in this report input.")
    lines.extend(["", "## Diagnostics", ""])
    all_diagnostics = list(diagnostics)
    for result in results:
        all_diagnostics.extend(f"{result.target}/{result.model}: {diagnostic}" for diagnostic in result.diagnostics)
    if all_diagnostics:
        lines.extend(f"- {diagnostic}" for diagnostic in all_diagnostics)
    else:
        lines.append("- No diagnostics.")
    lines.extend(
        [
            "",
            "## Source Traceability",
            "",
            "Project sources:",
            "- `docs/technical-specification.md`, sections 7 and 8.",
            "- `openspec/changes/add-forecast-model-selection/proposal.md`.",
            "- `openspec/changes/add-forecast-model-selection/design.md`.",
            "- `openspec/changes/add-forecast-model-selection/specs/forecast-model-selection/spec.md`.",
            "- `openspec/changes/add-researched-forecast-models/design.md`.",
            "- `openspec/changes/define-baseline-forecast-backtest/design.md`.",
            "",
            "Input metric files:",
        ]
    )
    lines.extend(f"- `{path}`" for path in input_paths)
    lines.extend(
        [
            "",
            "Methodology references:",
            "- Hyndman, R. J., & Athanasopoulos, G. (2021). *Forecasting: Principles and Practice*, 3rd ed., sections 5.8, 5.9, and 5.10. URLs: `https://otexts.com/fpp3/accuracy.html`, `https://otexts.com/fpp3/distaccuracy.html`, `https://otexts.com/fpp3/tscv.html`.",
            "- Hyndman, R. J., & Koehler, A. B. (2006). Another look at measures of forecast accuracy. *International Journal of Forecasting*, 22(4), 679-688. DOI: `10.1016/j.ijforecast.2006.03.001`.",
            "- Gneiting, T., & Raftery, A. E. (2007). Strictly Proper Scoring Rules, Prediction, and Estimation. *Journal of the American Statistical Association*, 102(477), 359-378. DOI: `10.1198/016214506000001437`.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def format_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rank forecast models from exported metric CSV files.")
    parser.add_argument("--input", action="append", required=True, help="Forecast metric table CSV. Repeat for multiple targets.")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--month", type=int, choices=range(1, 13), metavar="1-12")
    parser.add_argument("--season", choices=sorted(SEASONS))
    parser.add_argument("--horizon")
    parser.add_argument("--min-windows", type=int, default=2)
    parser.add_argument("--weights", help="Comma-separated overrides such as mae=0.4,rmse=0.2,daily_energy=0.2,bias=0.1,stability=0.1")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.min_windows < 1:
        raise ValueError("min-windows must be at least 1")
    if args.month is not None and args.season is not None:
        raise ValueError("Use either --month or --season, not both")
    input_paths = [Path(value) for value in args.input]
    rows, diagnostics = read_metric_rows(input_paths)
    diagnostics.extend(validate_metric_rows(rows))
    valid_rows = [row for row in rows if row_is_complete(row)]
    filtered = filter_rows(valid_rows, month=args.month, season=args.season, horizon=args.horizon)
    weights = parse_weights(args.weights)
    current_slice = slice_name(month=args.month, season=args.season, horizon=args.horizon)
    results = select_models(filtered, weights=weights, min_windows=args.min_windows, current_slice=current_slice)
    csv_path, markdown_path = write_outputs(
        Path(args.output_dir),
        results,
        input_paths=input_paths,
        diagnostics=diagnostics,
        weights=weights,
        current_slice=current_slice,
        source_rows=filtered,
    )
    print(f"Wrote forecast model-selection CSV to {csv_path}")
    print(f"Wrote forecast model-selection report to {markdown_path}")


if __name__ == "__main__":
    try:
        main()
    except ValueError as exception:
        print(f"error: {exception}", file=sys.stderr)
        raise SystemExit(1)
