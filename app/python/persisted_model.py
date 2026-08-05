from __future__ import annotations

import json
import platform
import pickle
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from forecast_runner import format_utc


ARTIFACT_MODEL_FILE = "model.pkl"
ARTIFACT_METADATA_FILE = "metadata.json"
ARTIFACT_FEATURE_SCHEMA_FILE = "feature-schema.json"
DEFAULT_MODEL_ROOT = (Path(__file__).resolve().parent / "../models/forecast-models").resolve()


def artifact_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def artifact_directory(root: str | Path, *, target: str, model: str, created_at: datetime) -> Path:
    safe_target = safe_name(target)
    safe_model = safe_name(model)
    return Path(root).resolve() / f"{safe_target}-{safe_model}-{artifact_timestamp(created_at)}"


def safe_name(value: str) -> str:
    cleaned = "".join(character if character.isalnum() or character in "-_" else "-" for character in value.lower())
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    if not cleaned:
        raise ValueError("Artifact name part must contain at least one letter or number")
    return cleaned


def write_artifact(artifact_dir: Path, *, model: Any, metadata: dict[str, Any], feature_schema: dict[str, Any]) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=False)
    with (artifact_dir / ARTIFACT_MODEL_FILE).open("wb") as output:
        pickle.dump(model, output)
    write_json(artifact_dir / ARTIFACT_METADATA_FILE, metadata)
    write_json(artifact_dir / ARTIFACT_FEATURE_SCHEMA_FILE, feature_schema)


def load_artifact(artifact_dir: str | Path) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    resolved = Path(artifact_dir).resolve()
    if not resolved.is_dir():
        raise ValueError(f"Model artifact directory does not exist: {resolved}")

    model_path = resolved / ARTIFACT_MODEL_FILE
    metadata_path = resolved / ARTIFACT_METADATA_FILE
    feature_schema_path = resolved / ARTIFACT_FEATURE_SCHEMA_FILE
    for path in (model_path, metadata_path, feature_schema_path):
        if not path.is_file():
            raise ValueError(f"Model artifact file is missing: {path}")

    with model_path.open("rb") as input_file:
        model = pickle.load(input_file)
    return model, read_json(metadata_path), read_json(feature_schema_path)


def validate_required_columns(columns: list[str], feature_schema: dict[str, Any]) -> None:
    required_columns = list(feature_schema.get("requiredColumns", []))
    missing = [column for column in required_columns if column not in columns]
    if missing:
        raise ValueError(f"Prediction dataset is missing required columns: {', '.join(missing)}")


def openstef_feature_schema(*, target: str, weather_features: tuple[str, ...], sample_interval: str) -> dict[str, Any]:
    return {
        "targetColumn": target,
        "weatherFeatures": list(weather_features),
        "requiredColumns": [target, *weather_features],
        "sampleInterval": sample_interval,
    }


def openstef_metadata(
    *,
    target: str,
    model: str,
    model_family: str,
    train_start: datetime,
    train_end: datetime,
    created_at: datetime,
    weather_path: str,
    artifact_dir: Path,
    sample_interval: str,
    horizon: str,
    xgboost_hyperparameters: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = {
        "createdAt": format_utc(created_at),
        "target": target,
        "model": model,
        "modelFamily": model_family,
        "trainStart": format_utc(train_start),
        "trainEnd": format_utc(train_end),
        "sampleInterval": sample_interval,
        "horizon": horizon,
        "weatherPath": str(weather_path),
        "artifactPath": str(artifact_dir),
        "pythonVersion": platform.python_version(),
        "pandasVersion": pd.__version__,
    }
    if xgboost_hyperparameters is not None:
        metadata["xgboostHyperparameters"] = xgboost_hyperparameters
    if extra:
        metadata.update(extra)
    return metadata


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
