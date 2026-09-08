from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from forecast_runner import (
    BASE_URL,
    DEFAULT_TRAIN_DAYS,
    OUTPUT_DIR,
    WEATHER_FEATURES,
    format_utc,
    parse_utc,
    require_positive_int,
    timestamped_report_path,
)
from weather_features import DEFAULT_WEATHER_PATH, load_weather_features

DEFAULT_BACKTEST_START = "2025-09-01T00:00:00Z"
DEFAULT_BACKTEST_END = "2026-05-31T22:00:00Z"
DEFAULT_FORECAST_DAYS = 7
DEFAULT_STEP_DAYS = 7
DEFAULT_MODELS = ("weekly-persistence", "openstef-default-xgboost", "openstef-xgboost-tuned")
DEFAULT_TARGETS = ("generation", "consumption")
ENERGY_DATA_START = "2025-05-31T22:00:00Z"
ENERGY_DATA_END = "2026-06-30T22:00:00Z"
JUNE_2026_START = "2026-05-31T22:00:00Z"

MODEL_COMMANDS = {
    "weekly-persistence": ["main.py", "--save"],
    "openstef-default-xgboost": ["default_openstef_xgboost.py"],
    "openstef-xgboost-tuned": ["tuned_openstef.py", "--no-progress"],
    "openstef-lgbm": ["lgbm_openstef.py"],
    "openstef-custom-ensemble": ["custom_openstef.py"],
}
WEATHER_MODELS = {
    "openstef-default-xgboost",
    "openstef-xgboost-tuned",
    "openstef-lgbm",
    "openstef-custom-ensemble",
}


@dataclass(frozen=True)
class RollingWindow:
    train_start: datetime
    train_end: datetime
    forecast_start: datetime
    forecast_end: datetime


@dataclass(frozen=True)
class StepResult:
    target: str
    model: str
    window: RollingWindow
    status: str
    returncode: int
    message: str


def generate_windows(
    *,
    backtest_start: datetime,
    backtest_end: datetime,
    train_days: int,
    forecast_days: int,
    step_days: int,
) -> list[RollingWindow]:
    require_positive_int("train-days", train_days)
    require_positive_int("forecast-days", forecast_days)
    require_positive_int("step-days", step_days)
    windows = []
    forecast_start = backtest_start
    while forecast_start + timedelta(days=forecast_days) <= backtest_end:
        train_start = forecast_start - timedelta(days=train_days)
        windows.append(
            RollingWindow(
                train_start=train_start,
                train_end=forecast_start,
                forecast_start=forecast_start,
                forecast_end=forecast_start + timedelta(days=forecast_days),
            )
        )
        forecast_start += timedelta(days=step_days)
    return windows


def validate_energy_window(window: RollingWindow, *, data_start: datetime, data_end: datetime) -> str | None:
    if window.train_start < data_start:
        return f"train_start {format_utc(window.train_start)} is before imported energy start {format_utc(data_start)}"
    if window.forecast_end > data_end:
        return f"forecast_end {format_utc(window.forecast_end)} is after imported energy end {format_utc(data_end)}"
    return None


def includes_june_2026(window: RollingWindow) -> bool:
    return window.forecast_end > parse_utc(JUNE_2026_START)


def validate_weather_window(window: RollingWindow, *, weather_path: str | Path, features: tuple[str, ...] = WEATHER_FEATURES) -> str | None:
    weather = load_weather_features(path=weather_path, requested_features=features)
    required = expected_index(window.train_start, window.forecast_end)
    missing = required.difference(weather.data.index)
    if not missing.empty:
        examples = ", ".join(timestamp.isoformat().replace("+00:00", "Z") for timestamp in missing[:3])
        return f"missing observed weather intervals={len(missing)} examples={examples}"
    return None


def expected_index(start: datetime, end: datetime):
    import pandas as pd

    return pd.date_range(start, end, freq="15min", inclusive="left")


def parse_csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def filter_valid_windows(windows: list[RollingWindow], *, data_start: datetime, data_end: datetime) -> tuple[list[RollingWindow], list[str]]:
    valid = []
    diagnostics = []
    for window in windows:
        reason = validate_energy_window(window, data_start=data_start, data_end=data_end)
        if reason:
            diagnostics.append(f"skip window {format_window(window)}: {reason}")
        else:
            valid.append(window)
    return valid, diagnostics


