import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from quantile_calibrated_xgboost import (
    build_parser,
    extract_quantile_series,
    quantile_column,
    quantile_frame,
    quantile_metrics,
    write_quantile_csv,
    write_quantile_plot,
)


class QuantileCalibratedXGBoostTest(unittest.TestCase):
    def test_quantile_column_formats_fixed_columns(self):
        self.assertEqual("p10_kwh", quantile_column(0.1))
        self.assertEqual("p50_kwh", quantile_column(0.5))
        self.assertEqual("p90_kwh", quantile_column(0.9))

    def test_extract_quantile_series_reads_dict_output(self):
        index = pd.date_range("2025-10-01T00:00:00Z", periods=1, freq="15min")
        forecast = type(
            "Forecast",
            (),
            {
                "quantile_series": {
                    0.1: pd.Series([1.0], index=index),
                    0.5: pd.Series([2.0], index=index),
                    0.9: pd.Series([3.0], index=index),
                }
            },
        )()

        result = extract_quantile_series(forecast)

        self.assertEqual(2.0, float(result[0.5].iloc[0]))

    def test_extract_quantile_series_reads_openstef_quantiles_data(self):
        index = pd.date_range("2025-10-01T00:00:00Z", periods=1, freq="15min")
        forecast = type(
            "Forecast",
            (),
            {
                "quantiles_data": pd.DataFrame(
                    {"quantile_P10": [1.0], "quantile_P50": [2.0], "quantile_P90": [3.0]},
                    index=index,
                )
            },
        )()

        result = extract_quantile_series(forecast)

        self.assertEqual(3.0, float(result[0.9].iloc[0]))

    def test_quantile_frame_uses_median_as_point_forecast(self):
        index = pd.date_range("2025-10-01T00:00:00Z", periods=1, freq="15min")
        frame = quantile_frame(
            {
                0.1: pd.Series([1.0], index=index),
                0.5: pd.Series([2.0], index=index),
                0.9: pd.Series([3.0], index=index),
            },
            pd.Series([2.5], index=index),
        )

        self.assertEqual(2.0, frame["forecast_kwh"].iloc[0])
        self.assertEqual(2.5, frame["actual_kwh"].iloc[0])

    def test_quantile_metrics_reports_coverage_when_actuals_exist(self):
        index = pd.date_range("2025-10-01T00:00:00Z", periods=2, freq="15min")
        frame = pd.DataFrame(
            {
                "p10_kwh": [1.0, 1.0],
                "p50_kwh": [2.0, 2.0],
                "p90_kwh": [3.0, 3.0],
                "actual_kwh": [2.5, 4.0],
            },
            index=index,
        )

        metrics = quantile_metrics(frame)

        self.assertEqual(2, metrics["quantile_aligned_intervals"])
        self.assertEqual(50.0, metrics["p10_p90_coverage_percent"])
        self.assertEqual(2.0, metrics["mean_prediction_interval_width_kwh"])

    def test_quantile_metrics_marks_missing_actuals_unavailable(self):
        index = pd.date_range("2026-10-01T00:00:00Z", periods=1, freq="15min")
        frame = pd.DataFrame(
            {"p10_kwh": [1.0], "p50_kwh": [2.0], "p90_kwh": [3.0], "actual_kwh": [pd.NA]},
            index=index,
        )

        metrics = quantile_metrics(frame)

        self.assertEqual(0, metrics["quantile_aligned_intervals"])
        self.assertIsNone(metrics["p10_p90_coverage_percent"])

    def test_write_quantile_outputs(self):
        index = pd.date_range("2025-10-01T00:00:00Z", periods=1, freq="15min")
        frame = pd.DataFrame(
            {"p10_kwh": [1.0], "p50_kwh": [2.0], "p90_kwh": [3.0], "actual_kwh": [2.5], "forecast_kwh": [2.0]},
            index=index,
        )
        with TemporaryDirectory() as directory:
            csv_path = write_quantile_csv(Path(directory), "generation", frame, datetime(2026, 1, 1, tzinfo=timezone.utc))
            plot_path = write_quantile_plot(Path(directory), "generation", frame, {}, datetime(2026, 1, 1, tzinfo=timezone.utc))

            csv_text = csv_path.read_text(encoding="utf-8")
            html = plot_path.read_text(encoding="utf-8")

        self.assertIn("p10_kwh", csv_text)
        self.assertIn("Quantile-Calibrated XGBoost", html)

    def test_parser_defaults_to_generation(self):
        args = build_parser().parse_args([])

        self.assertEqual("generation", args.target)


if __name__ == "__main__":
    unittest.main()
