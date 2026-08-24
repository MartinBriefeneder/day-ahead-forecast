from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from forecast_dataset_api import DEFAULT_TIMEOUT_SECONDS
from forecast_runner import timestamped_report_path


BASE_URL = "http://localhost:8080"
OUTPUT_DIR = (Path(__file__).resolve().parent / "../reports/forecast-runs").resolve()
DEFAULT_OUTPUT = "all-python-forecast-comparison.html"
TARGET = "generation"
RUN_LIMIT = 100
POINT_LIMIT = 10000
TIMEOUT_SECONDS = DEFAULT_TIMEOUT_SECONDS


def fetch_run_summaries(base_url: str, *, target: str | None, limit: int, timeout_seconds: int | None) -> list[dict[str, Any]]:
    params: dict[str, str | int] = {"limit": limit}
    if target is not None:
        params["target"] = target
    response = requests.get(f"{base_url}/api/forecast-runs", params=params, timeout=timeout_seconds)
    response.raise_for_status()
    return response.json()


def fetch_comparison(base_url: str, run_id: str, *, limit: int, timeout_seconds: int | None) -> list[dict[str, Any]]:
    response = requests.get(
        f"{base_url}/api/forecast-runs/{quote(run_id, safe='')}/comparison",
        params={"limit": limit},
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    return response.json()["points"]


def group_key(summary: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(summary.get("target")),
        str(summary.get("forecastStart")),
        str(summary.get("forecastEnd")),
        str(summary.get("sampleInterval")),
    )


def select_summaries(
    summaries: list[dict[str, Any]],
    *,
    target: str | None,
    forecast_start: str | None,
    forecast_end: str | None,
    all_saved: bool = False,
) -> list[dict[str, Any]]:
    selected = [
        summary
        for summary in summaries
        if (target is None or summary.get("target") == target)
        and (forecast_start is None or summary.get("forecastStart") == forecast_start)
        and (forecast_end is None or summary.get("forecastEnd") == forecast_end)
    ]
    if all_saved:
        return selected
    if forecast_start is not None or forecast_end is not None:
        return selected

    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for summary in selected:
        groups[group_key(summary)].append(summary)
    if not groups:
        return []

    return max(
        groups.values(),
        key=lambda group: (
            len({summary.get("model") for summary in group}),
            max(str(summary.get("generatedAt", "")) for summary in group),
            max(str(summary.get("forecastStart", "")) for summary in group),
        ),
    )


def attach_comparison_points(
    base_url: str,
    summaries: list[dict[str, Any]],
    *,
    point_limit: int,
    timeout_seconds: int | None,
    require_complete: bool = True,
) -> list[dict[str, Any]]:
    runs = []
    for summary in summaries:
        run = dict(summary)
        run["points"] = fetch_comparison(base_url, summary["runId"], limit=point_limit, timeout_seconds=timeout_seconds)
        if run["points"]:
            expected_count = expected_interval_count(run)
            if expected_count is not None and len(run["points"]) < expected_count:
                message = (
                    f"[forecast-python] comparison run_id={run['runId']} has {len(run['points'])} "
                    f"point(s), expected {expected_count} for saved forecast window"
                )
                if require_complete:
                    print(f"{message}; skipped incomplete saved run", flush=True)
                    continue
                print(message, flush=True)
            runs.append(run)
    return runs


def write_comparison_figure(output_path: Path, runs: list[dict[str, Any]]) -> None:
    from plotly import graph_objects as go

    first = runs[0]
    target_label = str(first["target"]).capitalize()
    fig = go.Figure()

    actual_windows: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for run in runs:
        if any(point.get("actualKwh") is not None for point in run["points"]):
            actual_windows.setdefault(group_key(run), run)
    show_window_labels = len({group_key(run) for run in runs}) > 1

    for run in actual_windows.values():
        actual_points = run["points"]
        actual_values = [point.get("actualKwh") for point in actual_points]
        fig.add_trace(
            go.Scatter(
                x=[point["timestamp"] for point in actual_points],
                y=actual_values,
                mode=trace_mode(actual_points),
                name=f"Actual {target_label} {window_label(run)}",
                line={"color": "#111827", "width": 2},
            )
        )

    for run in sorted(runs, key=lambda item: str(item.get("model"))):
        fig.add_trace(
            go.Scatter(
                x=[point["timestamp"] for point in run["points"]],
                y=[point.get("forecastKwh") for point in run["points"]],
                mode=trace_mode(run["points"]),
                name=f"{run.get('model')} {window_label(run) if show_window_labels else ''}".strip(),
            )
        )

    fig.update_layout(
        title=(
            f"Python {target_label} {comparison_title(actual_windows)}<br>"
            f"<sup>{window_summary(runs)}</sup>"
        ),
        xaxis_title="Time (UTC)",
        yaxis_title=f"{target_label} energy (kWh per interval)",
        hovermode="x unified",
        template="plotly_white",
        height=620,
    )
    fig.write_html(output_path, include_plotlyjs=True)


def window_label(run: dict[str, Any]) -> str:
    return f"({run.get('forecastStart')} to {run.get('forecastEnd')})"


def trace_mode(points: list[dict[str, Any]]) -> str:
    if len(points) < 2:
        return "lines+markers"
    return "lines"


def comparison_title(actual_windows: dict[tuple[str, str, str, str], dict[str, Any]]) -> str:
    if actual_windows:
        return "Forecast vs Actual Comparison"
    return "Forecast-Only Comparison"


def window_summary(runs: list[dict[str, Any]]) -> str:
    groups = {group_key(run) for run in runs}
    if len(groups) == 1:
        run = runs[0]
        return f"{run['forecastStart']} to {run['forecastEnd']} ({run['sampleInterval']})"
    return f"{len(groups)} forecast windows, {len(runs)} saved runs"


def expected_interval_count(run: dict[str, Any]) -> int | None:
    try:
        forecast_start = parse_instant(str(run["forecastStart"]))
        forecast_end = parse_instant(str(run["forecastEnd"]))
        sample_interval = parse_sample_interval(str(run["sampleInterval"]))
    except (KeyError, ValueError):
        return None
    seconds = int((forecast_end - forecast_start).total_seconds())
    interval_seconds = int(sample_interval.total_seconds())
    if seconds <= 0 or interval_seconds <= 0:
        return None
    return seconds // interval_seconds


def parse_instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def parse_sample_interval(value: str) -> timedelta:
    if not value.startswith("PT") or not value.endswith("M"):
        raise ValueError(f"Unsupported sample interval: {value}")
    return timedelta(minutes=int(value.removeprefix("PT").removesuffix("M")))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare saved forecast runs for one target and forecast window.")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--target", default=TARGET, choices=("generation", "consumption"))
    parser.add_argument("--forecast-start")
    parser.add_argument("--forecast-end")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--run-limit", type=int, default=RUN_LIMIT)
    parser.add_argument("--point-limit", type=int, default=POINT_LIMIT)
    parser.add_argument("--all-saved", action="store_true", help="Compare all saved runs for the selected target instead of one forecast window.")
    parser.add_argument("--allow-incomplete", action="store_true", help="Plot saved runs even when fewer points are returned than the saved forecast window requires.")
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

    runs = attach_comparison_points(
        args.base_url,
        summaries,
        point_limit=args.point_limit,
        timeout_seconds=TIMEOUT_SECONDS,
        require_complete=not args.allow_incomplete,
    )
    if not runs:
        print("Matching saved forecast runs have no complete comparison points; skipped comparison plot")
        return

    output_path = timestamped_report_path(
        Path(args.output_dir),
        f"{args.target}-{'all-saved-' if args.all_saved else ''}{DEFAULT_OUTPUT.removesuffix('.html')}",
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_comparison_figure(output_path, runs)
    print(f"Wrote {output_path} with {len(runs)} forecast runs")


if __name__ == "__main__":
    main()
