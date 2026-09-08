import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from export_forecast_metrics import (
    build_metric_row,
    compute_metrics,
    deduplicate_summaries,
    markdown_table,
    require_rows,
    weather_source,
    write_metric_table_files,
)


class ExportForecastMetricsTest(unittest.TestCase):
    def test_compute_metrics_includes_daily_error_and_wape(self):
        points = [
            {"timestamp": "2025-10-01T00:00:00Z", "forecastKwh": 2.0, "actualKwh": 1.0},
            {"timestamp": "2025-10-01T00:15:00Z", "forecastKwh": 4.0, "actualKwh": 5.0},
        ]

        metrics = compute_metrics(points, {"actualPointCount": 2})

        self.assertEqual(2, metrics["forecast_intervals"])
        self.assertEqual(2, metrics["actual_intervals"])
        self.assertEqual(2, metrics["aligned_intervals"])
        self.assertEqual(0, metrics["missing_actual_intervals"])
        self.assertEqual(1.0, metrics["mae_kwh"])
        self.assertEqual(1.0, metrics["rmse_kwh"])
        self.assertEqual(0.0, metrics["bias_kwh"])
        self.assertEqual(0.0, metrics["total_energy_error_kwh"])
        self.assertEqual(0.0, metrics["mean_abs_daily_energy_error_kwh"])
        self.assertAlmostEqual(33.333333, metrics["wape_percent"], places=5)

    def test_compute_metrics_handles_missing_actuals(self):
        metrics = compute_metrics(
            [{"timestamp": "2025-10-01T00:00:00Z", "forecastKwh": 2.0, "actualKwh": None}],
            {},
        )

        self.assertEqual(1, metrics["forecast_intervals"])
        self.assertEqual(0, metrics["aligned_intervals"])
        self.assertEqual(1, metrics["missing_actual_intervals"])
        self.assertNotIn("mae_kwh", metrics)

    def test_build_metric_row_adds_summary_and_weather_source(self):
        row = build_metric_row(
            {
                "runId": "run-1",
                "target": "generation",
                "model": "openstef-default-xgboost",
                "modelFamily": "openstef-xgboost",
                "trainStart": "2025-07-03T00:00:00Z",
                "trainEnd": "2025-10-01T00:00:00Z",
                "forecastStart": "2025-10-01T00:00:00Z",
                "forecastEnd": "2025-10-08T00:00:00Z",
                "sampleInterval": "PT15M",
                "horizon": "PT36H",
                "reportPath": "report.html",
            },
            {
                "points": [
                    {"timestamp": "2025-10-01T00:00:00Z", "forecastKwh": 2.0, "actualKwh": 1.0}
                ],
                "diagnostics": {"actualPointCount": 1},
            },
        )

        self.assertEqual("run-1", row["run_id"])
        self.assertEqual("observed historical weather", row["weather_source"])
        self.assertEqual(1.0, row["mae_kwh"])

    def test_weather_source_labels_known_models(self):
        self.assertEqual("energy-only", weather_source("weekly-persistence"))
        self.assertEqual("Gridoo forecast weather", weather_source("openstef-future-xgboost"))
        self.assertEqual("observed historical weather", weather_source("openstef-xgboost-tuned"))
        self.assertEqual("unknown", weather_source("other"))

    def test_deduplicate_summaries_keeps_latest_generated_at(self):
        summaries = [
            {"runId": "run-1", "generatedAt": "2026-09-07T10:00:00Z", "reportPath": "old.html"},
            {"runId": "run-1", "generatedAt": "2026-09-07T11:00:00Z", "reportPath": "new.html"},
            {"runId": "run-2", "generatedAt": "2026-09-07T09:00:00Z", "reportPath": "other.html"},
        ]

        selected = sorted(deduplicate_summaries(summaries), key=lambda item: item["runId"])

        self.assertEqual(["run-1", "run-2"], [summary["runId"] for summary in selected])
        self.assertEqual("new.html", selected[0]["reportPath"])

    def test_markdown_table_renders_missing_metrics_as_empty_cells(self):
        table = markdown_table([
            {
                "run_id": "run-1",
                "target": "generation",
                "model": "weekly-persistence",
                "model_family": "simple-benchmark",
                "weather_source": "energy-only",
                "forecast_intervals": 1,
                "aligned_intervals": 0,
                "missing_actual_intervals": 1,
            }
        ])

        self.assertIn("# Forecast Metric Table", table)
        self.assertIn("weekly-persistence", table)
        self.assertIn("wape_percent", table)

    def test_write_metric_table_files_writes_markdown_and_csv(self):
        rows = [
            {
                "run_id": "run-1",
                "target": "generation",
                "model": "weekly-persistence",
                "model_family": "simple-benchmark",
                "weather_source": "energy-only",
                "forecast_intervals": 1,
                "actual_intervals": 1,
                "aligned_intervals": 1,
                "missing_actual_intervals": 0,
                "mae_kwh": 0.5,
            }
        ]
        with TemporaryDirectory() as directory:
            markdown_path, csv_path = write_metric_table_files(Path(directory), "generation", rows)

            self.assertTrue(markdown_path.exists())
            self.assertTrue(csv_path.exists())
            self.assertIn("weekly-persistence", markdown_path.read_text(encoding="utf-8"))
            self.assertIn("weekly-persistence", csv_path.read_text(encoding="utf-8"))

    def test_require_rows_reports_no_matching_runs(self):
        with self.assertRaisesRegex(ValueError, "No metric rows to write"):
            require_rows([])


if __name__ == "__main__":
    unittest.main()
