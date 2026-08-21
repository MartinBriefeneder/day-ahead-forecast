import unittest

import pandas as pd

from forecast_runner import FORECAST_WEATHER_FEATURES, metric_items, none_if_nan, openstef_weather_config_kwargs, resolve_forecast_window


class ForecastRunnerTest(unittest.TestCase):
    def test_resolve_forecast_window_uses_explicit_forecast_start(self):
        train_start, train_end, forecast_start, forecast_end = resolve_forecast_window(
            train_start=None,
            train_days=90,
            forecast_start="2025-10-01T00:00:00Z",
            forecast_days=7,
        )

        self.assertEqual("2025-07-03T00:00:00+00:00", train_start.isoformat())
        self.assertEqual("2025-10-01T00:00:00+00:00", train_end.isoformat())
        self.assertEqual("2025-10-01T00:00:00+00:00", forecast_start.isoformat())
        self.assertEqual("2025-10-08T00:00:00+00:00", forecast_end.isoformat())

    def test_resolve_forecast_window_preserves_legacy_default(self):
        train_start, train_end, forecast_start, forecast_end = resolve_forecast_window(
            train_start=None,
            train_days=90,
            forecast_start=None,
            forecast_days=7,
        )

        self.assertEqual("2025-06-11T00:00:00+00:00", train_start.isoformat())
        self.assertEqual("2025-09-09T00:00:00+00:00", train_end.isoformat())
        self.assertEqual("2025-09-09T00:00:00+00:00", forecast_start.isoformat())
        self.assertEqual("2025-09-16T00:00:00+00:00", forecast_end.isoformat())

    def test_resolve_forecast_window_uses_default_training_data_for_future_start(self):
        train_start, train_end, forecast_start, forecast_end = resolve_forecast_window(
            train_start=None,
            train_days=90,
            forecast_start="2099-01-01T00:00:00Z",
            forecast_days=7,
        )

        self.assertEqual("2025-06-11T00:00:00+00:00", train_start.isoformat())
        self.assertEqual("2025-09-09T00:00:00+00:00", train_end.isoformat())
        self.assertEqual("2099-01-01T00:00:00+00:00", forecast_start.isoformat())
        self.assertEqual("2099-01-08T00:00:00+00:00", forecast_end.isoformat())

    def test_openstef_weather_config_accepts_forecast_weather_subset(self):
        self.assertEqual(
            {
                "temperature_column": "temperature_2m",
                "wind_speed_column": "wind_speed_10m",
                "radiation_column": "shortwave_radiation",
            },
            openstef_weather_config_kwargs(FORECAST_WEATHER_FEATURES),
        )

    def test_none_if_nan_handles_pandas_missing_values(self):
        self.assertIsNone(none_if_nan(pd.NA))

    def test_metric_items_skips_pandas_missing_values(self):
        self.assertEqual(
            [{"name": "mae_kwh", "value": 0.5}],
            metric_items({"mae_kwh": 0.5, "missing": pd.NA, "note": "ignored"}),
        )


if __name__ == "__main__":
    unittest.main()
