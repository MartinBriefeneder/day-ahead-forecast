import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from rolling_backtest import (
    DEFAULT_MODELS,
    RollingWindow,
    command_for,
    filter_valid_windows,
    generate_windows,
    includes_june_2026,
    validate_energy_window,
    validate_weather_window,
    write_run_summary,
)


class RollingBacktestTest(unittest.TestCase):
    def test_generate_windows_is_deterministic(self):
        windows = generate_windows(
            backtest_start=datetime(2025, 9, 1, tzinfo=timezone.utc),
            backtest_end=datetime(2025, 9, 22, tzinfo=timezone.utc),
            train_days=90,
            forecast_days=7,
            step_days=7,
        )

        self.assertEqual(3, len(windows))
        self.assertEqual(datetime(2025, 9, 1, tzinfo=timezone.utc), windows[0].forecast_start)
        self.assertEqual(datetime(2025, 9, 8, tzinfo=timezone.utc), windows[1].forecast_start)
        self.assertEqual(datetime(2025, 6, 3, tzinfo=timezone.utc), windows[0].train_start)

    def test_validate_energy_window_rejects_missing_training_coverage(self):
        window = RollingWindow(
            train_start=datetime(2025, 5, 1, tzinfo=timezone.utc),
            train_end=datetime(2025, 9, 1, tzinfo=timezone.utc),
            forecast_start=datetime(2025, 9, 1, tzinfo=timezone.utc),
            forecast_end=datetime(2025, 9, 8, tzinfo=timezone.utc),
        )

        reason = validate_energy_window(
            window,
            data_start=datetime(2025, 6, 1, tzinfo=timezone.utc),
            data_end=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )

        self.assertIn("before imported energy start", reason)

    def test_filter_valid_windows_reports_rejected_window(self):
        invalid = RollingWindow(
            train_start=datetime(2025, 5, 1, tzinfo=timezone.utc),
            train_end=datetime(2025, 9, 1, tzinfo=timezone.utc),
            forecast_start=datetime(2025, 9, 1, tzinfo=timezone.utc),
            forecast_end=datetime(2025, 9, 8, tzinfo=timezone.utc),
        )

        valid, diagnostics = filter_valid_windows(
            [invalid],
            data_start=datetime(2025, 6, 1, tzinfo=timezone.utc),
            data_end=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )

        self.assertEqual([], valid)
        self.assertIn("skip window", diagnostics[0])

    def test_validate_weather_window_reports_missing_intervals(self):
        weather_frame = pd.DataFrame(
            {"temperature_2m": [1.0], "relative_humidity_2m": [80.0], "wind_speed_10m": [2.0], "shortwave_radiation": [0.0], "surface_pressure": [990.0]},
            index=pd.DatetimeIndex(["2025-09-01T00:00:00Z"]),
        )
        weather = type("Weather", (), {"data": weather_frame})()
        window = RollingWindow(
            train_start=datetime(2025, 9, 1, tzinfo=timezone.utc),
            train_end=datetime(2025, 9, 1, 0, 15, tzinfo=timezone.utc),
            forecast_start=datetime(2025, 9, 1, 0, 15, tzinfo=timezone.utc),
            forecast_end=datetime(2025, 9, 1, 0, 30, tzinfo=timezone.utc),
        )

        with patch("rolling_backtest.load_weather_features", return_value=weather):
            reason = validate_weather_window(window, weather_path="weather.xlsx")

        self.assertIn("missing observed weather", reason)

    def test_includes_june_2026_detects_warning_period(self):
        window = RollingWindow(
            train_start=datetime(2026, 3, 1, tzinfo=timezone.utc),
            train_end=datetime(2026, 6, 1, tzinfo=timezone.utc),
            forecast_start=datetime(2026, 6, 1, tzinfo=timezone.utc),
            forecast_end=datetime(2026, 6, 8, tzinfo=timezone.utc),
        )

        self.assertTrue(includes_june_2026(window))

    def test_command_for_uses_selected_model_and_window(self):
        window = RollingWindow(
            train_start=datetime(2025, 6, 3, tzinfo=timezone.utc),
            train_end=datetime(2025, 9, 1, tzinfo=timezone.utc),
            forecast_start=datetime(2025, 9, 1, tzinfo=timezone.utc),
            forecast_end=datetime(2025, 9, 8, tzinfo=timezone.utc),
        )

        command = command_for("weekly-persistence", target="generation", window=window, base_url="http://backend", train_days=90)

        self.assertIn("main.py", command)
        self.assertIn("--save", command)
        self.assertIn("2025-09-01T00:00:00Z", command)

    def test_default_models_include_openstef_comparison_approaches(self):
        self.assertEqual(
            (
                "weekly-persistence",
                "openstef-default-xgboost",
                "openstef-xgboost-tuned",
                "openstef-lgbm",
                "openstef-custom-ensemble",
            ),
            DEFAULT_MODELS,
        )

    def test_write_run_summary_includes_diagnostics(self):
        window = RollingWindow(
            train_start=datetime(2025, 6, 3, tzinfo=timezone.utc),
            train_end=datetime(2025, 9, 1, tzinfo=timezone.utc),
            forecast_start=datetime(2025, 9, 1, tzinfo=timezone.utc),
            forecast_end=datetime(2025, 9, 8, tzinfo=timezone.utc),
        )
        with TemporaryDirectory() as directory:
            path = write_run_summary(Path(directory), [], [f"skip window {window.forecast_start}"])

            text = path.read_text(encoding="utf-8")

        self.assertIn("diagnostic", text)


if __name__ == "__main__":
    unittest.main()
