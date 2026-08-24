import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from unittest.mock import patch

import pandas as pd

from future_openstef_xgboost import (
    FUTURE_WEATHER_FEATURES,
    MODEL_NAME,
    api_payload,
    build_parser,
    complete_future_weather_frame,
    drop_incomplete_weather_rows,
    next_quarter_hour,
    numeric_openstef_frame,
    run_id,
    save_payload,
)


class FutureOpenStefXGBoostTest(unittest.TestCase):
    def test_run_id_contains_future_model_name(self):
        self.assertEqual(
            "generation-openstef-future-xgboost-20260819T000000Z-20260826T000000Z",
            run_id(
                "generation",
                datetime(2026, 8, 19, tzinfo=timezone.utc),
                datetime(2026, 8, 26, tzinfo=timezone.utc),
            ),
        )

    def test_next_quarter_hour_rounds_up(self):
        self.assertEqual(
            datetime(2026, 8, 18, 12, 15, tzinfo=timezone.utc),
            next_quarter_hour(datetime(2026, 8, 18, 12, 1, 5, tzinfo=timezone.utc)),
        )
        self.assertEqual(
            datetime(2026, 8, 18, 13, 0, tzinfo=timezone.utc),
            next_quarter_hour(datetime(2026, 8, 18, 12, 59, tzinfo=timezone.utc)),
        )

    def test_complete_future_weather_requires_all_quarter_hour_intervals(self):
        index = pd.date_range("2026-08-19T00:00:00Z", periods=2, freq="15min")
        data = pd.DataFrame(
            {
                "temperature_2m": [15.0, 16.0],
                "wind_speed_10m": [2.0, 2.5],
                "shortwave_radiation": [0.0, 5.0],
            },
            index=index,
        )

        with self.assertRaisesRegex(ValueError, "missing 1 interval"):
            complete_future_weather_frame(
                data,
                pd.Timestamp("2026-08-19T00:00:00Z").to_pydatetime(),
                pd.Timestamp("2026-08-19T00:45:00Z").to_pydatetime(),
            )

    def test_api_payload_saves_future_points_without_actual_values(self):
        index = pd.date_range("2026-08-19T00:00:00Z", periods=2, freq="15min")
        forecast = pd.Series([1.0, 1.5], index=index, name="forecast_kwh")

        payload = api_payload(
            target="consumption",
            generated_at=datetime(2026, 8, 18, tzinfo=timezone.utc),
            train_start=datetime(2026, 3, 1, tzinfo=timezone.utc),
            train_end=datetime(2026, 5, 30, tzinfo=timezone.utc),
            forecast_start=datetime(2026, 8, 19, tzinfo=timezone.utc),
            forecast_end=datetime(2026, 8, 19, 0, 30, tzinfo=timezone.utc),
            forecast=forecast,
        )

        self.assertEqual(MODEL_NAME, payload["model"])
        self.assertEqual("openstef-xgboost", payload["modelFamily"])
        self.assertEqual("PT15M", payload["sampleInterval"])
        self.assertEqual(2, len(payload["points"]))
        self.assertEqual(1.0, payload["points"][0]["forecastKwh"])
        self.assertIsNone(payload["points"][0]["actualKwh"])
        self.assertEqual([{"name": "forecast_intervals", "value": 2.0}, {"name": "total_forecast_kwh", "value": 2.5}], payload["metrics"])

    def test_api_payload_rejects_missing_forecast_values(self):
        index = pd.date_range("2026-08-19T00:00:00Z", periods=1, freq="15min")
        forecast = pd.Series([pd.NA], index=index, name="forecast_kwh")

        with self.assertRaisesRegex(ValueError, "missing values"):
            api_payload(
                target="generation",
                generated_at=datetime(2026, 8, 18, tzinfo=timezone.utc),
                train_start=datetime(2026, 3, 1, tzinfo=timezone.utc),
                train_end=datetime(2026, 5, 30, tzinfo=timezone.utc),
                forecast_start=datetime(2026, 8, 19, tzinfo=timezone.utc),
                forecast_end=datetime(2026, 8, 19, 0, 15, tzinfo=timezone.utc),
                forecast=forecast,
            )

    def test_numeric_openstef_frame_converts_pandas_na_to_float_nan(self):
        data = pd.DataFrame(
            {
                "generation": pd.Series([pd.NA], dtype="Float64"),
                "temperature_2m": pd.Series([pd.NA], dtype="Float64"),
                "wind_speed_10m": [2],
                "shortwave_radiation": [0],
            }
        )

        result = numeric_openstef_frame(data, "generation")

        self.assertEqual("float64", str(result["generation"].dtype))
        self.assertTrue(pd.isna(result.loc[0, "generation"]))
        self.assertIsNot(pd.NA, result.loc[0, "generation"])

    def test_drop_incomplete_weather_rows_removes_rows_and_updates_diagnostics(self):
        index = pd.date_range("2026-06-18T21:00:00Z", periods=2, freq="15min")
        data = pd.DataFrame(
            {
                "generation": [1.0, 2.0],
                "temperature_2m": [18.0, pd.NA],
                "wind_speed_10m": [1.5, 1.7],
                "shortwave_radiation": [20.0, 25.0],
            },
            index=index,
        )
        diagnostics = {"alignment": {"missingWeatherIntervalCount": 1}}

        result = drop_incomplete_weather_rows(data, FUTURE_WEATHER_FEATURES, diagnostics, "training")

        self.assertEqual([index[0]], list(result.index))
        self.assertEqual(1, diagnostics["alignment"]["droppedTrainingRowsWithMissingWeather"])
        self.assertEqual(
            ["2026-06-18T21:15:00Z"],
            diagnostics["alignment"]["droppedTrainingTimestampExamples"],
        )

    def test_drop_incomplete_weather_rows_rejects_empty_result(self):
        index = pd.date_range("2026-06-18T21:15:00Z", periods=1, freq="15min")
        data = pd.DataFrame(
            {
                "generation": [1.0],
                "temperature_2m": [pd.NA],
                "wind_speed_10m": [1.7],
                "shortwave_radiation": [25.0],
            },
            index=index,
        )

        with self.assertRaisesRegex(ValueError, "no rows with complete historical weather"):
            drop_incomplete_weather_rows(data, FUTURE_WEATHER_FEATURES, {}, "training")

    def test_drop_incomplete_weather_rows_allows_empty_prediction_context(self):
        index = pd.date_range("2026-06-18T21:15:00Z", periods=1, freq="15min")
        data = pd.DataFrame(
            {
                "generation": [1.0],
                "temperature_2m": [pd.NA],
                "wind_speed_10m": [1.7],
                "shortwave_radiation": [25.0],
            },
            index=index,
        )

        result = drop_incomplete_weather_rows(
            data,
            FUTURE_WEATHER_FEATURES,
            {},
            "prediction context",
            require_non_empty=False,
        )

        self.assertTrue(result.empty)

    def test_parser_defaults_to_next_week_future_weather_model(self):
        args = build_parser().parse_args([])

        self.assertEqual("generation", args.target)
        self.assertEqual(7, args.forecast_days)
        self.assertEqual(14, args.context_days)
        self.assertFalse(args.no_save)
        self.assertEqual(("temperature_2m", "wind_speed_10m", "shortwave_radiation"), FUTURE_WEATHER_FEATURES)

    def test_save_payload_accepts_backend_response_shape(self):
        payload = {"runId": "run-1", "points": [object()], "metrics": [object()]}

        with patch(
            "future_openstef_xgboost.save_forecast_run",
            return_value={"runId": "run-1", "forecastPoints": 1, "metrics": 1},
        ):
            output = StringIO()
            with redirect_stdout(output):
                save_payload(payload, base_url="http://localhost:8080")

        self.assertIn("Saved run-1 to backend (1 points, 1 metrics)", output.getvalue())


if __name__ == "__main__":
    unittest.main()
