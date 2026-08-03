# Quarkus Backend

This backend is the API and import service for the local forecast app.

It uses Java 21, Quarkus, and InfluxDB 3.

The backend can:

- import and validate historical energy CSV files.
- write quarter-hour energy values to InfluxDB.
- serve forecast datasets at `GET /api/forecast-datasets`.
- save forecast runs at `POST /api/forecast-runs`.
- compare a forecast run with actual values at `GET /api/forecast-runs/{runId}/comparison`.

Run all commands in this file from `app/quarkus`.

## Requirements

- Java 21
- Local InfluxDB from the Docker stack when the backend reads or writes data
- `INFLUXDB_TOKEN` with access to the local `energy` database

## Start Dev Mode

Start only the backend in Quarkus dev mode:

```bash
./mvnw -Denergy.influx.token="$INFLUXDB_TOKEN" quarkus:dev
```

Use `../run-dev.sh` if you also need InfluxDB, Grafana, and InfluxDB Explorer.

Quarkus Dev UI is available only in dev mode:

```text
http://localhost:8080/q/dev/
```

## Run Tests

Run all backend unit tests:

```bash
./mvnw test
```

Run one test class:

```bash
./mvnw -Dtest=EnergyCsvImportServiceTest test
```

## Build And Run

Build the backend:

```bash
./mvnw package
```

The build writes the runnable app to `target/quarkus-app/`.

Run the built app:

```bash
java -Denergy.influx.token="$INFLUXDB_TOKEN" -jar target/quarkus-app/quarkus-run.jar
```

## Import CSV Files

For normal local imports, use the reset script:

```bash
../reset-and-import-data.sh
```

Use direct backend command mode only when you do not need the reset script:

```bash
./mvnw package
java -Denergy.influx.token="$INFLUXDB_TOKEN" \
  -Denergy.import.command.directory=data/csv_Archiv \
  -jar target/quarkus-app/quarkus-run.jar
```

The backend imports all `.csv` files in the directory.

It exits when the import is complete.

## Validate CSV Files

Build the backend first:

```bash
./mvnw package
```

Generate a CSV validation report:

```bash
java -Denergy.validation.input=data/csv_Archiv \
  -Denergy.validation.report=target/energy-csv-validation-report.md \
  -jar target/quarkus-app/quarkus-run.jar
```

The command writes the report to `target/energy-csv-validation-report.md`.

It exits with status `1` if validation finds errors.

## Configuration

The default backend configuration is in `src/main/resources/application.properties`.

Important properties:

- `energy.influx.url`
- `energy.influx.database`
- `energy.influx.measurement`
- `energy.influx.forecast-measurement`
- `energy.influx.forecast-evaluation-measurement`
- `energy.influx.token`
