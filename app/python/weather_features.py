from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests

APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WEATHER_PATH = APP_ROOT / "data/raw/Historical data Wetter(1).xlsx"
WEATHER_SHEET_NAME = "Données"
LOCAL_TIMEZONE = "Europe/Vienna"
SAMPLE_FREQUENCY = "15min"


@dataclass(frozen=True)
class WeatherFeature:
    name: str
    source_column: str
    unit: str
    description: str


@dataclass(frozen=True)
class WeatherFeatureDataset:
    data: pd.DataFrame
    metadata: dict


WEATHER_FEATURES: dict[str, WeatherFeature] = {
    "shortwave_radiation": WeatherFeature(
        name="shortwave_radiation",
        source_column="all_sky_global_horizontal_irradiance",
        unit="W/m2",
        description="All-sky global horizontal irradiance from the historical weather file; equivalent to forecast ghi.",
    ),
    "temperature_2m": WeatherFeature(
        name="temperature_2m",
        source_column="2m_temperature",
        unit="degC",
        description="Air temperature at 2 m.",
    ),
    "relative_humidity_2m": WeatherFeature(
        name="relative_humidity_2m",
        source_column="2m_relative_humidity",
        unit="%",
        description="Relative humidity at 2 m.",
    ),
    "wind_speed_10m": WeatherFeature(
        name="wind_speed_10m",
        source_column="10m_wind_speed",
        unit="m/s",
        description="Wind speed at 10 m.",
    ),
    "surface_pressure": WeatherFeature(
        name="surface_pressure",
        source_column="surface_pressure",
        unit="hPa",
        description="Surface pressure.",
    ),
}
DEFAULT_WEATHER_FEATURES = tuple(WEATHER_FEATURES)
GRIDOO_FORECAST_URL = "https://datahub.gridoo.com/v1/weather/{location_id}"
DEFAULT_GRIDOO_LOCATION_ID = 4
GRIDOO_VARIABLES = {
    "shortwave_radiation": ("ghi", "W/m2"),
    "direct_normal_irradiance": ("dni", "W/m2"),
    "diffuse_horizontal_irradiance": ("dhi", "W/m2"),
    "temperature_2m": ("temperature", "degC"),
    "wind_speed_10m": ("windspeed", "m/s"),
    "wind_direction_10m": ("winddirection", "deg"),
}
DEFAULT_GRIDOO_WEATHER_FEATURES = tuple(GRIDOO_VARIABLES)


def load_weather_features(
    path: str | Path | None = None,
    requested_features: Iterable[str] | None = None,
    source_timezone: str = LOCAL_TIMEZONE,
    sheet_name: str = WEATHER_SHEET_NAME,
) -> WeatherFeatureDataset:
    feature_names = _requested_feature_names(requested_features)
    weather_path = _weather_path(path)
    frame = _read_weather_workbook(weather_path, sheet_name)
    return normalize_weather_features(
        frame,
        requested_features=feature_names,
        source_timezone=source_timezone,
        source_path=weather_path,
        sheet_name=sheet_name,
    )


def inspect_weather_source(
    path: str | Path | None = None,
    source_timezone: str = LOCAL_TIMEZONE,
    sheet_name: str = WEATHER_SHEET_NAME,
) -> dict:
    weather_path = _weather_path(path)
    frame = _read_weather_workbook(weather_path, sheet_name)
    return inspect_weather_frame(
        frame,
        source_timezone=source_timezone,
        source_path=weather_path,
        sheet_name=sheet_name,
    )


def normalize_weather_features(
    frame: pd.DataFrame,
    requested_features: Iterable[str] | None = None,
    source_timezone: str = LOCAL_TIMEZONE,
    source_path: str | Path | None = None,
    sheet_name: str = WEATHER_SHEET_NAME,
) -> WeatherFeatureDataset:
    feature_names = _requested_feature_names(requested_features)
    source_columns = _source_columns_for(feature_names)
    missing_columns = [column for column in source_columns if column not in frame.columns]
    if missing_columns:
        raise ValueError(
            "Weather source is missing source column(s): "
            + ", ".join(missing_columns)
            + ". Available columns: "
            + ", ".join(map(str, frame.columns))
        )

    timestamps = _parse_timestamp_column(frame)
    utc_timestamps = _to_utc(timestamps, source_timezone)
    valid_timestamps = utc_timestamps.notna()

    data = frame.loc[valid_timestamps, source_columns].copy()
    data.columns = feature_names
    data = data.apply(pd.to_numeric, errors="coerce")
    data.index = pd.DatetimeIndex(utc_timestamps.loc[valid_timestamps], name="timestamp")
    data = data.sort_index()

    metadata = inspect_weather_frame(
        frame,
        source_timezone=source_timezone,
        source_path=source_path,
        sheet_name=sheet_name,
    )
    metadata["normalizedFeatureNames"] = list(feature_names)
    metadata["droppedTimestampRows"] = int((~valid_timestamps).sum())
    metadata["utcDuplicateTimestampCount"] = int(data.index.duplicated(keep=False).sum())
    metadata["utcMissingTimestampCount"], metadata["utcMissingTimestampExamples"] = _missing_timestamp_summary(
        data.index
    )

    return WeatherFeatureDataset(data=data, metadata=metadata)


