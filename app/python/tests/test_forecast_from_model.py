import unittest
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from forecast_from_model import build_parser, payload_from_forecast, run_id


class ForecastFromModelTest(unittest.TestCase):
    def test_run_id_marks_persisted_model_name(self):
        self.assertEqual(
            "generation-openstef-barebones-persisted-20250909T000000Z",
            run_id("generation", "openstef-barebones-persisted", datetime(2025, 9, 9, tzinfo=timezone.utc)),
        )

    def test_payload_references_artifact_path(self):
        index = pd.date_range("2025-09-09T00:00:00Z", periods=1, freq="15min")
        comparison = pd.DataFrame(
            {"forecast_kwh": [1.25], "actual_kwh": [1.0], "error_kwh": [0.25]},
            index=index,
        )

        payload = payload_from_forecast(
            run_id_value="run-1",
            model="openstef-barebones-persisted",
            model_family="openstef-xgboost",
            target="generation",
            generated_at=datetime(2025, 9, 8, tzinfo=timezone.utc),
            train_start=datetime(2025, 6, 11, tzinfo=timezone.utc),
            train_end=datetime(2025, 9, 9, tzinfo=timezone.utc),
            forecast_start=datetime(2025, 9, 9, tzinfo=timezone.utc),
            forecast_end=datetime(2025, 9, 10, tzinfo=timezone.utc),
            comparison=comparison,
            metrics={"mae_kwh": 0.25, "ignored": None},
            artifact_dir=Path("/tmp/model-1"),
        )

        self.assertEqual("/tmp/model-1", payload["reportPath"])
        self.assertEqual("openstef-barebones-persisted", payload["model"])
        self.assertEqual([{"name": "mae_kwh", "value": 0.25}], payload["metrics"])
        self.assertEqual(1.25, payload["points"][0]["forecastKwh"])
        self.assertEqual(1.0, payload["points"][0]["actualKwh"])
        self.assertNotIn("errorKwh", payload["points"][0])

    def test_parser_requires_forecast_start(self):
        args = build_parser().parse_args([
            "/tmp/model-1",
            "--forecast-start",
            "2025-10-09T00:00:00Z",
            "--allow-in-sample-forecast",
        ])

        self.assertEqual("/tmp/model-1", args.artifact_dir)
        self.assertEqual("2025-10-09T00:00:00Z", args.forecast_start)
        self.assertTrue(args.allow_in_sample_forecast)


if __name__ == "__main__":
    unittest.main()
