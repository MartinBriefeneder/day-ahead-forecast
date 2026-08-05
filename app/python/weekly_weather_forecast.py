from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from barebones_openstef import WEATHER_FEATURES
from forecast_dataset_api import fetch_forecast_dataframe
from main import historical_average_forecast, parse_utc_argument
from weather_features import align_weather_features, fetch_open_meteo_forecast

BASE_URL = "http://localhost:8080"
DEFAULT_TARGET = "generation"
DEFAULT_TRAIN_START = "2025-06-11T00:00:00Z"
DEFAULT_TRAIN_END = "2026-06-01T00:00:00Z"
DEFAULT_FORECAST_START = "2026-08-06T00:00:00Z"
DEFAULT_FORECAST_DAYS = 7
DEFAULT_LATITUDE = 47.9056
DEFAULT_LONGITUDE = 14.1223
OUTPUT_DIR = (Path(__file__).resolve().parent / "../reports/forecast-runs").resolve()
MODEL_NAME = "weather-statistical-weekly"
SAMPLE_INTERVAL = "15min"


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
            "Upcoming weather forecast",
            "Daily expected energy totals",
        ),
        specs=[[{"secondary_y": False}], [{"secondary_y": True}], [{"secondary_y": False}]],
    )
    fig.add_trace(
        go.Scatter(x=forecast.index, y=forecast.values, mode="lines", name="Forecast kWh", line={"width": 2}),
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
        ),
        row=2,
        col=1,
        secondary_y=True,
    )
    totals = daily_totals(forecast)
    fig.add_trace(go.Bar(x=totals.index, y=totals.values, name="Daily kWh"), row=3, col=1)
    fig.update_yaxes(title_text="kWh per 15-minute interval", row=1, col=1)
    fig.update_yaxes(title_text="W/m2", row=2, col=1, secondary_y=False)
    fig.update_yaxes(title_text="degC", row=2, col=1, secondary_y=True)
    fig.update_yaxes(title_text="kWh per day", row=3, col=1)
    fig.update_layout(
        title=f"{target_label} Weekly Forecast From Historical Statistics And Weather Forecast",
        xaxis_title="Time (UTC)",
        hovermode="x unified",
        template="plotly_white",
        height=900,
        annotations=list(fig.layout.annotations)
        + [
            {
                "text": (
                    f"Model: {MODEL_NAME}<br>Train: {metadata['trainStart']} to {metadata['trainEnd']}<br>"
                    f"Weather: Open-Meteo forecast at {metadata['latitude']}, {metadata['longitude']}"
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
    parser.add_argument("--latitude", type=float, default=DEFAULT_LATITUDE)
    parser.add_argument("--longitude", type=float, default=DEFAULT_LONGITUDE)
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
        require_complete_weather=True,
    )
    if training.empty:
        raise ValueError("Training dataset is empty. Check imported historical energy data and historical weather data.")

    weather = fetch_open_meteo_forecast(
        latitude=args.latitude,
        longitude=args.longitude,
        start=forecast_start,
        end=forecast_end,
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
        train=training[args.target],
        train_weather=training[list(WEATHER_FEATURES)],
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
        "latitude": args.latitude,
        "longitude": args.longitude,
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
