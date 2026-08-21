import unittest
from datetime import datetime, timezone
from pathlib import Path

from compare_forecasts import build_parser, select_summaries
from forecast_runner import report_timestamp, timestamped_report_path


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

    def test_timestamped_report_path_adds_utc_timestamp_to_filename(self):
        path = timestamped_report_path(
            Path("reports"),
            "generation-all-python-forecast-comparison",
            generated_at=datetime(2026, 8, 21, 12, 34, 56, tzinfo=timezone.utc),
        )

        self.assertEqual(Path("reports/generation-all-python-forecast-comparison-20260821T123456Z.html"), path)
        self.assertEqual("20260821T123456Z", report_timestamp("2026-08-21T12:34:56Z"))


if __name__ == "__main__":
    unittest.main()
