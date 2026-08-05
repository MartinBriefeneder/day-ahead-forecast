import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from custom_openstef import (
    EXTENSION_POINT,
    MODEL_FAMILY,
    MODEL_NAME,
    api_payload,
    build_parser,
    parse_base_models,
    parse_utc,
    run_id,
    save_payload,
    write_comparison_plot,
    write_run_files,
)


class CustomOpenStefTest(unittest.TestCase):
    def test_parse_utc_accepts_z_suffix(self):
        self.assertEqual(
            datetime(2025, 6, 11, tzinfo=timezone.utc),
            parse_utc("2025-06-11T00:00:00Z"),
        )

    def test_parse_base_models_strips_empty_values(self):
        self.assertEqual(["lgbm", "gblinear"], parse_base_models("lgbm, gblinear, "))

    def test_run_id_contains_target_model_and_forecast_start(self):
        self.assertEqual(
            "generation-openstef-custom-ensemble-20250909T000000Z",
            run_id("generation", datetime(2025, 9, 9, tzinfo=timezone.utc)),
        )

    def test_api_payload_uses_backend_metric_list_shape(self):
        index = pd.date_range("2025-09-09T00:00:00Z", periods=1, freq="15min")
        comparison = pd.DataFrame(
            {"forecast_kwh": [1.25], "actual_kwh": [1.0], "error_kwh": [0.25]},
            index=index,
        )

        payload = api_payload(
            target="generation",
            generated_at=datetime(2025, 9, 8, tzinfo=timezone.utc),
            forecast_start=datetime(2025, 9, 9, tzinfo=timezone.utc),
            forecast_end=datetime(2025, 9, 10, tzinfo=timezone.utc),
            comparison=comparison,
            metrics={"mae_kwh": 0.25, "ignored": None},
        )

        self.assertEqual(MODEL_NAME, payload["model"])
        self.assertEqual(MODEL_FAMILY, payload["modelFamily"])
        self.assertEqual([{"name": "mae_kwh", "value": 0.25}], payload["metrics"])
        self.assertEqual(1.25, payload["points"][0]["forecastKwh"])
        self.assertEqual(1.0, payload["points"][0]["actualKwh"])
        self.assertNotIn("errorKwh", payload["points"][0])

    def test_save_payload_accepts_backend_response_shape(self):
        payload = {"runId": "run-1", "points": [object()], "metrics": [object()]}

        with patch(
            "custom_openstef.save_forecast_run",
            return_value={"runId": "run-1", "forecastPoints": 1, "metrics": 1},
        ):
            output = StringIO()
            with redirect_stdout(output):
                save_payload(payload, base_url="http://localhost:8080")

        self.assertIn("Saved run-1 to backend (1 points, 1 metrics)", output.getvalue())

    def test_write_run_files_saves_custom_comparison_plot(self):
        payload = {
            "runId": "generation-openstef-custom-ensemble-20250909T000000Z",
            "model": MODEL_NAME,
            "metrics": [{"name": "mae_kwh", "value": 0.25}],
            "points": [
                {
                    "timestamp": "2025-09-09T00:00:00Z",
                    "forecastKwh": 1.25,
                    "actualKwh": 1.0,
                }
            ],
        }
        metadata = {
            "target": "generation",
            "extensionPoint": EXTENSION_POINT,
            "baseModels": ["lgbm", "gblinear"],
            "combinerModel": "lgbm",
            "ensembleType": "learned_weights",
            "trainStart": "2025-06-11T00:00:00Z",
            "trainEnd": "2025-09-09T00:00:00Z",
            "forecastStart": "2025-09-09T00:00:00Z",
            "forecastEnd": "2025-09-16T00:00:00Z",
            "weatherAlignment": {"alignedWeatherIntervalCount": 1, "missingWeatherIntervalCount": 0},
            "validationMetrics": {"ensemble_r2": 0.5},
        }

        with TemporaryDirectory() as directory:
            plot_path = write_run_files(Path(directory), payload, metadata)
            plot = Path(directory) / "openstef-custom-ensemble-comparison.html"
            plot_exists = plot.exists()
            json_exists = (Path(directory) / "generation-openstef-custom-ensemble-20250909T000000Z.json").exists()
            markdown_exists = (Path(directory) / "openstef-custom-ensemble-report.md").exists()

        self.assertEqual("openstef-custom-ensemble-comparison.html", plot_path.name)
        self.assertTrue(plot_exists)
        self.assertFalse(json_exists)
        self.assertFalse(markdown_exists)

    def test_write_comparison_plot_saves_forecast_vs_actual_html(self):
        payload = {
            "model": MODEL_NAME,
            "points": [
                {
                    "timestamp": "2025-09-09T00:00:00Z",
                    "forecastKwh": 1.25,
                    "actualKwh": 1.0,
                }
            ],
        }
        metadata = {"target": "generation"}

        with TemporaryDirectory() as directory:
            path = write_comparison_plot(Path(directory), payload, metadata)
            html = path.read_text(encoding="utf-8")

        self.assertEqual("openstef-custom-ensemble-comparison.html", path.name)
        self.assertIn("Custom OpenSTEF", html)
        self.assertIn("Time (UTC)", html)
        self.assertIn("Generation energy (kWh per 15-minute interval)", html)
        self.assertIn(MODEL_NAME, html)

    def test_parser_defaults_to_custom_ensemble(self):
        args = build_parser().parse_args([])

        self.assertEqual("generation", args.target)
        self.assertEqual("lgbm,gblinear", args.base_models)
        self.assertEqual("lgbm", args.combiner_model)


if __name__ == "__main__":
    unittest.main()
