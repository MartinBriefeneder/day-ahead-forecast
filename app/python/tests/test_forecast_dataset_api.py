import unittest
from unittest.mock import patch

import pandas as pd
import requests

from forecast_dataset_api import DEFAULT_TIMEOUT_SECONDS, fetch_forecast_dataframe


class StubResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def api_payload() -> dict:
    return {
        "targetColumn": "consumption",
        "points": [
            {
                "timestamp": "2025-06-11T00:00:00Z",
                "consumption": 1.25,
            }
        ],
    }


class ForecastDatasetApiTest(unittest.TestCase):
    def test_fetch_dataframe_stays_energy_only_by_default(self):
        with patch("forecast_dataset_api.requests.get", return_value=StubResponse(api_payload())) as get:
            data = fetch_forecast_dataframe()

        self.assertEqual(["consumption"], list(data.columns))
        self.assertEqual(pd.Timestamp("2025-06-11T00:00:00Z"), data.index[0])
        self.assertNotIn("weather_diagnostics", data.attrs)
        self.assertEqual(DEFAULT_TIMEOUT_SECONDS, get.call_args.kwargs["timeout"])

    def test_fetch_dataframe_adds_weather_only_when_requested(self):
        def add_weather(data, **kwargs):
            result = data.copy()
            result["temperature_2m"] = 12.0
            return result, {"alignment": {"alignedWeatherIntervalCount": len(result)}}

        with patch("forecast_dataset_api.requests.get", return_value=StubResponse(api_payload())):
            with patch("weather_features.add_weather_features", side_effect=add_weather):
                data = fetch_forecast_dataframe(include_weather=True, weather_features=["temperature_2m"])

        self.assertEqual(["consumption", "temperature_2m"], list(data.columns))
        self.assertEqual(12.0, data["temperature_2m"].iloc[0])
        self.assertEqual(1, data.attrs["weather_diagnostics"]["alignment"]["alignedWeatherIntervalCount"])

    def test_fetch_dataframe_reports_backend_connection_failure(self):
        with patch("forecast_dataset_api.requests.get", side_effect=requests.ConnectionError("refused")):
            with self.assertRaisesRegex(ConnectionError, "Start it from app/ with ./run-server.sh or ./run-dev.sh"):
                fetch_forecast_dataframe()


if __name__ == "__main__":
    unittest.main()
