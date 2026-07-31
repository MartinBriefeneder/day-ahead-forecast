# Python Forecast Experiments

This folder contains local forecast experiments that consume the Quarkus forecast dataset API. The scripts do not read or modify raw CSV files directly.

## Dependencies

Create or update the local virtual environment from `requirements.txt`:

```bash
cd app/python
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Baseline Backtest

Start local services and Quarkus first, then run:

```bash
../run-forecast.sh --target consumption --train-days 200 --forecast-days 7
```

The default run evaluates two energy-only baselines:

- `historical-average`: mean value for the same weekday and quarter-hour in the training range.
- `weekly-persistence`: value from the same quarter-hour one week earlier, with historical average fallback.

The runner writes one JSON file per model plus `forecast-backtest-report.md` to `../reports/forecast-runs`.

## Weather Alignment

Use the historical weather workbook as optional input:

```bash
../run-forecast.sh --target generation --weather-file "../../data/raw/Historical data Wetter(1).xlsx"
```

The weather file is aligned to quarter-hour UTC timestamps and normalized to OpenSTEF-style feature names such as `temperature_2m`, `wind_speed_10m`, `shortwave_radiation`, `surface_pressure`, and `relative_humidity_2m`.

## Persistence

Use `--persist` to write forecast points and metrics back through the Quarkus API:

```bash
../run-forecast.sh --persist --run-id-prefix demo-run
```

Forecast values are stored separately from imported actual measurements so Grafana can compare forecast, actual, and error without modifying `energy_values`.

Use `--show-plot` to open the Plotly forecast-vs-actual chart. Use `--models historical-average`, `--models weekly-persistence`, or `--models openstef-xgboost` to select specific models. The OpenSTEF model requires weather columns.