def inspect_weather_frame(
    frame: pd.DataFrame,
    source_timezone: str = LOCAL_TIMEZONE,
    source_path: str | Path | None = None,
    sheet_name: str = WEATHER_SHEET_NAME,
) -> dict:
    timestamps = _parse_timestamp_column(frame)
    parsed_timestamps = timestamps.dropna()
    duplicate_count, duplicate_examples = _duplicate_timestamp_summary(parsed_timestamps)
    missing_count, missing_examples = _missing_timestamp_summary(parsed_timestamps)
    ambiguous_count, ambiguous_examples = _dst_timestamp_summary(parsed_timestamps, source_timezone, "ambiguous")
    nonexistent_count, nonexistent_examples = _dst_timestamp_summary(parsed_timestamps, source_timezone, "nonexistent")

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "sourcePath": str(source_path) if source_path is not None else None,
        "sheetName": sheet_name,
        "rowCount": int(len(frame)),
        "columnCount": int(len(frame.columns)),
        "columns": [str(column) for column in frame.columns],
        "timestampColumn": "timestamp",
        "sourceTimezoneAssumption": source_timezone,
        "timestampParseFailureCount": int(timestamps.isna().sum()),
        "localStart": _format_timestamp(parsed_timestamps.min()) if not parsed_timestamps.empty else None,
        "localEnd": _format_timestamp(parsed_timestamps.max()) if not parsed_timestamps.empty else None,
        "resolution": _resolution_summary(parsed_timestamps),
        "duplicateTimestampCount": duplicate_count,
        "duplicateTimestampExamples": duplicate_examples,
        "missingTimestampCount": missing_count,
        "missingTimestampExamples": missing_examples,
        "ambiguousDstTimestampCount": ambiguous_count,
        "ambiguousDstTimestampExamples": ambiguous_examples,
        "nonexistentDstTimestampCount": nonexistent_count,
        "nonexistentDstTimestampExamples": nonexistent_examples,
        "features": [asdict(feature) for feature in WEATHER_FEATURES.values()],
        "unresolvedQuestions": [
            "The workbook does not contain explicit provider metadata.",
            "The workbook does not contain explicit timezone metadata; Europe/Vienna is used for local alignment.",
            "The workbook does not contain dni, dhi, or wind direction fields from the Gridoo forecast interface.",
        ],
    }


def align_weather_features(
    weather: WeatherFeatureDataset | pd.DataFrame,
    target_index: pd.DatetimeIndex,
    requested_features: Iterable[str] | None = None,
    require_complete: bool = False,
) -> tuple[pd.DataFrame, dict]:
    feature_names = _requested_feature_names(requested_features)
    data = weather.data if isinstance(weather, WeatherFeatureDataset) else weather
    missing_features = [feature for feature in feature_names if feature not in data.columns]
    if missing_features:
        raise ValueError(
            "Requested weather feature(s) are unavailable: "
            + ", ".join(missing_features)
            + ". Available weather features: "
            + ", ".join(map(str, data.columns))
        )
    if not data.index.is_unique:
        duplicate_examples = _format_index_examples(data.index[data.index.duplicated(keep=False)])
        raise ValueError(
            "Weather data contains duplicate UTC timestamps and cannot be aligned safely. "
            f"Examples: {', '.join(duplicate_examples)}"
        )

    utc_target_index = _utc_index(target_index)
    aligned = data.sort_index().reindex(utc_target_index)[list(feature_names)]
    missing_mask = aligned.isna().any(axis=1)
    diagnostics = {
        "targetIntervalCount": int(len(utc_target_index)),
        "weatherFeatureNames": list(feature_names),
        "alignedWeatherIntervalCount": int((~missing_mask).sum()),
        "missingWeatherIntervalCount": int(missing_mask.sum()),
        "missingWeatherTimestampExamples": _format_index_examples(aligned.index[missing_mask]),
        "missingWeatherValuesByFeature": {
            feature: int(aligned[feature].isna().sum()) for feature in feature_names
        },
        "unmatchedWeatherIntervalCount": _unmatched_weather_interval_count(data, utc_target_index),
    }

    if require_complete and diagnostics["missingWeatherIntervalCount"]:
        examples = ", ".join(diagnostics["missingWeatherTimestampExamples"])
        raise ValueError(
            "Weather alignment is incomplete: "
            f"{diagnostics['missingWeatherIntervalCount']} of {diagnostics['targetIntervalCount']} "
            f"target intervals have missing weather values. Examples: {examples}"
        )

    return aligned, diagnostics


