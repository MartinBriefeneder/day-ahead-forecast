# Day-Ahead Forecast

## What You Need

- Git
- Docker

## Setup

```sh
git clone <repo-url> day-ahead-forecast
cd day-ahead-forecast/app
./run-server.sh
./reset-and-import-data.sh
docker compose --profile forecasts run --rm forecast-runner \
  --base-url http://forecast-backend:8080 \
  --target all \
  --forecast-start 2025-10-01T00:00:00Z \
  --forecast-days 7
```

This creates one week of saved generation and consumption forecasts.

For a historical backtest, choose a `--forecast-start` inside the imported CSV data range.

For a true future forecast, the weather forecast input must also be available. If the live weather step fails, the batch continues by default and still saves successful model runs.

Reports are written to `app/reports/forecast-runs/`.
Saved forecast runs are available through Grafana and the backend API.

## Start The App

```sh
cd app
./run-server.sh
```

Open:

- Backend: `http://localhost:8080`
- Grafana: `http://localhost:3000`
- InfluxDB: `http://localhost:8086`

## Import The CSV Data

```sh
cd app
./reset-and-import-data.sh
```

This resets the local InfluxDB bucket and imports `app/quarkus/data/csv_Archiv`.

## Run Forecasts

```sh
cd app
./run-forecasts.sh
```

Useful options:

```sh
./run-forecasts.sh --target generation
./run-forecasts.sh --target consumption
./run-forecasts.sh --forecast-days 7
```

## Run The Fixed Demo Suite

```sh
cd app
./scripts/run-fixed-window-forecast-suite.sh
```

This runs the saved live and backtest forecast windows.

## Check The Data Import

```sh
cd app
./scripts/check-imported-data.sh
```

## Run Tests

Backend tests:

```sh
cd app/quarkus
./mvnw test
```

Python tests, after you created `app/python/.venv` and installed `requirements.txt`:

```sh
cd app/python
.venv/bin/python -m unittest discover -s tests
```

## Reset Only Forecasts

```sh
cd app
./scripts/reset-forecasts.sh
```

This deletes stored forecasts but keeps imported actual energy values.

## Test Credentials

InfluxDB: `http://localhost:8086`

- Username: `admin`
- Password: `local-influxdb-password`
- Organization: `kirchdorf`
- Bucket: `energy`
- Token: `apiv3_OkmfXNXtBPcrAZHrJ-HT5Xs8_UpxwFJS2iwaG8Lv3Uioiy40hrk_75A0WFrLxd6E92T3jg7oSDLZUlITwcR0Hg`

Grafana: `http://localhost:3000`

- Dashboards work without login.
- If login is needed: `admin` / `admin`.
