import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from compare_forecasts import build_parser, expected_interval_count, select_summaries, write_comparison_figure
from forecast_runner import report_timestamp, timestamped_report_path


class CompareForecastsTest(unittest.TestCase):
    def test_parser_accepts_consumption_target(self):
        args = build_parser().parse_args(["--target", "consumption"])

        self.assertEqual("consumption", args.target)

    def test_select_summaries_keeps_target_groups_separate(self):
        summaries = [
            {
                "runId": "generation-run",
                "target": "generation",
                "model": "weekly-persistence",
                "forecastStart": "2025-12-01T00:00:00Z",
                "forecastEnd": "2025-12-02T00:00:00Z",
                "sampleInterval": "PT15M",
                "generatedAt": "2026-01-01T00:00:00Z",
            },
            {
                "runId": "consumption-run",
                "target": "consumption",
                "model": "weekly-persistence",
                "forecastStart": "2025-12-01T00:00:00Z",
                "forecastEnd": "2025-12-02T00:00:00Z",
                "sampleInterval": "PT15M",
                "generatedAt": "2026-01-01T00:00:00Z",
            },
        ]

        selected = select_summaries(summaries, target="consumption", forecast_start=None, forecast_end=None)

        self.assertEqual(["consumption-run"], [summary["runId"] for summary in selected])

    def test_select_summaries_all_saved_keeps_multiple_windows(self):
        summaries = [
            {
                "runId": "run-a",
                "target": "generation",
                "model": "weekly-persistence",
                "forecastStart": "2025-12-01T00:00:00Z",
                "forecastEnd": "2025-12-02T00:00:00Z",
                "sampleInterval": "PT15M",
                "generatedAt": "2026-01-01T00:00:00Z",
            },
            {
                "runId": "run-b",
                "target": "generation",
                "model": "weekly-persistence",
                "forecastStart": "2025-12-02T00:00:00Z",
                "forecastEnd": "2025-12-03T00:00:00Z",
                "sampleInterval": "PT15M",
                "generatedAt": "2026-01-02T00:00:00Z",
            },
        ]

        selected = select_summaries(summaries, target="generation", forecast_start=None, forecast_end=None, all_saved=True)

        self.assertEqual(["run-a", "run-b"], [summary["runId"] for summary in selected])

    def test_comparison_figure_writes_actuals_for_each_saved_window(self):
        runs = [
            {
                "target": "generation",
                "model": "model-a",
                "forecastStart": "2025-12-01T00:00:00Z",
                "forecastEnd": "2025-12-02T00:00:00Z",
                "sampleInterval": "PT15M",
                "points": [{"timestamp": "2025-12-01T00:00:00Z", "forecastKwh": 1.0, "actualKwh": 1.2}],
            },
            {
                "target": "generation",
                "model": "model-b",
                "forecastStart": "2025-12-02T00:00:00Z",
                "forecastEnd": "2025-12-03T00:00:00Z",
                "sampleInterval": "PT15M",
                "points": [{"timestamp": "2025-12-02T00:00:00Z", "forecastKwh": 2.0, "actualKwh": 2.3}],
            },
        ]

        with TemporaryDirectory() as directory:
            path = Path(directory) / "comparison.html"
            write_comparison_figure(path, runs)
            html = path.read_text(encoding="utf-8")

        self.assertIn("Actual Generation (2025-12-01T00:00:00Z to 2025-12-02T00:00:00Z)", html)
        self.assertIn("Actual Generation (2025-12-02T00:00:00Z to 2025-12-03T00:00:00Z)", html)
        self.assertIn("Forecast vs Actual Comparison", html)
        self.assertIn("2 forecast windows, 2 saved runs", html)

    def test_comparison_figure_labels_future_runs_as_forecast_only(self):
        runs = [
            {
                "target": "generation",
                "model": "model-a",
                "forecastStart": "2026-08-24T08:00:00Z",
                "forecastEnd": "2026-08-31T08:00:00Z",
                "sampleInterval": "PT15M",
                "points": [{"timestamp": "2026-08-24T08:00:00Z", "forecastKwh": 1.0, "actualKwh": None}],
            }
        ]

        with TemporaryDirectory() as directory:
            path = Path(directory) / "comparison.html"
            write_comparison_figure(path, runs)
            html = path.read_text(encoding="utf-8")

        self.assertIn("Forecast-Only Comparison", html)
        self.assertIn("2026-08-24T08:00:00Z to 2026-08-31T08:00:00Z", html)
        self.assertNotIn("Actual Generation", html)

    def test_comparison_figure_labels_forecast_only_multiple_windows(self):
        runs = [
            {
                "target": "generation",
                "model": "model-a",
                "forecastStart": "2026-08-24T08:00:00Z",
                "forecastEnd": "2026-08-31T08:00:00Z",
                "sampleInterval": "PT15M",
                "points": [{"timestamp": "2026-08-24T08:00:00Z", "forecastKwh": 1.0, "actualKwh": None}],
            },
            {
                "target": "generation",
                "model": "model-a",
                "forecastStart": "2026-08-31T08:00:00Z",
                "forecastEnd": "2026-09-07T08:00:00Z",
                "sampleInterval": "PT15M",
                "points": [{"timestamp": "2026-08-31T08:00:00Z", "forecastKwh": 2.0, "actualKwh": None}],
            },
        ]

        with TemporaryDirectory() as directory:
            path = Path(directory) / "comparison.html"
            write_comparison_figure(path, runs)
            html = path.read_text(encoding="utf-8")

        self.assertIn("model-a (2026-08-24T08:00:00Z to 2026-08-31T08:00:00Z)", html)
        self.assertIn("model-a (2026-08-31T08:00:00Z to 2026-09-07T08:00:00Z)", html)

    def test_expected_interval_count_uses_saved_forecast_window(self):
        run = {
            "forecastStart": "2026-08-24T08:00:00Z",
            "forecastEnd": "2026-08-31T08:00:00Z",
            "sampleInterval": "PT15M",
        }

        self.assertEqual(672, expected_interval_count(run))

    def test_timestamped_report_path_adds_utc_timestamp_to_filename(self):
        path = timestamped_report_path(
            Path("reports"),
            "generation-all-python-forecast-comparison",
            generated_at=datetime(2026, 8, 21, 12, 34, 56, tzinfo=timezone.utc),
        )

        self.assertEqual(Path("reports/generation-all-python-forecast-comparison-20260821T123456Z.html"), path)
        self.assertEqual("20260821T123456Z", report_timestamp("2026-08-21T12:34:56Z"))


if __name__ == "__main__":
    unittest.main()
