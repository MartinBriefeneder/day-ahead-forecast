# Day-Ahead Forecast App

## Boss Server Demo

Use this on the Windows/WSL server. It only requires Docker Desktop with WSL integration. Java and Maven are handled inside the backend Docker build.

First start without importing data:

```bash
cd app
./setup-demo.sh
```

First start with the default historical CSV import, if `data/raw/csv_Archiv_6_2025_bis_5_2026` is present:

```bash
cd app
./setup-demo.sh --import
```

Use a different CSV directory:

```bash
cd app
./setup-demo.sh --import-dir ../path/to/csv-directory
```

For later starts after the import has already run:

```bash
cd app
./run-server.sh
```

The setup creates `app/influxdb/admin-token.json` automatically when missing, builds the Quarkus backend image from `quarkus/Dockerfile`, and starts `influxdb`, `grafana`, and `backend` through `docker-compose.yaml` plus `docker-compose.backend.yaml`.

- Backend: `http://localhost:8080`
- Grafana: `http://localhost:3000`
- InfluxDB: `http://localhost:8181`

## Local Development

- Start InfluxDB, Grafana, and the backend in Quarkus dev mode: `./run-dev.sh`
- Reset the local `energy` database and import the historical CSV files: `./reset-and-import-data.sh`
- Reset/import a different CSV directory: `./reset-and-import-data.sh ../path/to/csv-directory`

## Local Forecast Experiments

The Python forecast runner lives in `python/` and consumes the Quarkus forecast dataset API.

- Simple benchmark backtest: `./run-forecast.sh`
- The runner has no command-line arguments; adjust the constants at the top of `python/main.py` for local experiments.

`python/main.py` evaluates energy-only benchmark models. Use `python/ensemble.py` for the OpenSTEF baseline/ensemble experiment.

The command requires the local services and Quarkus backend to be running first. Reports are written to `app/reports/forecast-runs/` by default. See `python/README.md` for current limitations.
