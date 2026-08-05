from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from barebones_openstef import HORIZON, MODEL_NAME, SAMPLE_INTERVAL, WEATHER_FEATURES, create_barebones_workflow, parse_utc
from forecast_dataset_api import fetch_forecast_dataset
from forecast_runner import BASE_URL, DEFAULT_TARGET, DEFAULT_TRAIN_DAYS, DEFAULT_TRAIN_START, format_utc, require_positive_int
from persisted_model import DEFAULT_MODEL_ROOT, artifact_directory, openstef_feature_schema, openstef_metadata, write_artifact
from weather_features import DEFAULT_WEATHER_PATH


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train and persist a barebones OpenSTEF forecast model.")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--target", default=DEFAULT_TARGET, choices=("generation", "consumption"))
    parser.add_argument("--train-start", default=DEFAULT_TRAIN_START)
    parser.add_argument("--train-days", type=int, default=DEFAULT_TRAIN_DAYS)
    parser.add_argument("--weather-path", default=str(DEFAULT_WEATHER_PATH))
    parser.add_argument("--model-root", default=str(DEFAULT_MODEL_ROOT))
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    require_positive_int("train-days", args.train_days)

    train_start = parse_utc(args.train_start)
    train_end = train_start + timedelta(days=args.train_days)
    dataset = fetch_forecast_dataset(
        base_url=args.base_url,
        target=args.target,
        start=format_utc(train_start),
        end=format_utc(train_end),
        include_weather=True,
        weather_path=args.weather_path,
        weather_features=WEATHER_FEATURES,
        require_complete_weather=True,
    )
    dataset.data.attrs["target"] = args.target
    if dataset.data.empty:
        raise ValueError("Training dataset is empty. Check that imported energy data and weather data are available.")

    print(f"Training rows: {len(dataset.data):,}")
    workflow, config = create_barebones_workflow(args.target)
    workflow.fit(dataset)

    created_at = datetime.now(timezone.utc)
    artifact_dir = artifact_directory(args.model_root, target=args.target, model=MODEL_NAME, created_at=created_at)
    schema = openstef_feature_schema(target=args.target, weather_features=WEATHER_FEATURES, sample_interval=SAMPLE_INTERVAL)
    metadata = openstef_metadata(
        target=args.target,
        model=MODEL_NAME,
        model_family="openstef-xgboost",
        train_start=train_start,
        train_end=train_end,
        created_at=created_at,
        weather_path=args.weather_path,
        artifact_dir=artifact_dir,
        sample_interval=SAMPLE_INTERVAL,
        horizon=HORIZON,
        xgboost_hyperparameters=config.xgboost_hyperparams.model_dump(mode="json"),
    )
    write_artifact(artifact_dir, model=workflow, metadata=metadata, feature_schema=schema)
    print(f"Wrote model artifact to {artifact_dir}")


if __name__ == "__main__":
    main()
