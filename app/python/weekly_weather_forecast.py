from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from forecast_dataset_api import fetch_forecast_dataframe
from main import historical_average_forecast, parse_utc_argument
from weather_features import DEFAULT_GRIDOO_LOCATION_ID, align_weather_features, fetch_gridoo_forecast

BASE_URL = "http://localhost:8080"
DEFAULT_TARGET = "generation"
DEFAULT_TRAIN_START = "2025-06-11T00:00:00Z"
DEFAULT_TRAIN_END = "2026-06-01T00:00:00Z"
DEFAULT_FORECAST_START = "2026-08-06T00:00:00Z"
DEFAULT_FORECAST_DAYS = 7
OUTPUT_DIR = (Path(__file__).resolve().parent / "../reports/forecast-runs").resolve()
MODEL_NAME = "weather-statistical-weekly"
SAMPLE_INTERVAL = "15min"
WEATHER_FEATURES = ("temperature_2m", "shortwave_radiation")


def format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def safe_name(value: str) -> str:
    cleaned = "".join(character if character.isalnum() or character in "-_" else "-" for character in value.lower())
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    if not cleaned:
        raise ValueError("Name part must contain at least one letter or number")
    return cleaned


def build_forecast_index(start: datetime, days: int) -> pd.DatetimeIndex:
    if days <= 0:
        raise ValueError("forecast-days must be positive")
    end = start + timedelta(days=days)
    return pd.date_range(start=start, end=end, freq=SAMPLE_INTERVAL, inclusive="left")


def weather_statistical_forecast(
    *,
    target: str,
    train: pd.Series,
    train_weather: pd.DataFrame,
    forecast_weather: pd.DataFrame,
) -> pd.Series:
    train = train.sort_index().dropna()
    if train.empty:
        raise ValueError("Training energy data is empty")
    if target == "generation":
        return generation_forecast(train, train_weather, forecast_weather)
    if target == "consumption":
        return consumption_forecast(train, train_weather, forecast_weather)
    raise ValueError("target must be 'generation' or 'consumption'")


def generation_forecast(train: pd.Series, train_weather: pd.DataFrame, forecast_weather: pd.DataFrame) -> pd.Series:
    frame = pd.DataFrame({"energy": train, "radiation": train_weather["shortwave_radiation"]}).dropna()
    sun = frame[frame["radiation"] > 20].copy()
    if sun.empty:
        return historical_average_forecast(train, forecast_weather.index).clip(lower=0)

    sun["slot"] = slot_key(sun.index)
    sun["yield_per_radiation"] = sun["energy"] / sun["radiation"]
    by_slot = sun.groupby("slot")["yield_per_radiation"].median()
    fallback = float(sun["yield_per_radiation"].median())

    values = []
    for timestamp, row in forecast_weather.iterrows():
        radiation = float(row["shortwave_radiation"])
        if radiation <= 10:
            values.append(0.0)
        else:
            factor = by_slot.get(slot_key(pd.DatetimeIndex([timestamp]))[0], fallback)
            values.append(max(0.0, radiation * float(factor)))
    return pd.Series(values, index=forecast_weather.index, name="forecast_kwh")


def consumption_forecast(train: pd.Series, train_weather: pd.DataFrame, forecast_weather: pd.DataFrame) -> pd.Series:
    baseline = historical_average_forecast(train, forecast_weather.index)
    train_baseline = historical_average_forecast(train, train.index)
    frame = pd.DataFrame(
        {
            "actual": train,
            "baseline": train_baseline,
            "temperature": train_weather["temperature_2m"],
        }
    ).dropna()
    if frame.empty or frame["temperature"].var() == 0:
        return baseline.clip(lower=0)

    frame["slot"] = slot_key(frame.index)
    slot_temperature = frame.groupby("slot")["temperature"].mean()
    slope = float(frame["temperature"].cov(frame["actual"] - frame["baseline"]) / frame["temperature"].var())

    values = []
    for timestamp, base_value in baseline.items():
        temperature = float(forecast_weather.loc[timestamp, "temperature_2m"])
        normal_temperature = float(slot_temperature.get(slot_key(pd.DatetimeIndex([timestamp]))[0], frame["temperature"].mean()))
        values.append(max(0.0, float(base_value) + slope * (temperature - normal_temperature)))
    return pd.Series(values, index=forecast_weather.index, name="forecast_kwh")


