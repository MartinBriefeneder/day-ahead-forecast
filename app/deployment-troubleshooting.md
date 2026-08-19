# Deployment Troubleshooting

## InfluxDB Exit Code 132

If the `influxdb` container exits and restarts repeatedly, inspect the exit status:

```sh
docker inspect -f '{{.State.ExitCode}} {{.State.OOMKilled}} {{.State.Error}}' influxdb
```

Exit code `132` means the process terminated with `SIGILL`:

- GNU Bash documents fatal signal exit status as `128 + signal_number`.
- Linux `signal(7)` lists `SIGILL` as signal `4` and describes it as `Illegal Instruction`.
- `128 + 4 = 132`.

For this project, that means the InfluxDB process is crashing. It is not only slow to start, and it is not caused by `influxdb-init`. If this happens only on one server, the likely cause is that the server CPU does not support an instruction used by the InfluxDB binary.

Useful checks on the server:

```sh
docker compose ps --all
docker compose logs --no-color --timestamps --tail=200 influxdb
docker inspect -f '{{.State.ExitCode}} {{.State.OOMKilled}} {{.State.Error}}' influxdb
uname -m
lscpu
```

The main Compose file pins InfluxDB 3 Core to `influxdb:3.10.1-core` and uses `restart: on-failure:5` so this failure remains visible.

## InfluxDB 2.7 Trial

Use `docker-compose.influxdb2-trial.yaml` to check whether InfluxDB 2.7 starts on the server CPU:

```sh
docker compose -f docker-compose.influxdb2-trial.yaml up influxdb2-trial
```

Check the result:

```sh
docker compose -f docker-compose.influxdb2-trial.yaml ps --all
docker compose -f docker-compose.influxdb2-trial.yaml logs --no-color --timestamps --tail=200 influxdb2-trial
```

This is only a container compatibility trial. InfluxDB 2.7 is not a drop-in replacement for the current backend because the app currently uses the InfluxDB 3 setup and query/write workflow.

Sources:

- GNU Bash manual, `Exit Status`: https://www.gnu.org/software/bash/manual/html_node/Exit-Status.html
- Linux man-pages, `signal(7)`: https://man7.org/linux/man-pages/man7/signal.7.html
- InfluxDB OSS v2 Docker Compose setup: https://docs.influxdata.com/influxdb/v2/install/use-docker-compose/
