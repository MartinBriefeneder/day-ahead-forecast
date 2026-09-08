import unittest
from pathlib import Path


class RunAllForecastsScriptTest(unittest.TestCase):
    def test_batch_runner_includes_future_forecast_before_comparison(self):
        script_path = Path(__file__).resolve().parents[2] / "run-forecasts.sh"
        lines = script_path.read_text(encoding="utf-8").splitlines()
        commands = [line.strip() for line in lines if line.strip().startswith("run_forecast_step ") and ".py" in line]

        self.assertEqual(
            [
                'run_forecast_step "weekly-persistence $current_target" python3 main.py "${common_args[@]}" --save',
                'run_forecast_step "default-openstef-xgboost $current_target" python3 default_openstef_xgboost.py "${common_args[@]}"',
                'run_forecast_step "tuned-openstef-xgboost $current_target" python3 tuned_openstef.py "${common_args[@]}"',
            ],
            commands[:3],
        )
        self.assertEqual(
            'run_forecast_step "openstef-lgbm $current_target" python3 lgbm_openstef.py "${common_args[@]}"',
            commands[3],
        )
        self.assertEqual(
            'run_forecast_step "custom-openstef $current_target" python3 custom_openstef.py "${common_args[@]}"',
            commands[4],
        )
        self.assertEqual(
            'run_forecast_step "compare-window $current_target" python3 compare_forecasts.py --base-url "$base_url" --target "$current_target" --forecast-start "$forecast_start" --forecast-end "$forecast_end"',
            commands[5],
        )
        self.assertEqual(
            'run_forecast_step "compare-all-saved $current_target" python3 compare_forecasts.py --base-url "$base_url" --target "$current_target" --all-saved',
            commands[6],
        )

    def test_batch_runner_exposes_shared_forecast_window_options(self):
        script_path = Path(__file__).resolve().parents[2] / "run-forecasts.sh"
        script = script_path.read_text(encoding="utf-8")

        self.assertIn('--forecast-start ISO', script)
        self.assertIn('--forecast-days DAYS', script)
        self.assertIn('next-quarter-hour', script)
        self.assertIn('export PYTHONUNBUFFERED=1', script)
        self.assertIn('--base-url URL', script)
        self.assertIn('common_args=(--base-url "$base_url" --target "$current_target" --train-days "$train_days" --forecast-start "$forecast_start" --forecast-days "$forecast_days")', script)
        self.assertIn('common_args+=(--train-start "$train_start")', script)
        self.assertIn('FORECAST_COMPARE_ALL_SAVED=1', script)
        self.assertIn('FORECAST_RUN_LGBM=1', script)
        self.assertIn('FORECAST_RUN_ENSEMBLE=1', script)
        self.assertIn('if is_enabled "$run_lgbm"; then', script)
        self.assertIn('if is_enabled "$run_ensemble"; then', script)
        self.assertIn('if is_enabled "$compare_all_saved"; then', script)

    def test_legacy_batch_runner_delegates_to_forecast_runner(self):
        script_path = Path(__file__).resolve().parents[2] / "run-all-forecasts.sh"
        script = script_path.read_text(encoding="utf-8")

        self.assertIn('exec "$SCRIPT_DIR/run-forecasts.sh" "$@"', script)

    def test_reproducible_suite_uses_static_windows_and_all_models(self):
        script_path = Path(__file__).resolve().parents[2] / "run-reproducible-forecast-suite.sh"
        script = script_path.read_text(encoding="utf-8")

        self.assertIn('if [ "$#" -ne 0 ]; then', script)
        self.assertIn('BACKTEST_FORECAST_START="2026-06-11T21:15:00Z"', script)
        self.assertIn('FUTURE_FORECAST_START="2026-09-08T11:15:00Z"', script)
        self.assertIn('FORECAST_RUN_LGBM=1', script)
        self.assertIn('FORECAST_RUN_ENSEMBLE=1', script)
        self.assertIn('quantile_calibrated_xgboost.py --base-url "$BASE_URL" --target generation', script)
        self.assertIn('quantile_calibrated_xgboost.py --base-url "$BASE_URL" --target consumption', script)
        self.assertIn('export_forecast_metrics.py --base-url "$BASE_URL" --target generation', script)
        self.assertIn('export_forecast_metrics.py --base-url "$BASE_URL" --target consumption', script)


if __name__ == "__main__":
    unittest.main()
