from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests


BASE_URL = "http://localhost:8080"
OUTPUT_DIR = (Path(__file__).resolve().parent / "../reports/forecast-runs").resolve()
DEFAULT_OUTPUT = "all-python-forecast-comparison.html"
TARGET = "generation"
RUN_LIMIT = 100
POINT_LIMIT = 10000
TIMEOUT_SECONDS = 120


def fetch_run_summaries(base_url: str, *, target: str | None, limit: int, timeout_seconds: int) -> list[dict[str, Any]]:
    params: dict[str, str | int] = {"limit": limit}
    if target is not None:
        params["target"] = target
    response = requests.get(f"{base_url}/api/forecast-runs", params=params, timeout=timeout_seconds)
    response.raise_for_status()
    return response.json()


def fetch_comparison(base_url: str, run_id: str, *, limit: int, timeout_seconds: int) -> list[dict[str, Any]]:
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
) -> list[dict[str, Any]]:
    selected = [
        summary
        for summary in summaries
        if (target is None or summary.get("target") == target)
        and (forecast_start is None or summary.get("forecastStart") == forecast_start)
        and (forecast_end is None or summary.get("forecastEnd") == forecast_end)
    ]
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
    timeout_seconds: int,
) -> list[dict[str, Any]]:
    runs = []
    for summary in summaries:
        run = dict(summary)
        run["points"] = fetch_comparison(base_url, summary["runId"], limit=point_limit, timeout_seconds=timeout_seconds)
        if run["points"]:
            runs.append(run)
    return runs


def write_comparison_figure(output_path: Path, runs: list[dict[str, Any]]) -> None:
    from plotly import graph_objects as go

    first = runs[0]
    target_label = str(first["target"]).capitalize()
    fig = go.Figure()

    actual_run = next((run for run in runs if any(point.get("actualKwh") is not None for point in run["points"])), first)
    actual_points = actual_run["points"]
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

    for run in sorted(runs, key=lambda item: str(item.get("model"))):
        fig.add_trace(
            go.Scatter(
                x=[point["timestamp"] for point in run["points"]],
                y=[point.get("forecastKwh") for point in run["points"]],
                mode="lines",
                name=str(run.get("model")),
            )
        )

    fig.update_layout(
        title=f"Python {target_label} Forecast Comparison<br><sup>{first['forecastStart']} to {first['forecastEnd']} ({first['sampleInterval']})</sup>",
        xaxis_title="Time (UTC)",
        yaxis_title=f"{target_label} energy (kWh per interval)",
        hovermode="x unified",
        template="plotly_white",
        height=620,
    )
    fig.write_html(output_path, include_plotlyjs=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare saved forecast runs for one target and forecast window.")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--target", default=TARGET, choices=("generation", "consumption"))
    parser.add_argument("--forecast-start")
    parser.add_argument("--forecast-end")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--run-limit", type=int, default=RUN_LIMIT)
    parser.add_argument("--point-limit", type=int, default=POINT_LIMIT)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    summaries = select_summaries(
        fetch_run_summaries(args.base_url, target=args.target, limit=args.run_limit, timeout_seconds=TIMEOUT_SECONDS),
        target=args.target,
        forecast_start=args.forecast_start,
        forecast_end=args.forecast_end,
    )
    if not summaries:
        raise ValueError("No matching saved forecast runs found")

    runs = attach_comparison_points(args.base_url, summaries, point_limit=args.point_limit, timeout_seconds=TIMEOUT_SECONDS)
    if not runs:
        print("Matching saved forecast runs have no comparison points; skipped comparison plot")
        return

    output_path = Path(args.output_dir) / f"{args.target}-{DEFAULT_OUTPUT}"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_comparison_figure(output_path, runs)
    print(f"Wrote {output_path} with {len(runs)} forecast runs")


if __name__ == "__main__":
    main()
