import unittest

from forecast_runner import resolve_forecast_window


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


if __name__ == "__main__":
    unittest.main()
