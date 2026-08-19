import unittest

from main import backend_payload, build_parser, resolve_windows


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
            "metrics": {"mae_kwh": 0.5, "note": "ignored"},
            "points": [],
        }

        result = backend_payload(payload)

        self.assertEqual([{"name": "mae_kwh", "value": 0.5}], result["metrics"])

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

if __name__ == "__main__":
    unittest.main()
