import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from weekly_weather_forecast import (
    build_forecast_index,
    complete_training_data,
    generation_forecast,
    weather_statistical_forecast,
    write_plotly_html,
)


class WeeklyWeatherForecastTest(unittest.TestCase):
    def test_build_forecast_index_uses_quarter_hours_and_left_closed_end(self):
        index = build_forecast_index(datetime(2026, 8, 6, tzinfo=timezone.utc), 1)

        self.assertEqual(96, len(index))
        self.assertEqual(pd.Timestamp("2026-08-06T00:00:00Z"), index[0])
        self.assertEqual(pd.Timestamp("2026-08-06T23:45:00Z"), index[-1])

    def test_generation_forecast_scales_by_upcoming_radiation(self):
        train_index = pd.date_range("2026-07-30T12:00:00Z", periods=2, freq="15min")
        forecast_index = pd.date_range("2026-08-06T12:00:00Z", periods=2, freq="15min")
        train = pd.Series([2.0, 4.0], index=train_index)
        train_weather = pd.DataFrame({"shortwave_radiation": [400.0, 800.0]}, index=train_index)
        forecast_weather = pd.DataFrame({"shortwave_radiation": [500.0, 0.0]}, index=forecast_index)

        forecast = generation_forecast(train, train_weather, forecast_weather)

        self.assertEqual([2.5, 0.0], list(forecast))

    def test_weather_statistical_forecast_rejects_unknown_target(self):
        index = pd.date_range("2026-08-06T00:00:00Z", periods=1, freq="15min")
        with self.assertRaisesRegex(ValueError, "target must be"):
            weather_statistical_forecast(
                target="net",
                train=pd.Series([1.0], index=index),
                train_weather=pd.DataFrame({"shortwave_radiation": [1.0]}, index=index),
                forecast_weather=pd.DataFrame({"shortwave_radiation": [1.0]}, index=index),
            )

    def test_complete_training_data_drops_missing_historical_weather_rows(self):
        index = pd.date_range("2025-10-26T00:00:00Z", periods=3, freq="15min")
        training = pd.DataFrame(
            {
                "generation": [1.0, 2.0, 3.0],
                "temperature_2m": [10.0, None, 12.0],
                "shortwave_radiation": [0.0, 0.0, 5.0],
            },
            index=index,
        )

        complete = complete_training_data(
            training,
            target="generation",
            weather_features=("temperature_2m", "shortwave_radiation"),
        )

        self.assertEqual([index[0], index[2]], list(complete.index))

    def test_complete_training_data_rejects_fully_incomplete_training_data(self):
        index = pd.date_range("2025-10-26T00:00:00Z", periods=1, freq="15min")
        training = pd.DataFrame({"generation": [1.0], "temperature_2m": [None]}, index=index)

        with self.assertRaisesRegex(ValueError, "no rows with complete"):
            complete_training_data(training, target="generation", weather_features=("temperature_2m",))

    def test_write_plotly_html_writes_named_report(self):
        index = pd.date_range("2026-08-06T00:00:00Z", periods=1, freq="15min")
        forecast = pd.Series([1.0], index=index)
        weather = pd.DataFrame({"shortwave_radiation": [10.0], "temperature_2m": [20.0]}, index=index)
        metadata = {
            "trainStart": "2025-06-11T00:00:00Z",
            "trainEnd": "2026-06-01T00:00:00Z",
            "forecastEnd": "2026-08-06T00:15:00Z",
            "weatherLocationId": 4,
        }

        with tempfile.TemporaryDirectory() as directory:
            path = write_plotly_html(
                output_dir=Path(directory),
                target="generation",
                forecast=forecast,
                forecast_weather=weather,
                metadata=metadata,
            )

            self.assertEqual("generation-weather-statistical-weekly-20260806-20260806.html", path.name)
            self.assertIn("Weekly Forecast", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