def add_weather_features(
    energy_data: pd.DataFrame,
    path: str | Path | None = None,
    requested_features: Iterable[str] | None = None,
    source_timezone: str = LOCAL_TIMEZONE,
    sheet_name: str = WEATHER_SHEET_NAME,
    require_complete: bool = False,
) -> tuple[pd.DataFrame, dict]:
    weather = load_weather_features(
        path=path,
        requested_features=requested_features,
        source_timezone=source_timezone,
        sheet_name=sheet_name,
    )
    aligned_weather, alignment_diagnostics = align_weather_features(
        weather,
        energy_data.index,
        requested_features=requested_features,
        require_complete=require_complete,
    )
    aligned_weather = aligned_weather.copy()
    aligned_weather.index = energy_data.index
    result = energy_data.copy()
    for column in aligned_weather.columns:
        result[column] = aligned_weather[column]

    diagnostics = {
        "source": weather.metadata,
        "alignment": alignment_diagnostics,
    }
    result.attrs["weather_diagnostics"] = diagnostics
    return result, diagnostics


def fetch_gridoo_forecast(
    *,
    start: datetime,
    end: datetime,
    location_id: int = DEFAULT_GRIDOO_LOCATION_ID,
    requested_features: Iterable[str] | None = None,
    timeout_seconds: int = 30,
    url: str = GRIDOO_FORECAST_URL,
) -> WeatherFeatureDataset:
    feature_names = _requested_gridoo_feature_names(requested_features)
    forecast_start = _utc_timestamp(start)
    forecast_end = _utc_timestamp(end)
    params = {
        "start": int(forecast_start.timestamp()),
        "end": int(forecast_end.timestamp()),
    }
    request_url = url.format(location_id=location_id)

    response = requests.get(request_url, params=params, timeout=timeout_seconds)
    response.raise_for_status()
    payload = response.json()
    data = _gridoo_frame(payload, feature_names)
    data = data[(data.index >= forecast_start) & (data.index < forecast_end)]
    metadata = {
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": "Gridoo Weather API",
        "sourceUrl": request_url,
        "locationId": location_id,
        "utcStart": forecast_start.isoformat().replace("+00:00", "Z"),
        "utcEnd": forecast_end.isoformat().replace("+00:00", "Z"),
        "featureNames": list(feature_names),
        "intervalCount": int(len(data)),
    }
    return WeatherFeatureDataset(data=data, metadata=metadata)


def _gridoo_frame(payload: list[dict] | dict, feature_names: Iterable[str]) -> pd.DataFrame:
    rows = payload
    if isinstance(payload, dict):
        rows = payload.get("data", payload.get("weather", []))
    if not isinstance(rows, list):
        raise ValueError("Gridoo response must be a JSON array or contain a weather data array")
    if not rows:
        return pd.DataFrame(columns=list(feature_names), index=pd.DatetimeIndex([], name="timestamp"))

    data = pd.DataFrame(rows)
    if "timestamp_iso" in data.columns:
        data["timestamp"] = pd.to_datetime(data["timestamp_iso"], utc=True, errors="coerce")
    elif "timestamp" in data.columns:
        data["timestamp"] = pd.to_datetime(data["timestamp"], unit="s", utc=True, errors="coerce")
    else:
        raise ValueError("Gridoo response does not contain timestamp or timestamp_iso values")
    for feature in feature_names:
        source_name = GRIDOO_VARIABLES[feature][0]
        if source_name not in data.columns:
            raise ValueError(f"Gridoo response is missing variable: {source_name}")
        data[feature] = pd.to_numeric(data[source_name], errors="coerce")

    data = data.dropna(subset=["timestamp"]).set_index("timestamp").sort_index()
    return data[list(feature_names)]


def _requested_gridoo_feature_names(requested_features: Iterable[str] | None) -> tuple[str, ...]:
    if requested_features is None:
        return DEFAULT_GRIDOO_WEATHER_FEATURES
    feature_names = tuple(requested_features)
    unsupported = [feature for feature in feature_names if feature not in GRIDOO_VARIABLES]
    if unsupported:
        raise ValueError(
            "Unsupported Gridoo weather feature(s): "
            + ", ".join(unsupported)
            + ". Supported features: "
            + ", ".join(GRIDOO_VARIABLES)
        )
    return feature_names


