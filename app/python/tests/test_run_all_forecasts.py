import unittest
from pathlib import Path


class RunAllForecastsScriptTest(unittest.TestCase):
    def test_batch_runner_includes_future_forecast_before_comparison(self):
        script_path = Path(__file__).resolve().parents[2] / "run-all-forecasts.sh"
        lines = script_path.read_text(encoding="utf-8").splitlines()
        commands = [line.strip() for line in lines if line.strip().startswith("python3 ") and ".py" in line]

        self.assertEqual(
            [
                'python3 main.py "${common_args[@]}" --save',
                'python3 default_openstef_xgboost.py "${common_args[@]}"',
                'python3 tuned_openstef.py "${common_args[@]}"',
                'python3 custom_openstef.py "${common_args[@]}"',
                'python3 compare_forecasts.py --target "$current_target" --forecast-start "$forecast_start" --forecast-end "$forecast_end"',
                'python3 compare_forecasts.py --target "$current_target" --all-saved',
            ],
            commands,
        )

    def test_batch_runner_exposes_shared_forecast_window_options(self):
        script_path = Path(__file__).resolve().parents[2] / "run-all-forecasts.sh"
        script = script_path.read_text(encoding="utf-8")

        self.assertIn('--forecast-start ISO', script)
        self.assertIn('--forecast-days DAYS', script)
        self.assertIn('next-quarter-hour', script)
        self.assertIn('common_args=(--target "$current_target" --train-days "$train_days" --forecast-start "$forecast_start" --forecast-days "$forecast_days")', script)
        self.assertIn('common_args+=(--train-start "$train_start")', script)


if __name__ == "__main__":
    unittest.main()
