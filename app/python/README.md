# Forecast Experiments

This directory contains Python forecast runners.

The runners read historical energy data from the Quarkus backend.

Some runners add observed historical weather features from the workbook in `app/data/raw/`.

Run commands from `app/python` except when a command shows another directory.

## Set Up Python

Create or update the local virtual environment from `requirements.txt`:

```bash
cd app/python
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run The Simple Benchmark Forecast

Start the local services and Quarkus first. Then run:

```bash
source .venv/bin/activate
python main.py
```

The command uses the existing `.venv` and runs `main.py`.

The runner supports these useful options:

- `--target consumption`
- `--target generation`
- `--train-start 2025-06-01T00:00:00Z`
- `--train-days 90`
- `--forecast-start 2025-12-01T00:00:00Z`
- `--forecast-weeks 2`

This runner tests the energy-only `weekly-persistence` benchmark model.

When `--forecast-start` is set, the training window defaults to the previous `--train-days`. This keeps the InfluxDB query narrow.

It writes only the local HTML report.

Example for a two-week expected consumption forecast:

```bash
python main.py --target consumption --forecast-start 2025-12-01T00:00:00Z --forecast-weeks 2
```

The runner writes this file under `app/reports/forecast-runs/`:

- `forecast-backtest-dashboard.html`

The dashboard contains quarter-hour forecast values and daily and weekly expected-energy totals.

## Run The Default OpenSTEF XGBoost Forecast

Start the local services and Quarkus first. Then run:

```bash
source .venv/bin/activate
python default_openstef_xgboost.py --target generation
```

The default OpenSTEF XGBoost runner fetches energy data from the backend.

It joins local observed historical weather features, trains one default OpenSTEF XGBoost workflow, creates a comparison plot, and sends the forecast run to the backend.

Useful options:

- `--target generation`
- `--target consumption`
- `--train-start 2025-06-11T00:00:00Z`
- `--train-days 90`
- `--forecast-days 7`

Example:

```bash
python default_openstef_xgboost.py --target consumption --train-days 60 --forecast-days 3
```

The runner writes this file under `app/reports/forecast-runs/`:

- `openstef-default-xgboost-comparison.html`

## Run The Tuned OpenSTEF Forecast

Start the local services and Quarkus first. Then run:

```bash
source .venv/bin/activate
python tuned_openstef.py --target generation --n-trials 10
```

The tuned runner fetches energy data from the backend.

It joins local observed historical weather features, trains one default OpenSTEF XGBoost workflow, runs Optuna tuning, trains the tuned workflow, creates a comparison plot, and sends both forecast runs to the backend.

Useful options:

- `--target generation`
- `--target consumption`
- `--train-start 2025-06-11T00:00:00Z`
- `--train-days 90`
- `--forecast-days 7`
- `--n-trials 10`
- `--no-progress`

The runner writes this file under `app/reports/forecast-runs/`:

- `openstef-xgboost-forecast-comparison.html`

## Run The Custom OpenSTEF Ensemble Forecast

Start the local services and Quarkus first. Then run:

```bash
source .venv/bin/activate
python custom_openstef.py --target generation
```

The custom runner uses OpenSTEF's `EnsembleForecastingWorkflowConfig` extension point.

It joins local observed historical weather features, trains a configurable ensemble, creates a comparison plot, and sends the forecast run to the backend.

Useful options:

- `--target generation`
- `--target consumption`
- `--base-models lgbm,gblinear`
- `--combiner-model lgbm`
- `--ensemble-type learned_weights`
- `--train-start 2025-06-11T00:00:00Z`
- `--train-days 90`
- `--forecast-days 7`

The runner writes this file under `app/reports/forecast-runs/`:

- `openstef-custom-ensemble-comparison.html`

`ensemble.py` remains as a compatibility wrapper for `custom_openstef.py`.

## Use Weather Features

Historical weather features use this local workbook of observed actual weather values:

```text
app/data/raw/Historical data Wetter(1).xlsx
```

No active forecast runner currently calls the Gridoo Weather API. The Gridoo field mapping remains documented for a later OpenSTEF future-forecast workflow.

The historical loader maps source columns to names that match OpenSTEF:

| Source column | Feature | Unit |
|---|---|---|
| `all_sky_global_horizontal_irradiance` | `shortwave_radiation` | `W/m2` |
| `2m_temperature` | `temperature_2m` | `degC` |
| `2m_relative_humidity` | `relative_humidity_2m` | `%` |
| `10m_wind_speed` | `wind_speed_10m` | `m/s` |
| `surface_pressure` | `surface_pressure` | `hPa` |

The Gridoo forecast loader maps provider fields to the same internal feature names where possible:

| Gridoo field | Feature | Unit |
|---|---|---|
| `ghi` | `shortwave_radiation` | `W/m2` |
| `dni` | `direct_normal_irradiance` | `W/m2` |
| `dhi` | `diffuse_horizontal_irradiance` | `W/m2` |
| `temperature` | `temperature_2m` | `degC` |
| `windspeed` | `wind_speed_10m` | `m/s` |
| `winddirection` | `wind_direction_10m` | `deg` |

Historical `all_sky_global_horizontal_irradiance` corresponds to Gridoo forecast `ghi`; both become `shortwave_radiation`.

Weather use is optional.

`fetch_forecast_dataframe()` and `fetch_forecast_dataset()` keep energy-only behavior until the caller sets `include_weather=True`.

Weather diagnostics are stored in `DataFrame.attrs["weather_diagnostics"]`.

Known limits:

- The workbook timestamps have no timezone offset. The local loader assumes `Europe/Vienna` and converts timestamps to UTC.
- Ambiguous and nonexistent daylight-saving timestamps are reported and excluded. The loader does not guess or interpolate these timestamps.
- The local weather range starts on 2025-06-11. Experiments before that date must disable weather or handle missing weather diagnostics.
- The documented Gridoo forecast endpoint starts at `2026-06-22T10:00:00Z`.

## Run Tests

Run the Python tests:

```bash
cd app/python
source .venv/bin/activate
python -m unittest discover -s tests
```
