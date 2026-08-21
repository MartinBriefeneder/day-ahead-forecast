import unittest
from datetime import datetime, timezone

import pandas as pd

from main import backend_payload, build_parser, compute_metrics, resolve_data_query_end, resolve_windows


class MainForecastRunnerTest(unittest.TestCase):
    def test_parser_does_not_accept_no_save(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["--no-save"])

    def test_parser_does_not_accept_output_dir(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["--output-dir", "reports"])

    def test_parser_accepts_save(self):
        args = build_parser().parse_args(["--save"])

        self.assertEqual(True, args.save)

    def test_backend_payload_converts_metric_dict_to_items(self):
        payload = {
            "runId": "run-1",
            "metrics": {"mae_kwh": 0.5, "missing": pd.NA, "note": "ignored"},
            "points": [],
        }

        result = backend_payload(payload)

        self.assertEqual([{"name": "mae_kwh", "value": 0.5}], result["metrics"])

    def test_compute_metrics_coerces_pandas_missing_values(self):
        index = pd.date_range("2025-09-09T00:00:00Z", periods=2, freq="15min")
        forecast = pd.Series([pd.NA, 1.5], index=index, dtype="Float64")
        actual = pd.Series([1.0, 1.0], index=index, dtype="Float64")

        metrics, comparison = compute_metrics(forecast, actual)

        self.assertEqual(2, metrics["forecast_intervals"])
        self.assertEqual(1, metrics["aligned_intervals"])
        self.assertEqual(1.5, metrics["total_forecast_kwh"])
        self.assertEqual(0.5, metrics["mae_kwh"])
        self.assertTrue(pd.isna(comparison.iloc[0].forecast_kwh))

    def test_forecast_start_defaults_training_window_to_previous_train_days(self):
        args = build_parser().parse_args([
            "--forecast-start",
            "2026-08-05T00:00:00Z",
            "--train-days",
            "90",
            "--forecast-weeks",
            "1",
        ])

        train_start, forecast_start, forecast_end, horizon = resolve_windows(args)

        self.assertEqual("2026-05-07T00:00:00+00:00", train_start.isoformat())
        self.assertEqual("2026-08-05T00:00:00+00:00", forecast_start.isoformat())
        self.assertEqual("2026-08-12T00:00:00+00:00", forecast_end.isoformat())
        self.assertEqual(7, horizon.days)

    def test_forecast_days_sets_day_horizon(self):
        args = build_parser().parse_args([
            "--forecast-start",
            "2026-08-05T00:00:00Z",
            "--train-days",
            "90",
            "--forecast-days",
            "3",
        ])

        _, _, forecast_end, horizon = resolve_windows(args)

        self.assertEqual("2026-08-08T00:00:00+00:00", forecast_end.isoformat())
        self.assertEqual(3, horizon.days)

    def test_future_forecast_queries_only_training_range(self):
        query_end = resolve_data_query_end(
            datetime(2025, 6, 1, tzinfo=timezone.utc),
            datetime(2026, 8, 22, tzinfo=timezone.utc),
            datetime(2026, 8, 29, tzinfo=timezone.utc),
            train_days=90,
            now=datetime(2026, 8, 21, tzinfo=timezone.utc),
        )

        self.assertEqual("2025-08-30T00:00:00+00:00", query_end.isoformat())

    def test_backtest_queries_through_forecast_end(self):
        query_end = resolve_data_query_end(
            datetime(2025, 6, 1, tzinfo=timezone.utc),
            datetime(2025, 9, 1, tzinfo=timezone.utc),
            datetime(2025, 9, 8, tzinfo=timezone.utc),
            train_days=90,
            now=datetime(2026, 8, 21, tzinfo=timezone.utc),
        )

        self.assertEqual("2025-09-08T00:00:00+00:00", query_end.isoformat())

if __name__ == "__main__":
    unittest.main()
