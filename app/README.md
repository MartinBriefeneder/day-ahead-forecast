## Local Development

- Start InfluxDB, Grafana, and the backend: `./run-dev.sh`
- Reset the local `energy` database and import the historical CSV files: `./reset-and-import-data.sh`
- Reset/import a different CSV directory: `./reset-and-import-data.sh ../path/to/csv-directory`

## Boss Server Demo

Use this on the Windows/WSL server when Quarkus should run as a Docker container instead of Maven dev mode:

```bash
cd app
./run-server.sh
```

This packages the Quarkus backend, builds the backend image from `quarkus/Dockerfile`, and starts `influxdb`, `grafana`, and `backend` through `docker-compose.yaml` plus `docker-compose.backend.yaml`.

The backend is available at `http://localhost:8080`; Grafana is available at `http://localhost:3000`.

To inspect the effective compose config manually:

```bash
export INFLUXDB_TOKEN=$(sed -n 's/.*"token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' influxdb/admin-token.json)
docker compose -f docker-compose.yaml -f docker-compose.backend.yaml config
```

## Local Forecast Experiments

The Python forecast runner lives in `python/` and consumes the Quarkus forecast dataset API.

- Baseline backtest: `./run-forecast.sh --target consumption --train-days 200 --forecast-days 7`
- Include weather alignment: `./run-forecast.sh --target generation --weather-file "../data/raw/Historical data Wetter(1).xlsx"`
- Persist forecast values and evaluation metrics to InfluxDB through Quarkus: `./run-forecast.sh --persist --run-id-prefix meeting-demo`

The command requires the local services and Quarkus backend to be running first. Reports are written to `app/reports/forecast-runs/` by default. See `python/README.md` for model options and current limitations.
