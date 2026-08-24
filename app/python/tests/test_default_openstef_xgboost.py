import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from default_openstef_xgboost import (
    MODEL_NAME,
    api_payload,
    build_parser,
    parse_utc,
    run_id,
    save_payload,
    write_comparison_plot,
)


class DefaultOpenStefXGBoostTest(unittest.TestCase):
    def test_parse_utc_accepts_z_suffix(self):
        self.assertEqual(
            datetime(2025, 6, 11, tzinfo=timezone.utc),
            parse_utc("2025-06-11T00:00:00Z"),
        )

    def test_run_id_contains_target_model_and_forecast_start(self):
        self.assertEqual(
            "generation-openstef-default-xgboost-20250909T000000Z-20250916T000000Z",
            run_id(
                "generation",
                datetime(2025, 9, 9, tzinfo=timezone.utc),
                datetime(2025, 9, 16, tzinfo=timezone.utc),
            ),
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
        self.assertEqual("openstef-xgboost", payload["modelFamily"])
        self.assertEqual("PT36H", payload["horizon"])
        self.assertEqual([{"name": "mae_kwh", "value": 0.25}], payload["metrics"])
        self.assertEqual(1.25, payload["points"][0]["forecastKwh"])
        self.assertEqual(1.0, payload["points"][0]["actualKwh"])
        self.assertNotIn("errorKwh", payload["points"][0])

    def test_save_payload_accepts_backend_response_shape(self):
        payload = {"runId": "run-1", "points": [object()], "metrics": [object()]}

        with patch(
            "default_openstef_xgboost.save_forecast_run",
            return_value={"runId": "run-1", "forecastPoints": 1, "metrics": 1},
        ):
            output = StringIO()
            with redirect_stdout(output):
                save_payload(payload, base_url="http://localhost:8080")

        self.assertIn("Saved run-1 to backend (1 points, 1 metrics)", output.getvalue())

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

        self.assertRegex(path.name, r"^generation-openstef-default-xgboost-comparison-\d{8}T\d{6}Z\.html$")
        self.assertIn("Default XGBoost Forecast vs Actual", html)
        self.assertIn("Time (UTC)", html)
        self.assertIn("Generation energy (kWh per 15-minute interval)", html)
        self.assertIn(MODEL_NAME, html)

    def test_write_comparison_plot_uses_forecast_only_title_without_actuals(self):
        payload = {
            "model": MODEL_NAME,
            "points": [
                {
                    "timestamp": "2026-08-24T08:00:00Z",
                    "forecastKwh": 1.25,
                    "actualKwh": None,
                }
            ],
        }
        metadata = {"target": "generation"}

        with TemporaryDirectory() as directory:
            path = write_comparison_plot(Path(directory), payload, metadata)
            html = path.read_text(encoding="utf-8")

        self.assertIn("Default XGBoost Forecast", html)
        self.assertNotIn("Default XGBoost Forecast vs Actual", html)

    def test_parser_is_default_openstef_xgboost_only(self):
        args = build_parser().parse_args([])

        self.assertEqual("generation", args.target)
        self.assertIsNone(args.train_start)
        self.assertIsNone(args.forecast_start)
        self.assertFalse(hasattr(args, "persist_model"))
        self.assertFalse(hasattr(args, "model_root"))
        self.assertFalse(hasattr(args, "models"))
        self.assertFalse(hasattr(args, "n_trials"))

    def test_parser_accepts_forecast_start_for_shared_batch_window(self):
        args = build_parser().parse_args(["--forecast-start", "2025-09-09T00:00:00Z", "--forecast-days", "3"])

        self.assertEqual("2025-09-09T00:00:00Z", args.forecast_start)
        self.assertEqual(3, args.forecast_days)


if __name__ == "__main__":
    unittest.main()
