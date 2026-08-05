import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from main import build_parser, resolve_windows, write_reports


class MainBacktestReportTest(unittest.TestCase):
    def test_write_reports_creates_plotly_backtest_dashboard(self):
        index = pd.date_range("2025-09-09T00:00:00Z", periods=4, freq="15min")
        actual = pd.Series([1.0, 1.1, 1.2, 1.3], index=index, name="consumption")
        payloads = [
            {
                "runId": "consumption-historical-average-20250909T000000Z",
                "model": "historical-average",
                "target": "consumption",
                "generatedAt": "2025-09-08T00:00:00Z",
                "trainStart": "2025-09-08T00:00:00Z",
                "forecastStart": "2025-09-09T00:00:00Z",
                "forecastEnd": "2025-09-09T01:00:00Z",
                "sampleInterval": "PT15M",
                "horizon": "P7D",
                "metrics": {
                    "aligned_intervals": 4,
                    "mae_kwh": 0.1,
                    "rmse_kwh": 0.1,
                    "bias_kwh": 0.1,
                    "total_energy_error_kwh": 0.4,
                    "mean_abs_daily_energy_error_kwh": 0.4,
                },
                "points": [
                    {
                        "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
                        "forecastKwh": value + 0.1,
                        "actualKwh": value,
                        "errorKwh": 0.1,
                    }
                    for timestamp, value in actual.items()
                ],
            }
        ]

        with TemporaryDirectory() as directory:
            output_dir = Path(directory)
            dashboard_path = write_reports(output_dir, payloads, actual)
            dashboard = (output_dir / "forecast-backtest-dashboard.html").read_text(encoding="utf-8")

        self.assertEqual("forecast-backtest-dashboard.html", dashboard_path.name)
        self.assertIn("Consumption Forecast Dashboard", dashboard)
        self.assertIn("Expected Energy Totals", dashboard)
        self.assertIn("Actuals and forecasts", dashboard)
        self.assertIn("Interval error", dashboard)
        self.assertIn("historical-average", dashboard)

    def test_parser_does_not_accept_no_save(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["--no-save"])

    def test_forecast_start_defaults_training_window_to_previous_train_days(self):
        args = build_parser().parse_args([
            "--forecast-start",
            "2026-08-05T00:00:00Z",
            "--train-days",
            "90",
            "--forecast-weeks",
            "1",
        ])

        train_start, forecast_start, forecast_end, horizon = resolve_windows(args)

        self.assertEqual("2026-05-07T00:00:00+00:00", train_start.isoformat())
        self.assertEqual("2026-08-05T00:00:00+00:00", forecast_start.isoformat())
        self.assertEqual("2026-08-12T00:00:00+00:00", forecast_end.isoformat())
        self.assertEqual(7, horizon.days)

if __name__ == "__main__":
    unittest.main()
