from pathlib import Path
from typing import Iterable

import pandas as pd
import requests


def fetch_forecast_dataframe(
    base_url: str = "http://localhost:8080",
    target: str = "consumption",
    start: str = "2025-06-01T00:00:00Z",
    end: str = "2025-07-20T00:00:00Z",
    timeout_seconds: int = 30,
    include_weather: bool = False,
    weather_path: str | Path | None = None,
    weather_features: Iterable[str] | None = None,
    weather_timezone: str = "Europe/Vienna",
    require_complete_weather: bool = False,
) -> pd.DataFrame:
    if target not in {"consumption", "generation"}:
        raise ValueError("target must be 'consumption' or 'generation'")
    response = requests.get(
        f"{base_url}/api/forecast-datasets",
        params={"target": target, "from": start, "to": end},
        timeout=timeout_seconds,
    )
    response.raise_for_status()

    payload = response.json()
    target_column = payload["targetColumn"]
    data = pd.DataFrame(payload["points"])
    if data.empty:
        data = pd.DataFrame(columns=[target_column], index=pd.DatetimeIndex([], tz="UTC", name="timestamp"))
    else:
        data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True)
        data = data.set_index("timestamp")[[target_column]]

    if include_weather:
        from weather_features import add_weather_features

        data, diagnostics = add_weather_features(
            data,
            path=weather_path,
            requested_features=weather_features,
            source_timezone=weather_timezone,
            require_complete=require_complete_weather,
        )
        data.attrs["weather_diagnostics"] = diagnostics

    return data


def fetch_forecast_dataset(
    base_url: str = "http://localhost:8080",
    target: str = "consumption",
    start: str = "2025-06-01T00:00:00Z",
    end: str = "2025-07-20T00:00:00Z",
    timeout_seconds: int = 30,
    include_weather: bool = False,
    weather_path: str | Path | None = None,
    weather_features: Iterable[str] | None = None,
    weather_timezone: str = "Europe/Vienna",
    require_complete_weather: bool = False,
):
    from datetime import timedelta

    from openstef_core.datasets import TimeSeriesDataset

    return TimeSeriesDataset(
        data=fetch_forecast_dataframe(
            base_url=base_url,
            target=target,
            start=start,
            end=end,
            timeout_seconds=timeout_seconds,
            include_weather=include_weather,
            weather_path=weather_path,
            weather_features=weather_features,
            weather_timezone=weather_timezone,
            require_complete_weather=require_complete_weather,
        ),
        sample_interval=timedelta(minutes=15),
        check_frequency=False,
    )


def save_forecast_run(
    payload: dict,
    base_url: str = "http://localhost:8080",
    timeout_seconds: int = 30,
) -> dict:
    response = requests.post(
        f"{base_url}/api/forecast-runs",
        json=payload,
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    return response.json()
