import unittest
from unittest.mock import patch

import pandas as pd

from weather_features import (
    WeatherFeatureDataset,
    add_weather_features,
    align_weather_features,
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


if __name__ == "__main__":
    unittest.main()