def command_for(model: str, *, target: str, window: RollingWindow, base_url: str, train_days: int) -> list[str]:
    if model not in MODEL_COMMANDS:
        raise ValueError(f"Unsupported model for rolling backtest: {model}")
    return [
        sys.executable,
        *MODEL_COMMANDS[model],
        "--base-url",
        base_url,
        "--target",
        target,
        "--train-start",
        format_utc(window.train_start),
        "--train-days",
        str(train_days),
        "--forecast-start",
        format_utc(window.forecast_start),
        "--forecast-days",
        str((window.forecast_end - window.forecast_start).days),
    ]


def run_model_step(model: str, *, target: str, window: RollingWindow, base_url: str, train_days: int) -> StepResult:
    command = command_for(model, target=target, window=window, base_url=base_url, train_days=train_days)
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    message = result.stdout.strip() if result.returncode == 0 else result.stderr.strip() or result.stdout.strip()
    return StepResult(
        target=target,
        model=model,
        window=window,
        status="ok" if result.returncode == 0 else "failed",
        returncode=result.returncode,
        message=message,
    )


def write_run_summary(output_dir: Path, results: list[StepResult], diagnostics: list[str]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = timestamped_report_path(output_dir, "rolling-backtest-summary", suffix=".csv")
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["target", "model", "forecast_start", "forecast_end", "status", "returncode", "message"])
        for result in results:
            writer.writerow([
                result.target,
                result.model,
                format_utc(result.window.forecast_start),
                format_utc(result.window.forecast_end),
                result.status,
                result.returncode,
                result.message,
            ])
        for diagnostic in diagnostics:
            writer.writerow(["", "", "", "", "diagnostic", "", diagnostic])
    return path


def format_window(window: RollingWindow) -> str:
    return f"{format_utc(window.forecast_start)} to {format_utc(window.forecast_end)}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run repeated historical forecast windows for model comparison.")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--target", default="all", choices=("generation", "consumption", "all"))
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS))
    parser.add_argument("--backtest-start", default=DEFAULT_BACKTEST_START)
    parser.add_argument("--backtest-end", default=DEFAULT_BACKTEST_END)
    parser.add_argument("--train-days", type=int, default=DEFAULT_TRAIN_DAYS)
    parser.add_argument("--forecast-days", type=int, default=DEFAULT_FORECAST_DAYS)
    parser.add_argument("--step-days", type=int, default=DEFAULT_STEP_DAYS)
    parser.add_argument("--max-windows", type=int)
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--weather-path", default=str(DEFAULT_WEATHER_PATH))
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    targets = list(DEFAULT_TARGETS) if args.target == "all" else [args.target]
    models = parse_csv_list(args.models)
    windows = generate_windows(
        backtest_start=parse_utc(args.backtest_start),
        backtest_end=parse_utc(args.backtest_end),
        train_days=args.train_days,
        forecast_days=args.forecast_days,
        step_days=args.step_days,
    )
    valid_windows, diagnostics = filter_valid_windows(
        windows,
        data_start=parse_utc(ENERGY_DATA_START),
        data_end=parse_utc(ENERGY_DATA_END),
    )
    if args.max_windows is not None:
        valid_windows = valid_windows[: args.max_windows]
    if not valid_windows:
        raise ValueError("No valid rolling backtest windows selected")

    weather_errors: dict[RollingWindow, str] = {}
    for window in valid_windows:
        if includes_june_2026(window):
            diagnostics.append(f"window includes June 2026 structure-warning period: {format_window(window)}")
        if any(model in WEATHER_MODELS for model in models):
            weather_error = validate_weather_window(window, weather_path=args.weather_path)
            if weather_error:
                weather_errors[window] = weather_error
                diagnostics.append(f"skip weather-dependent models for {format_window(window)}: {weather_error}")

    results = []
    for window in valid_windows:
        for target in targets:
            for model in models:
                if model in WEATHER_MODELS and window in weather_errors:
                    results.append(
                        StepResult(
                            target=target,
                            model=model,
                            window=window,
                            status="skipped",
                            returncode=0,
                            message=weather_errors[window],
                        )
                    )
                    print(f"[rolling-backtest] skipped {target} {model} {format_window(window)}", flush=True)
                    continue
                result = run_model_step(model, target=target, window=window, base_url=args.base_url, train_days=args.train_days)
                results.append(result)
                print(f"[rolling-backtest] {result.status} {target} {model} {format_window(window)}", flush=True)
                if result.returncode != 0 and not args.continue_on_error:
                    write_run_summary(Path(args.output_dir), results, diagnostics)
                    raise SystemExit(result.returncode)

    summary_path = write_run_summary(Path(args.output_dir), results, diagnostics)
    print(f"Wrote rolling backtest summary to {summary_path}")


if __name__ == "__main__":
    main()