def slot_key(index: pd.DatetimeIndex) -> pd.Index:
    return pd.Index(index.strftime("%w %H:%M"))


def daily_totals(series: pd.Series) -> pd.Series:
    return series.resample("1D").sum()


def complete_training_data(training: pd.DataFrame, *, target: str, weather_features: tuple[str, ...]) -> pd.DataFrame:
    required_columns = [target, *weather_features]
    complete = training.dropna(subset=required_columns)
    if complete.empty:
        raise ValueError("Training dataset has no rows with complete energy and historical weather data.")
    return complete


def write_plotly_html(
    *,
    output_dir: Path,
    target: str,
    forecast: pd.Series,
    forecast_weather: pd.DataFrame,
    metadata: dict[str, Any],
) -> Path:
    from plotly import graph_objects as go
    from plotly.subplots import make_subplots

    output_dir.mkdir(parents=True, exist_ok=True)
    forecast_start = pd.Timestamp(forecast.index.min()).strftime("%Y%m%d")
    forecast_end = pd.Timestamp(metadata["forecastEnd"]).strftime("%Y%m%d")
    output_path = output_dir / f"{safe_name(target)}-{MODEL_NAME}-{forecast_start}-{forecast_end}.html"
    target_label = target.capitalize()

    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        subplot_titles=(
            f"Forecast {target_label}",
            "Gridoo weather forecast inputs",
            "Daily expected energy totals",
        ),
        specs=[[{"secondary_y": False}], [{"secondary_y": True}], [{"secondary_y": False}]],
    )
    fig.add_trace(
        go.Scatter(
            x=forecast.index,
            y=forecast.values,
            mode="lines",
            name="Forecast kWh",
            line={"width": 2},
            hovertemplate="%{x|%Y-%m-%d %H:%M UTC}<br>%{y:.3f} kWh<extra></extra>",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=forecast_weather.index,
            y=forecast_weather["shortwave_radiation"],
            mode="lines",
            name="Shortwave radiation W/m2",
            line={"color": "#f59e0b"},
            hovertemplate="%{x|%Y-%m-%d %H:%M UTC}<br>%{y:.1f} W/m2<extra></extra>",
        ),
        row=2,
        col=1,
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=forecast_weather.index,
            y=forecast_weather["temperature_2m"],
            mode="lines",
            name="Temperature degC",
            line={"color": "#dc2626"},
            hovertemplate="%{x|%Y-%m-%d %H:%M UTC}<br>%{y:.1f} degC<extra></extra>",
        ),
        row=2,
        col=1,
        secondary_y=True,
    )
    totals = daily_totals(forecast)
    fig.add_trace(
        go.Bar(
            x=totals.index,
            y=totals.values,
            name="Daily kWh",
            hovertemplate="%{x|%Y-%m-%d}<br>%{y:.2f} kWh<extra></extra>",
        ),
        row=3,
        col=1,
    )
    fig.update_yaxes(title_text="kWh per 15-minute interval", row=1, col=1)
    fig.update_yaxes(title_text="W/m2", row=2, col=1, secondary_y=False)
    fig.update_yaxes(title_text="degC", row=2, col=1, secondary_y=True)
    fig.update_yaxes(title_text="kWh per day", row=3, col=1)
    fig.update_xaxes(tickformat="%Y-%m-%d\n%H:%M", row=1, col=1)
    fig.update_xaxes(tickformat="%Y-%m-%d\n%H:%M", row=2, col=1)
    fig.update_xaxes(title_text="Day (UTC)", tickformat="%Y-%m-%d", row=3, col=1)
    fig.update_layout(
        title=f"{target_label} Weekly Forecast From Historical Statistics And Weather Forecast",
        hovermode="x unified",
        template="plotly_white",
        height=900,
        annotations=list(fig.layout.annotations)
        + [
            {
                "text": (
                    f"Model: {MODEL_NAME}<br>Train: {metadata['trainStart']} to {metadata['trainEnd']}<br>"
                    f"Weather: Gridoo forecast for location {metadata['weatherLocationId']}"
                ),
                "xref": "paper",
                "yref": "paper",
                "x": 0,
                "y": -0.12,
                "showarrow": False,
                "align": "left",
            }
        ],
        margin={"b": 120},
    )
    fig.write_html(output_path, include_plotlyjs=True)
    return output_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a future weekly energy forecast Plotly HTML file.")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--target", default=DEFAULT_TARGET, choices=("generation", "consumption"))
    parser.add_argument("--train-start", default=DEFAULT_TRAIN_START)
    parser.add_argument("--train-end", default=DEFAULT_TRAIN_END)
    parser.add_argument("--forecast-start", default=DEFAULT_FORECAST_START)
    parser.add_argument("--forecast-days", type=int, default=DEFAULT_FORECAST_DAYS)
    parser.add_argument("--weather-location-id", type=int, default=DEFAULT_GRIDOO_LOCATION_ID)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    train_start = parse_utc_argument(args.train_start)
    train_end = parse_utc_argument(args.train_end)
    forecast_start = parse_utc_argument(args.forecast_start)
    forecast_index = build_forecast_index(forecast_start, args.forecast_days)
    forecast_end = forecast_index[-1].to_pydatetime() + timedelta(minutes=15)

    if train_end <= train_start:
        raise ValueError("train-end must be after train-start")

    training = fetch_forecast_dataframe(
        base_url=args.base_url,
        target=args.target,
        start=format_utc(train_start),
        end=format_utc(train_end),
        include_weather=True,
        weather_features=WEATHER_FEATURES,
        require_complete_weather=False,
    )
    if training.empty:
        raise ValueError("Training dataset is empty. Check imported historical energy data and historical weather data.")
    complete_training = complete_training_data(training, target=args.target, weather_features=WEATHER_FEATURES)
    weather_diagnostics = training.attrs.get("weather_diagnostics", {})
    missing_weather_count = weather_diagnostics.get("alignment", {}).get("missingWeatherIntervalCount", 0)
    if missing_weather_count:
        print(f"Warning: dropped {len(training) - len(complete_training):,} training rows with incomplete historical weather data.")

    weather = fetch_gridoo_forecast(
        start=forecast_start,
        end=forecast_end,
        location_id=args.weather_location_id,
        requested_features=WEATHER_FEATURES,
    )
    forecast_weather, weather_alignment = align_weather_features(
        weather,
        forecast_index,
        requested_features=WEATHER_FEATURES,
        require_complete=True,
    )
    forecast = weather_statistical_forecast(
        target=args.target,
        train=complete_training[args.target],
        train_weather=complete_training[list(WEATHER_FEATURES)],
        forecast_weather=forecast_weather,
    )

    metadata = {
        "generatedAt": format_utc(datetime.now(timezone.utc)),
        "target": args.target,
        "model": MODEL_NAME,
        "trainStart": format_utc(train_start),
        "trainEnd": format_utc(train_end),
        "forecastStart": format_utc(forecast_start),
        "forecastEnd": format_utc(forecast_end),
        "sampleInterval": "PT15M",
        "weatherProvider": "Gridoo Weather API",
        "weatherLocationId": args.weather_location_id,
        "forecastWeatherSource": weather.metadata,
        "historicalWeatherAlignment": weather_diagnostics.get("alignment", {}),
        "trainingRows": int(len(training)),
        "completeTrainingRows": int(len(complete_training)),
        "weatherAlignment": weather_alignment,
    }
    output_path = write_plotly_html(
        output_dir=Path(args.output_dir),
        target=args.target,
        forecast=forecast,
        forecast_weather=forecast_weather,
        metadata=metadata,
    )
    print(f"Wrote weekly weather forecast plot to {output_path}")
    print(f"Total forecast energy: {forecast.sum():.2f} kWh")


if __name__ == "__main__":
    main()
