import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from main import backend_payload, build_parser, write_reports


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
            write_reports(output_dir, payloads, actual)
            dashboard = (output_dir / "forecast-backtest-dashboard.html").read_text(encoding="utf-8")
            markdown = (output_dir / "forecast-backtest-report.md").read_text(encoding="utf-8")

        self.assertIn("Consumption Backtest Dashboard", dashboard)
        self.assertIn("Actuals and forecasts", dashboard)
        self.assertIn("Interval error", dashboard)
        self.assertIn("historical-average", dashboard)
        self.assertIn("forecast-backtest-dashboard.html", markdown)

    def test_backend_payload_uses_backend_metric_list_shape(self):
        payload = {
            "runId": "run-1",
            "model": "historical-average",
            "target": "consumption",
            "modelFamily": "simple-benchmark",
            "generatedAt": "2026-01-01T00:00:00Z",
            "trainStart": "2025-11-01T00:00:00Z",
            "trainEnd": "2025-12-01T00:00:00Z",
            "forecastStart": "2025-12-01T00:00:00Z",
            "forecastEnd": "2025-12-02T00:00:00Z",
            "sampleInterval": "PT15M",
            "reportPath": "app/reports/forecast-runs/forecast-backtest-report.md",
            "points": [
                {
                    "timestamp": "2025-12-01T00:00:00Z",
                    "forecastKwh": 12.5,
                    "actualKwh": 12.0,
                    "errorKwh": 0.5,
                }
            ],
            "metrics": {"mae_kwh": 0.5, "ignored": None},
        }

        result = backend_payload(payload)

        self.assertEqual("simple-benchmark", result["modelFamily"])
        self.assertEqual("2025-11-01T00:00:00Z", result["trainStart"])
        self.assertEqual("app/reports/forecast-runs/forecast-backtest-report.md", result["reportPath"])
        self.assertEqual([{"name": "mae_kwh", "value": 0.5}], result["metrics"])
        self.assertNotIn("errorKwh", result["points"][0])

    def test_parser_supports_no_save(self):
        args = build_parser().parse_args(["--no-save"])

        self.assertTrue(args.no_save)


if __name__ == "__main__":
    unittest.main()
