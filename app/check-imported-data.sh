#!/usr/bin/env bash
set -euo pipefail

script_dir="$(CDPATH= cd "$(dirname "$0")" && pwd)"
cd "$script_dir"

if [ -f ./.env ]; then
  set -a
  . ./.env
  set +a
fi

csv_directory="${ENERGY_IMPORT_DIRECTORY:-./quarkus/data/csv_Archiv}"
measurement="${ENERGY_INFLUX_MEASUREMENT:-energy_values}"
report_dir="${ENERGY_DATA_CHECK_REPORT_DIR:-./reports/data-check}"
build_mode="${ENERGY_DATA_CHECK_BUILD:-auto}"
wait_seconds="${INFLUX_WAIT_SECONDS:-60}"

usage() {
  printf 'Usage: %s [csv-directory]\n' "$0"
  printf 'Checks that imported InfluxDB energy_values match the CSV parser output.\n'
  printf 'Requires INFLUXDB_TOKEN in the environment or app/.env.\n'
  printf 'Set ENERGY_DATA_CHECK_BUILD=0 to skip backend image build checks.\n'
}

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  usage
  exit 0
fi

if [ "${1:-}" != "" ]; then
  csv_directory="$1"
fi

if [ ! -d "$csv_directory" ]; then
  printf '[data-check] CSV import directory does not exist: %s\n' "$csv_directory" >&2
  exit 1
fi

: "${INFLUXDB_TOKEN:?set INFLUXDB_TOKEN in the environment or app/.env before running the data check}"
: "${INFLUXDB_ORG:=kirchdorf}"
: "${INFLUXDB_BUCKET:=energy}"
export INFLUXDB_TOKEN INFLUXDB_ORG INFLUXDB_BUCKET

mkdir -p "$report_dir"
import_dir="$(realpath "$csv_directory")"
report_dir_abs="$(realpath "$report_dir")"
validation_report="$report_dir_abs/energy-csv-validation-report.md"
overall_count_csv="$report_dir_abs/influx-energy-values-count.csv"
breakdown_count_csv="$report_dir_abs/influx-energy-values-direction-category-count.csv"

wait_for_influx() {
  local attempts
  attempts=0
  until docker compose exec -T influxdb influx ping --host http://localhost:8086 >/dev/null 2>&1; do
    attempts=$((attempts + 1))
    if [ "$attempts" -ge "$wait_seconds" ]; then
      printf '[data-check] timed out waiting for InfluxDB after %s seconds\n' "$wait_seconds" >&2
      exit 1
    fi
    sleep 1
  done
}

should_build_backend() {
  case "$build_mode" in
    1|true|yes|always)
      return 0
      ;;
    0|false|no|never|skip)
      return 1
      ;;
    auto)
      ! docker image inspect day-ahead-forecast-backend >/dev/null 2>&1
      return
      ;;
    *)
      printf '[data-check] invalid ENERGY_DATA_CHECK_BUILD value: %s. Use auto, 1, or 0.\n' "$build_mode" >&2
      exit 1
      ;;
  esac
}

flux_literal() {
  python3 - "$1" <<'PY'
import json
import sys

print(json.dumps(sys.argv[1]))
PY
}

run_validation_report() {
  printf '[data-check] validate CSV parser output from %s\n' "$import_dir"
  docker compose --profile import run --rm \
    --volume "$import_dir:/import-data:ro" \
    --volume "$report_dir_abs:/check-output" \
    --entrypoint /bin/sh \
    importer \
    -c 'java -Dquarkus.http.host=127.0.0.1 -Dquarkus.http.port=0 -Denergy.validation.input=/import-data -Denergy.validation.report=/check-output/energy-csv-validation-report.md -jar /deployments/quarkus-run.jar'
}

parse_expected_value() {
  python3 - "$validation_report" "$1" <<'PY'
import re
import sys

path, label = sys.argv[1], sys.argv[2]
pattern = re.compile(rf"^- {re.escape(label)}: (.+)$")
with open(path, encoding="utf-8") as report:
    for line in report:
        match = pattern.match(line.strip())
        if match:
            print(match.group(1))
            raise SystemExit(0)
raise SystemExit(f"Could not find '{label}' in {path}")
PY
}

