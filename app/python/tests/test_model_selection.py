import csv
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from model_selection import (
    DEFAULT_WEIGHTS,
    filter_rows,
    parse_weights,
    read_metric_rows,
    select_models,
    slice_name,
    validate_metric_rows,
    write_outputs,
)


def metric_row(target, model, forecast_start, mae, rmse, bias, daily_error, **overrides):
    row = {
        "run_id": f"{target}-{model}-{forecast_start}",
        "target": target,
        "model": model,
        "model_family": overrides.get("model_family", model),
        "weather_source": overrides.get("weather_source", "energy-only"),
        "train_start": "2025-07-01T00:00:00Z",
        "train_end": forecast_start,
        "forecast_start": forecast_start,
        "forecast_end": overrides.get("forecast_end", "2025-10-08T00:00:00Z"),
        "sample_interval": "PT15M",
        "horizon": overrides.get("horizon", "P7D"),
        "aligned_intervals": "96",
        "mae_kwh": str(mae),
        "rmse_kwh": str(rmse),
        "bias_kwh": str(bias),
        "mean_abs_daily_energy_error_kwh": str(daily_error),
    }
    row.update({key: str(value) for key, value in overrides.items()})
    return row


class ModelSelectionTest(unittest.TestCase):
    def test_select_models_ranks_each_target_separately(self):
        rows = [
            metric_row("generation", "model-a", "2025-10-01T00:00:00Z", 1, 2, 0.1, 3),
            metric_row("generation", "model-a", "2025-10-08T00:00:00Z", 1, 2, 0.1, 3),
            metric_row("generation", "model-b", "2025-10-01T00:00:00Z", 4, 5, 2, 6),
            metric_row("generation", "model-b", "2025-10-08T00:00:00Z", 4, 5, 2, 6),
            metric_row("consumption", "model-a", "2025-10-01T00:00:00Z", 5, 6, 2, 7),
            metric_row("consumption", "model-a", "2025-10-08T00:00:00Z", 5, 6, 2, 7),
            metric_row("consumption", "model-b", "2025-10-01T00:00:00Z", 2, 3, 0.2, 4),
            metric_row("consumption", "model-b", "2025-10-08T00:00:00Z", 2, 3, 0.2, 4),
        ]

        results = select_models(rows, current_slice="full-period")

        winners = {result.target: result.model for result in results if result.rank == 1}
        self.assertEqual({"generation": "model-a", "consumption": "model-b"}, winners)

    def test_select_models_marks_fixed_window_only(self):
        rows = [metric_row("generation", "model-a", "2025-10-01T00:00:00Z", 1, 2, 0.1, 3)]

        results = select_models(rows, min_windows=2)

        self.assertEqual("fixed-window-only", results[0].evidence_label)
        self.assertEqual("fixed-window-only", results[0].recommendation_status)
        self.assertEqual(1, results[0].rank)

    def test_select_models_marks_insufficient_slice(self):
        rows = [
            metric_row("generation", "model-a", "2025-10-01T00:00:00Z", 1, 2, 0.1, 3),
            metric_row("generation", "model-a", "2025-10-08T00:00:00Z", 1, 2, 0.1, 3),
        ]

        results = select_models(rows, min_windows=3)

        self.assertEqual("insufficient-sample", results[0].recommendation_status)
        self.assertIsNone(results[0].rank)

    def test_validate_metric_rows_reports_missing_and_invalid_values(self):
        rows = [
            {
                "target": "generation",
                "model": "model-a",
                "forecast_start": "not-a-date",
                "forecast_end": "2025-10-08T00:00:00Z",
                "mae_kwh": "bad",
                "rmse_kwh": "2",
                "bias_kwh": "",
                "mean_abs_daily_energy_error_kwh": "3",
                "source_file": "metrics.csv",
                "source_line": "2",
            }
        ]

        diagnostics = validate_metric_rows(rows)

        self.assertTrue(any("missing required value: bias_kwh" in diagnostic for diagnostic in diagnostics))
        self.assertTrue(any("invalid numeric value for mae_kwh" in diagnostic for diagnostic in diagnostics))
        self.assertTrue(any("invalid timestamp for forecast_start" in diagnostic for diagnostic in diagnostics))

    def test_filter_rows_supports_month_season_and_horizon(self):
        rows = [
            metric_row("generation", "model-a", "2025-10-01T00:00:00Z", 1, 2, 0.1, 3, horizon="P7D"),
            metric_row("generation", "model-a", "2026-01-01T00:00:00Z", 1, 2, 0.1, 3, horizon="PT36H"),
        ]

        self.assertEqual(1, len(filter_rows(rows, month=10)))
        self.assertEqual(1, len(filter_rows(rows, season="winter")))
        self.assertEqual(1, len(filter_rows(rows, horizon="PT36H")))
        self.assertEqual("month=10;horizon=P7D", slice_name(month=10, horizon="P7D"))

    def test_parse_weights_normalizes_overrides(self):
        weights = parse_weights("mae=2,rmse=1,daily_energy=1,bias=1,stability=0")

        self.assertAlmostEqual(1.0, sum(weights.values()))
        self.assertGreater(weights["mae"], DEFAULT_WEIGHTS["mae"])

    def test_read_metric_rows_reports_missing_columns(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "metrics.csv"
            path.write_text("target,model\ngeneration,model-a\n", encoding="utf-8")

            rows, diagnostics = read_metric_rows([path])

        self.assertEqual([], rows)
        self.assertTrue(any("missing required columns" in diagnostic for diagnostic in diagnostics))

    def test_write_outputs_writes_markdown_with_sources(self):
        rows = [
            metric_row("generation", "model-a", "2025-10-01T00:00:00Z", 1, 2, 0.1, 3),
            metric_row("generation", "model-a", "2025-10-08T00:00:00Z", 1, 2, 0.1, 3),
            metric_row("generation", "model-b", "2025-10-01T00:00:00Z", 3, 4, 1, 5),
            metric_row("generation", "model-b", "2025-10-08T00:00:00Z", 3, 4, 1, 5),
        ]
        results = select_models(rows)
        with TemporaryDirectory() as directory:
            input_path = Path(directory) / "metrics.csv"
            markdown_path = write_outputs(
                Path(directory),
                results,
                input_paths=[input_path],
                diagnostics=[],
                weights=DEFAULT_WEIGHTS,
                current_slice="full-period",
                source_rows=[{**rows[0], "crps": "1.2"}],
            )

            self.assertTrue(markdown_path.exists())
            self.assertEqual([], list(Path(directory).glob("forecast-model-selection-*.csv")))
            markdown = markdown_path.read_text(encoding="utf-8")

            self.assertIn("Source Traceability", markdown)
            self.assertIn("https://otexts.com/fpp3/tscv.html", markdown)
            self.assertIn("`crps`", markdown)
            self.assertIn("Evaluation slice: `full-period`", markdown)
            self.assertIn("| generation | 1 | `model-a` |", markdown)


if __name__ == "__main__":
    unittest.main()
