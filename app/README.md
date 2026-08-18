# Day-Ahead Forecast App Setup

This directory contains the local application stack.

The expected server setup is Windows Server with WSL and Docker support.

## Required Software In WSL

Install these packages in the WSL Linux distribution:

```bash
sudo apt update
sudo apt install -y git ca-certificates curl
```

Install Docker Desktop on Windows and enable WSL integration for the Linux distribution.

Check Docker from WSL:

```bash
docker --version
docker compose version
```

If you want to run the backend in Quarkus dev mode, install Java 21 in WSL:

```bash
sudo apt install -y openjdk-21-jdk
```

If you want to run forecast experiments, install Python support in WSL:

```bash
sudo apt install -y python3 python3-venv python3-pip
```

## Recommended Project Location

Clone or unpack the project inside the WSL filesystem, for example under `~/projects/`.

Avoid running the project from `/mnt/c/...`. Docker bind mounts and builds are slower there.

## Ports

These ports must be free on the server:

- `8080`: Quarkus backend
- `3000`: Grafana
- `8180`: InfluxDB Explorer
- `8181`: InfluxDB 3 Core

## Environment

The shell scripts use a shared local InfluxDB demo token by default.

To override it, create `app/.env` with this value:

```bash
cd app
printf '%s\n' 'INFLUXDB_TOKEN=your-token-here' > .env
```

The scripts also accept an already exported `INFLUXDB_TOKEN`.

## First Run

Run these commands from this `app/` directory:

```bash
./reset-and-import-data.sh
./run-server.sh
```

The import can take some time because it rebuilds the backend image and writes CSV data to InfluxDB.

Open these URLs after the stack starts:

- Backend: <http://localhost:8080>
- Grafana: <http://localhost:3000>
- InfluxDB Explorer: <http://localhost:8180>

## Development Mode

Use this command when you want Docker services plus a local Quarkus dev server:

```bash
./run-dev.sh
```

This requires Java 21 in WSL.

## Forecast Experiments

Start the backend first with `./run-server.sh` or `./run-dev.sh`.

Then run all forecast experiments:

```bash
./run-all-forecasts.sh
```

These commands create `app/python/.venv` if needed and install `app/python/requirements.txt`.

Weather-based forecast code needs outbound internet access to the Gridoo Weather API.

Historical weather experiments need this local workbook:

```text
app/data/raw/Historical data Wetter(1).xlsx
```

## Useful Maintenance Commands

Delete stored forecast results but keep imported actual values:

```bash
./reset-forecasts.sh
```

Start the full Docker backend stack again:

```bash
./run-server.sh
```
