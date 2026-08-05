import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from persisted_model import (
    artifact_directory,
    load_artifact,
    openstef_feature_schema,
    openstef_metadata,
    safe_name,
    validate_required_columns,
    write_artifact,
)


class PersistedModelTest(unittest.TestCase):
    def test_safe_name_replaces_unsafe_characters(self):
        self.assertEqual("openstef-barebones", safe_name("OpenSTEF Barebones"))

    def test_artifact_directory_contains_target_model_and_timestamp(self):
        with TemporaryDirectory() as directory:
            path = artifact_directory(
                directory,
                target="generation",
                model="openstef-barebones",
                created_at=datetime(2026, 8, 5, 12, tzinfo=timezone.utc),
            )

        self.assertEqual("generation-openstef-barebones-20260805T120000Z", path.name)

    def test_write_and_load_artifact_roundtrip(self):
        with TemporaryDirectory() as directory:
            artifact_dir = Path(directory) / "model-1"
            write_artifact(
                artifact_dir,
                model={"model": "stub"},
                metadata={"target": "generation"},
                feature_schema={"requiredColumns": ["generation"]},
            )

            model, metadata, schema = load_artifact(artifact_dir)

        self.assertEqual({"model": "stub"}, model)
        self.assertEqual({"target": "generation"}, metadata)
        self.assertEqual({"requiredColumns": ["generation"]}, schema)

    def test_validate_required_columns_reports_missing_columns(self):
        with self.assertRaisesRegex(ValueError, "shortwave_radiation"):
            validate_required_columns(["generation"], {"requiredColumns": ["generation", "shortwave_radiation"]})

    def test_openstef_feature_schema_uses_target_and_weather_features(self):
        schema = openstef_feature_schema(
            target="generation",
            weather_features=("temperature_2m", "shortwave_radiation"),
            sample_interval="PT15M",
        )

        self.assertEqual(["generation", "temperature_2m", "shortwave_radiation"], schema["requiredColumns"])
        self.assertEqual("PT15M", schema["sampleInterval"])

    def test_openstef_metadata_contains_reuse_fields(self):
        metadata = openstef_metadata(
            target="generation",
            model="openstef-barebones",
            model_family="openstef-xgboost",
            train_start=datetime(2025, 6, 11, tzinfo=timezone.utc),
            train_end=datetime(2025, 9, 9, tzinfo=timezone.utc),
            created_at=datetime(2026, 8, 5, 12, tzinfo=timezone.utc),
            weather_path="weather.xlsx",
            artifact_dir=Path("/tmp/model-1"),
            sample_interval="PT15M",
            horizon="PT36H",
            xgboost_hyperparameters={"max_depth": 3},
        )

        self.assertEqual("openstef-barebones", metadata["model"])
        self.assertEqual("/tmp/model-1", metadata["artifactPath"])
        self.assertEqual({"max_depth": 3}, metadata["xgboostHyperparameters"])


if __name__ == "__main__":
    unittest.main()
