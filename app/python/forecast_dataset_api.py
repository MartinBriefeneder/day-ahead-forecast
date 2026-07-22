from datetime import timedelta

import pandas as pd
import requests
from openstef_core.datasets import TimeSeriesDataset


def fetch_forecast_dataset(
    base_url: str = "http://localhost:8080",
    target: str = "consumption",
    start: str = "2025-06-01T00:00:00Z",
    end: str = "2025-07-20T00:00:00Z",
    timeout_seconds: int = 30,
) -> TimeSeriesDataset:
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

    return TimeSeriesDataset(
        data=data,
        sample_interval=timedelta(minutes=15),
        check_frequency=False,
    )