query_influx() {
  local flux
  local output
  flux="$1"
  output="$2"
  docker compose exec -T influxdb influx query \
    --host http://localhost:8086 \
    --org "$INFLUXDB_ORG" \
    --token "$INFLUXDB_TOKEN" \
    --raw \
    "$flux" > "$output"
}

compare_counts() {
  python3 - "$expected_series" "$expected_categories" "$overall_count_csv" "$breakdown_count_csv" <<'PY'
import csv
import sys

expected_total = int(sys.argv[1])
expected_groups = int(sys.argv[2])
overall_path = sys.argv[3]
breakdown_path = sys.argv[4]


def records(path):
    header = None
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.reader(handle):
            if not row or row[0].startswith("#"):
                continue
            if "_value" in row:
                header = row
                continue
            if header:
                yield dict(zip(header, row))


overall_records = list(records(overall_path))
actual_total = 0
if overall_records:
    actual_total = int(float(overall_records[-1].get("_value") or 0))

breakdown = []
for record in records(breakdown_path):
    direction = record.get("direction") or ""
    category = record.get("category") or ""
    count = int(float(record.get("_value") or 0))
    breakdown.append((direction, category, count))

failures = []
if actual_total != expected_total:
    failures.append(f"total rows mismatch: expected {expected_total}, actual {actual_total}")

if expected_groups <= 0:
    failures.append(f"invalid expected category count: {expected_groups}")
elif expected_total % expected_groups != 0:
    failures.append(f"expected total {expected_total} is not divisible by expected group count {expected_groups}")
else:
    expected_per_group = expected_total // expected_groups
    if len(breakdown) != expected_groups:
        failures.append(f"direction/category group count mismatch: expected {expected_groups}, actual {len(breakdown)}")
    for direction, category, count in sorted(breakdown):
        if count != expected_per_group:
            failures.append(
                f"{direction}/{category} count mismatch: expected {expected_per_group}, actual {count}"
            )

print(f"[data-check] expected rows from CSV parser: {expected_total}")
print(f"[data-check] actual rows in InfluxDB: {actual_total}")
print("[data-check] actual direction/category counts:")
for direction, category, count in sorted(breakdown):
    print(f"[data-check]   {direction}/{category}: {count}")

if failures:
    print("[data-check] FAIL")
    for failure in failures:
        print(f"[data-check]   {failure}")
    raise SystemExit(1)

print("[data-check] PASS: imported InfluxDB rows match the CSV parser output")
PY
}

printf '[data-check] start InfluxDB if needed\n'
docker compose up -d influxdb
wait_for_influx

if should_build_backend; then
  printf '[data-check] build backend image\n'
  docker compose --profile import build importer
fi

run_validation_report
expected_series="$(parse_expected_value "Series parsed")"
validation_errors="$(parse_expected_value "Errors")"
expected_categories="$(parse_expected_value "Categories")"

if [ "$validation_errors" != "0" ]; then
  printf '[data-check] CSV validation reported %s error(s). See %s\n' "$validation_errors" "$validation_report" >&2
  exit 1
fi

bucket_literal="$(flux_literal "$INFLUXDB_BUCKET")"
measurement_literal="$(flux_literal "$measurement")"

printf '[data-check] count imported rows in InfluxDB bucket=%s measurement=%s\n' "$INFLUXDB_BUCKET" "$measurement"
query_influx "from(bucket: ${bucket_literal}) |> range(start: time(v: \"1970-01-01T00:00:00Z\"), stop: time(v: \"2100-01-01T00:00:00Z\")) |> filter(fn: (r) => r[\"_measurement\"] == ${measurement_literal}) |> filter(fn: (r) => r[\"_field\"] == \"value_kwh\") |> group() |> count()" "$overall_count_csv"

printf '[data-check] count imported rows by direction and category\n'
query_influx "from(bucket: ${bucket_literal}) |> range(start: time(v: \"1970-01-01T00:00:00Z\"), stop: time(v: \"2100-01-01T00:00:00Z\")) |> filter(fn: (r) => r[\"_measurement\"] == ${measurement_literal}) |> filter(fn: (r) => r[\"_field\"] == \"value_kwh\") |> group(columns: [\"direction\", \"category\"]) |> count()" "$breakdown_count_csv"

compare_counts

printf '[data-check] reports written to %s\n' "$report_dir_abs"
