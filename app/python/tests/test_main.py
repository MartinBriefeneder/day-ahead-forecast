import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from main import write_reports


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


if __name__ == "__main__":
    unittest.main()
