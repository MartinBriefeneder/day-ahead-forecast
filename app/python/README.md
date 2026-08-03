# Forecast Experiments

This directory contains Python forecast runners.

The runners read historical energy data from the Quarkus backend.

Some runners add local historical weather features from the workbook in `data/raw/`.

Run commands from `app/python` except when a command shows another directory.

## Set Up Python

Create or update the local virtual environment from `requirements.txt`:

```bash
cd app/python
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run The Simple Benchmark Backtest

Start the local services and Quarkus first. Then run:

```bash
../run-forecast.sh
```

The script creates `.venv` when it is missing.

It installs the requirements and runs `main.py`.

The runner has no command-line arguments.

Change the constants at the top of `main.py` if you need another target or date window.

This runner tests energy-only benchmark models.

The runner writes these files under `app/reports/forecast-runs/`:

- `<target>-historical-average-<forecast-start>.json`
- `<target>-weekly-persistence-<forecast-start>.json`
- `forecast-backtest-report.md`
- `forecast-backtest-dashboard.html`

Use `ensemble.py` for the OpenSTEF baseline and ensemble experiment.

## Run The Barebones OpenSTEF Forecast

Start the local services and Quarkus first. Then run:

```bash
../run-barebones-openstef.sh --target generation
```

The barebones runner fetches energy data from the backend.

It joins local historical weather features, trains one default OpenSTEF XGBoost workflow, writes reports, creates a comparison plot, and sends the forecast run to the backend.

Useful options:

- `--target generation`
- `--target consumption`
- `--train-start 2025-06-11T00:00:00Z`
- `--train-days 90`
- `--forecast-days 7`

Example:

```bash
../run-barebones-openstef.sh --target consumption --train-days 60 --forecast-days 3
```

The runner writes these files under `app/reports/forecast-runs/`:

- `<target>-openstef-barebones-<forecast-start>.json`
- `openstef-barebones-metadata.json`
- `openstef-barebones-report.md`
- `openstef-barebones-comparison.html`

## Run The Tuned OpenSTEF Forecast

Start the local services and Quarkus first. Then run:

```bash
../run-tuned-openstef.sh --target generation --n-trials 10
```

The tuned runner fetches energy data from the backend.

It joins local historical weather features, trains one default OpenSTEF XGBoost workflow, runs Optuna tuning, trains the tuned workflow, writes reports, creates a comparison plot, and sends both forecast runs to the backend.

Useful options:

- `--target generation`
- `--target consumption`
- `--train-start 2025-06-11T00:00:00Z`
- `--train-days 90`
- `--forecast-days 7`
- `--n-trials 10`
- `--no-progress`

The runner writes these files under `app/reports/forecast-runs/`:

- `<target>-openstef-xgboost-default-<forecast-start>.json`
- `<target>-openstef-xgboost-tuned-<forecast-start>.json`
- `openstef-xgboost-tuning-metadata.json`
- `openstef-xgboost-tuning-report.md`
- `openstef-xgboost-forecast-comparison.html`

## Use Local Historical Weather

Weather features use only this local workbook:

```text
data/raw/Historical data Wetter(1).xlsx
```

The weather code does not call WeatherAPI or another external weather service.

Generate the weather inspection report:

```bash
cd app/python
source .venv/bin/activate
python weather_features.py inspect --output ../reports/weather-inspection-report.md
```

The command writes Markdown and JSON reports.

The loader maps source columns to names that match OpenSTEF:

| Source column | Feature | Unit |
|---|---|---|
| `all_sky_global_horizontal_irradiance` | `shortwave_radiation` | `W/m2` |
| `2m_temperature` | `temperature_2m` | `degC` |
| `2m_relative_humidity` | `relative_humidity_2m` | `%` |
| `10m_wind_speed` | `wind_speed_10m` | `m/s` |
| `surface_pressure` | `surface_pressure` | `hPa` |

Weather use is optional.

`fetch_forecast_dataframe()` and `fetch_forecast_dataset()` keep energy-only behavior until the caller sets `include_weather=True`.

Weather diagnostics are stored in `DataFrame.attrs["weather_diagnostics"]`.

Known limits:

- The workbook timestamps have no timezone offset. The local loader assumes `Europe/Vienna` and converts timestamps to UTC.
- Ambiguous and nonexistent daylight-saving timestamps are reported and excluded. The loader does not guess or interpolate these timestamps.
- The local weather range starts on 2025-06-11. Experiments before that date must disable weather or handle missing weather diagnostics.

## Run Tests

Run the Python tests:

```bash
cd app/python
source .venv/bin/activate
python -m unittest discover -s tests
```
