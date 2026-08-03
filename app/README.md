# Day-Ahead Forecast App

Use this directory to run the local day-ahead forecast app.

The local stack uses Docker for InfluxDB 3 Core, Grafana, and InfluxDB Explorer.

The Quarkus backend can run in Maven dev mode or in Docker.

Run all commands in this file from the `app` directory.

## Requirements

- Docker with Docker Compose support
- Java 21 for Quarkus dev mode
- Python 3 for forecast experiments
- An InfluxDB admin token

## Set The InfluxDB Token

Create `.env` from the example file:

```bash
cp .env.example .env
```

The `.env` file must include this value:

```env
INFLUXDB_TOKEN=local-dev-token
```

You can also export `INFLUXDB_TOKEN` in your shell.

Do not commit `.env`.

## Start Local Development

Start the local services and the backend in Quarkus dev mode:

```bash
./run-dev.sh
```

The script starts these Docker services:

- InfluxDB 3 Core
- Grafana
- InfluxDB Explorer

The script does not start the backend container.

It starts the backend from `quarkus/` with `./mvnw quarkus:dev`.

## Reset And Import CSV Data

Use this command when you need a clean local `energy` database.

The script deletes the local database.

It creates the database again.

It builds the backend image and imports CSV files.

```bash
./reset-and-import-data.sh
```

The default import directory is `quarkus/data/csv_Archiv`.

Import another CSV directory:

```bash
./reset-and-import-data.sh ../path/to/csv-directory
```

## Start The Backend In Docker

Start the full local Docker stack, including the backend container:

```bash
./run-server.sh
```

The script enables the Compose `server` profile.

It builds the Quarkus backend image from `quarkus/Dockerfile`.

## Service URLs

- Backend: `http://localhost:8080`
- Grafana: `http://localhost:3000`
- InfluxDB: `http://localhost:8181`
- InfluxDB Explorer: `http://localhost:8180`

## Run Forecast Experiments

Start the local services and the backend first. Then run the simple forecast runner:

```bash
./run-forecast.sh
```

The script creates `python/.venv` when it is missing.

It installs `python/requirements.txt` and runs `python/main.py`.

The runner supports `--base-url`, `--output-dir`, and `--no-save`.

Change the constants at the top of `python/main.py` for local experiments.

The runner writes JSON, Markdown, and a Plotly HTML dashboard to `reports/forecast-runs/` by default.

It also saves forecast runs to the backend by default so they can be queried from InfluxDB and Grafana.

Use report-only mode when you do not want backend persistence:

```bash
./run-forecast.sh --no-save
```

The weather inspection command writes to `reports/weather-inspection-report.md`. It does not call an external weather API.

See `python/README.md` for Python runners and known limits.

## Troubleshooting

- If a script reports a missing token, create `.env` or export `INFLUXDB_TOKEN`.
- If startup times out, check that Docker is running and that the token is correct.
- If port `8080` is in use, stop the other local process that owns the port.
- If Grafana has no data, run `./reset-and-import-data.sh` and select a time range that the imported CSV files cover.
