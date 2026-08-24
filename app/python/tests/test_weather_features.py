import unittest
from unittest.mock import patch

import pandas as pd
import requests

from weather_features import (
    WeatherFeatureDataset,
    add_weather_features,
    align_weather_features,
    fetch_gridoo_forecast,
    inspect_weather_frame,
    normalize_weather_features,
)


def weather_frame(timestamps: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "all_sky_global_horizontal_irradiance": range(len(timestamps)),
            "2m_temperature": [10.0 + index for index in range(len(timestamps))],
            "2m_relative_humidity": [70.0] * len(timestamps),
            "10m_wind_speed": [2.0] * len(timestamps),
            "surface_pressure": [950.0] * len(timestamps),
        }
    )


class WeatherFeaturesTest(unittest.TestCase):
    def test_normalizes_source_columns_to_utc_weather_features(self):
        dataset = normalize_weather_features(weather_frame(["2025-06-11T00:00:00", "2025-06-11T00:15:00"]))

        self.assertEqual(
            [
                "shortwave_radiation",
                "temperature_2m",
                "relative_humidity_2m",
                "wind_speed_10m",
                "surface_pressure",
            ],
            list(dataset.data.columns),
        )
        self.assertEqual("UTC", str(dataset.data.index.tz))
        self.assertEqual(pd.Timestamp("2025-06-10T22:00:00Z"), dataset.data.index[0])

    def test_reports_duplicate_and_missing_local_timestamps(self):
        metadata = inspect_weather_frame(
            weather_frame(
                [
                    "2025-06-11T00:00:00",
                    "2025-06-11T00:15:00",
                    "2025-06-11T00:15:00",
                    "2025-06-11T00:45:00",
                ]
            )
        )

        self.assertEqual(2, metadata["duplicateTimestampCount"])
        self.assertEqual(1, metadata["missingTimestampCount"])
        self.assertEqual(["2025-06-11T00:30:00"], metadata["missingTimestampExamples"])

    def test_reports_dst_rows_without_guessing(self):
        metadata = inspect_weather_frame(
            weather_frame(
                [
                    "2025-10-26T02:00:00",
                    "2026-03-29T02:00:00",
                ]
            )
        )

        self.assertEqual(1, metadata["ambiguousDstTimestampCount"])
        self.assertEqual(1, metadata["nonexistentDstTimestampCount"])

    def test_alignment_keeps_energy_index_and_reports_missing_weather(self):
        weather = normalize_weather_features(weather_frame(["2025-06-11T00:00:00"]))
        energy_index = pd.date_range("2025-06-10T22:00:00Z", periods=2, freq="15min")

        aligned, diagnostics = align_weather_features(weather, energy_index)

        self.assertEqual(list(energy_index), list(aligned.index))
        self.assertEqual(1, diagnostics["alignedWeatherIntervalCount"])
        self.assertEqual(1, diagnostics["missingWeatherIntervalCount"])

    def test_add_weather_features_fails_for_unknown_feature(self):
        energy = pd.DataFrame({"consumption": [1.0]}, index=pd.date_range("2025-06-10T22:00:00Z", periods=1))

        with self.assertRaisesRegex(ValueError, "Unsupported weather feature"):
            add_weather_features(energy, requested_features=["cloud_magic"])

    def test_add_weather_features_attaches_alignment_diagnostics(self):
        index = pd.date_range("2025-06-10T22:00:00Z", periods=1)
        energy = pd.DataFrame({"consumption": [1.0]}, index=index)
        weather = WeatherFeatureDataset(
            data=pd.DataFrame({"temperature_2m": [12.0]}, index=index),
            metadata={"sourcePath": "synthetic"},
        )

        with patch("weather_features.load_weather_features", return_value=weather):
            result, diagnostics = add_weather_features(energy, requested_features=["temperature_2m"])

        self.assertEqual(["consumption", "temperature_2m"], list(result.columns))
        self.assertEqual(12.0, result.loc[index[0], "temperature_2m"])
        self.assertEqual(1, diagnostics["alignment"]["alignedWeatherIntervalCount"])
        self.assertIn("weather_diagnostics", result.attrs)

    def test_fetch_gridoo_forecast_maps_response_fields(self):
        payload = [
            {
                "timestamp": 1785974400,
                "timestamp_iso": "2026-08-06T00:00:00Z",
                "ghi": 0.0,
                "dni": 0.0,
                "dhi": 0.0,
                "temperature": 17.0,
                "windspeed": 1.5,
                "winddirection": 42.0,
            },
            {
                "timestamp": 1785975300,
                "timestamp_iso": "2026-08-06T00:15:00Z",
                "ghi": 5.0,
                "dni": 10.0,
                "dhi": 2.0,
                "temperature": 17.5,
                "windspeed": 1.6,
                "winddirection": 43.0,
            },
        ]

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return payload

        with patch("weather_features.requests.get", return_value=Response()) as get:
            dataset = fetch_gridoo_forecast(
                start=pd.Timestamp("2026-08-06T00:00:00Z").to_pydatetime(),
                end=pd.Timestamp("2026-08-06T00:30:00Z").to_pydatetime(),
                requested_features=[
                    "temperature_2m",
                    "shortwave_radiation",
                    "direct_normal_irradiance",
                    "diffuse_horizontal_irradiance",
                    "wind_speed_10m",
                    "wind_direction_10m",
                ],
            )

        self.assertEqual(
            [
                "temperature_2m",
                "shortwave_radiation",
                "direct_normal_irradiance",
                "diffuse_horizontal_irradiance",
                "wind_speed_10m",
                "wind_direction_10m",
            ],
            list(dataset.data.columns),
        )
        self.assertEqual(pd.Timestamp("2026-08-06T00:00:00Z"), dataset.data.index[0])
        self.assertEqual(5.0, dataset.data.loc[pd.Timestamp("2026-08-06T00:15:00Z"), "shortwave_radiation"])
        self.assertEqual(10.0, dataset.data.loc[pd.Timestamp("2026-08-06T00:15:00Z"), "direct_normal_irradiance"])
        self.assertEqual(2, dataset.metadata["intervalCount"])
        self.assertEqual(1785974400, get.call_args.kwargs["params"]["start"])
        self.assertEqual(1785976200, get.call_args.kwargs["params"]["end"])
        self.assertIn("/weather/4", get.call_args.args[0])

    def test_fetch_gridoo_forecast_retries_connection_errors(self):
        payload = [
            {
                "timestamp_iso": "2026-08-06T00:00:00Z",
                "temperature": 17.0,
            }
        ]

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return payload

        with patch("weather_features.requests.get", side_effect=[requests.ConnectionError("dns"), Response()]) as get:
            dataset = fetch_gridoo_forecast(
                start=pd.Timestamp("2026-08-06T00:00:00Z").to_pydatetime(),
                end=pd.Timestamp("2026-08-06T00:15:00Z").to_pydatetime(),
                requested_features=["temperature_2m"],
                retry_delay_seconds=0,
            )

        self.assertEqual(2, get.call_count)
        self.assertEqual(17.0, dataset.data.loc[pd.Timestamp("2026-08-06T00:00:00Z"), "temperature_2m"])


if __name__ == "__main__":
    unittest.main()
