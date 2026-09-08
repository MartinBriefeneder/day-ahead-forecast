import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from lgbm_openstef import (
    MODEL_FAMILY,
    MODEL_NAME,
    api_payload,
    build_parser,
    run_id,
    save_payload,
    write_comparison_plot,
)


class LgbmOpenStefTest(unittest.TestCase):
    def test_run_id_contains_lgbm_model_name(self):
        self.assertEqual(
            "generation-openstef-lgbm-20250909T000000Z-20250916T000000Z",
            run_id(
                "generation",
                datetime(2025, 9, 9, tzinfo=timezone.utc),
                datetime(2025, 9, 16, tzinfo=timezone.utc),
            ),
        )

    def test_api_payload_uses_lgbm_metadata(self):
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
        self.assertEqual("PT15M", payload["sampleInterval"])
        self.assertEqual([{"name": "mae_kwh", "value": 0.25}], payload["metrics"])
        self.assertEqual(1.25, payload["points"][0]["forecastKwh"])

    def test_save_payload_accepts_backend_response_shape(self):
        payload = {"runId": "run-1", "points": [object()], "metrics": [object()]}

        with patch(
            "lgbm_openstef.save_forecast_run",
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

        self.assertRegex(path.name, r"^generation-openstef-lgbm-comparison-\d{8}T\d{6}Z\.html$")
        self.assertIn("LightGBM Forecast vs Actual", html)
        self.assertIn("Generation energy (kWh per 15-minute interval)", html)

    def test_parser_defaults_to_lgbm(self):
        args = build_parser().parse_args([])

        self.assertEqual("generation", args.target)
        self.assertIsNone(args.train_start)
        self.assertIsNone(args.forecast_start)


if __name__ == "__main__":
    unittest.main()
