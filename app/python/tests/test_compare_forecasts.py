import unittest

from compare_forecasts import build_parser, select_summaries


class CompareForecastsTest(unittest.TestCase):
    def test_parser_accepts_consumption_target(self):
        args = build_parser().parse_args(["--target", "consumption"])

        self.assertEqual("consumption", args.target)

    def test_select_summaries_keeps_target_groups_separate(self):
        summaries = [
            {
                "runId": "generation-run",
                "target": "generation",
                "model": "weekly-persistence",
                "forecastStart": "2025-12-01T00:00:00Z",
                "forecastEnd": "2025-12-02T00:00:00Z",
                "sampleInterval": "PT15M",
                "generatedAt": "2026-01-01T00:00:00Z",
            },
            {
                "runId": "consumption-run",
                "target": "consumption",
                "model": "weekly-persistence",
                "forecastStart": "2025-12-01T00:00:00Z",
                "forecastEnd": "2025-12-02T00:00:00Z",
                "sampleInterval": "PT15M",
                "generatedAt": "2026-01-01T00:00:00Z",
            },
        ]

        selected = select_summaries(summaries, target="consumption", forecast_start=None, forecast_end=None)

        self.assertEqual(["consumption-run"], [summary["runId"] for summary in selected])


if __name__ == "__main__":
    unittest.main()