def _utc_timestamp(value: datetime) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _weather_path(path: str | Path | None) -> Path:
    weather_path = DEFAULT_WEATHER_PATH if path is None else Path(path)
    if not weather_path.exists():
        raise FileNotFoundError(f"Weather file not found: {weather_path}")
    return weather_path


def _read_weather_workbook(path: Path, sheet_name: str) -> pd.DataFrame:
    return pd.read_excel(path, sheet_name=sheet_name, engine="openpyxl")


def _requested_feature_names(requested_features: Iterable[str] | None) -> tuple[str, ...]:
    feature_names = tuple(requested_features or DEFAULT_WEATHER_FEATURES)
    unknown = [feature for feature in feature_names if feature not in WEATHER_FEATURES]
    if unknown:
        raise ValueError(
            "Unsupported weather feature(s): "
            + ", ".join(unknown)
            + ". Supported weather features: "
            + ", ".join(WEATHER_FEATURES)
        )
    return feature_names


def _source_columns_for(feature_names: Iterable[str]) -> list[str]:
    return [WEATHER_FEATURES[feature_name].source_column for feature_name in feature_names]


def _parse_timestamp_column(frame: pd.DataFrame) -> pd.Series:
    if "timestamp" not in frame.columns:
        raise ValueError("Weather source must contain a 'timestamp' column")
    return pd.to_datetime(frame["timestamp"], errors="coerce")


def _to_utc(timestamps: pd.Series, source_timezone: str) -> pd.Series:
    if timestamps.dt.tz is not None:
        return timestamps.dt.tz_convert("UTC")
    return timestamps.dt.tz_localize(source_timezone, ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC")


def _utc_index(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    utc_index = pd.DatetimeIndex(index)
    if utc_index.tz is None:
        raise ValueError("Energy dataset index must be timezone-aware before weather alignment")
    return utc_index.tz_convert("UTC")


def _resolution_summary(timestamps: pd.Series) -> dict:
    if timestamps.empty:
        return {"expected": SAMPLE_FREQUENCY, "mostCommon": None, "quarterHourAligned": False}
    unique_timestamps = pd.Series(pd.DatetimeIndex(timestamps).drop_duplicates().sort_values())
    diffs = unique_timestamps.diff().dropna()
    diff_seconds = diffs.dt.total_seconds()
    most_common = str(diffs.value_counts().idxmax()) if not diffs.empty else None
    return {
        "expected": SAMPLE_FREQUENCY,
        "mostCommon": most_common,
        "quarterHourAligned": bool((timestamps.dt.minute % 15 == 0).all()),
        "nonQuarterHourStepCount": int((diff_seconds != 15 * 60).sum()),
    }


def _duplicate_timestamp_summary(timestamps: pd.Series) -> tuple[int, list[str]]:
    duplicates = timestamps[timestamps.duplicated(keep=False)]
    return int(len(duplicates)), _format_timestamp_examples(duplicates)


def _missing_timestamp_summary(timestamps: pd.Series | pd.DatetimeIndex) -> tuple[int, list[str]]:
    index = pd.DatetimeIndex(timestamps).dropna().drop_duplicates().sort_values()
    if len(index) < 2:
        return 0, []
    full_index = pd.date_range(index.min(), index.max(), freq=SAMPLE_FREQUENCY, tz=index.tz)
    missing = full_index.difference(index)
    return int(len(missing)), _format_index_examples(missing)


def _dst_timestamp_summary(timestamps: pd.Series, source_timezone: str, problem: str) -> tuple[int, list[str]]:
    if timestamps.empty or timestamps.dt.tz is not None:
        return 0, []
    if problem == "ambiguous":
        localized = timestamps.dt.tz_localize(source_timezone, ambiguous="NaT", nonexistent="shift_forward")
    elif problem == "nonexistent":
        localized = timestamps.dt.tz_localize(source_timezone, ambiguous=False, nonexistent="NaT")
    else:
        raise ValueError(f"Unknown DST problem type: {problem}")
    problem_timestamps = timestamps[localized.isna()]
    return int(len(problem_timestamps)), _format_timestamp_examples(problem_timestamps)


def _unmatched_weather_interval_count(data: pd.DataFrame, target_index: pd.DatetimeIndex) -> int:
    if len(target_index) == 0 or data.empty:
        return 0
    within_target_range = data.loc[(data.index >= target_index.min()) & (data.index <= target_index.max())]
    return int(len(within_target_range.index.difference(target_index)))


def _format_timestamp(value: pd.Timestamp) -> str:
    return pd.Timestamp(value).isoformat()


def _format_timestamp_examples(values: pd.Series) -> list[str]:
    return [_format_timestamp(value) for value in values.dropna().head(8)]


def _format_index_examples(index: pd.Index) -> list[str]:
    return [_format_timestamp(value) for value in pd.DatetimeIndex(index).dropna().sort_values().unique()[:8]]

