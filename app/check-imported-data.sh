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
expected_file_counts_tsv="$report_dir_abs/expected-file-counts.tsv"
file_count_dir="$report_dir_abs/influx-file-counts"

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
    --user "$(id -u):$(id -g)" \
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

write_expected_file_counts() {
  python3 - "$validation_report" "$expected_file_counts_tsv" <<'PY'
from datetime import datetime, timedelta, timezone
import csv
import re
import sys

report_path, output_path = sys.argv[1], sys.argv[2]
files = []
current = None

def parse_int(value):
    return int(value.strip())

def parse_instant(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc)

with open(report_path, encoding="utf-8") as report:
    for raw_line in report:
        line = raw_line.strip()
        match = re.match(r"^### (.+)$", line)
        if match:
            current = {"file": match.group(1)}
            files.append(current)
            continue
        if current is None or not line.startswith("- ") or ": " not in line:
            continue
        label, value = line[2:].split(": ", 1)
        if label == "Data rows parsed":
            current["data_rows"] = parse_int(value)
        elif label == "Series parsed":
            current["series_count"] = parse_int(value)
        elif label == "First timestamp (UTC instant)":
            current["first"] = value
        elif label == "Last timestamp (UTC instant)":
            current["last"] = value
        elif label == "Metering points":
            current["metering_points"] = parse_int(value)

with open(output_path, "w", newline="", encoding="utf-8") as output:
    fieldnames = ["file", "start", "stop", "series_count", "expected_group_count", "expected_per_group"]
    writer = csv.DictWriter(output, fieldnames=fieldnames, delimiter="\t")
    writer.writeheader()
    for file in files:
        required = ["file", "first", "last", "series_count", "data_rows", "metering_points"]
        missing = [name for name in required if name not in file]
        if missing:
            raise SystemExit(f"Validation report file summary is missing {missing}: {file}")
        row_meter_count = file["data_rows"] * file["metering_points"]
        if row_meter_count <= 0 or file["series_count"] % row_meter_count != 0:
            raise SystemExit(f"Cannot derive expected group count for {file['file']}")
        start = parse_instant(file["first"])
        stop = parse_instant(file["last"]) + timedelta(minutes=15)
        writer.writerow({
            "file": file["file"],
            "start": start.isoformat().replace("+00:00", "Z"),
            "stop": stop.isoformat().replace("+00:00", "Z"),
            "series_count": file["series_count"],
            "expected_group_count": file["series_count"] // row_meter_count,
            "expected_per_group": row_meter_count,
        })
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

query_file_counts() {
  local file
  local start
  local stop
  local output

  rm -rf "$file_count_dir"
  mkdir -p "$file_count_dir"

  while IFS=$'\t' read -r file start stop _series_count _expected_group_count _expected_per_group; do
    if [ "$file" = "file" ]; then
      continue
    fi
    output="$file_count_dir/$file.counts.csv"
    printf '[data-check] count imported rows for %s\n' "$file"
    query_influx "from(bucket: ${bucket_literal}) |> range(start: time(v: \"${start}\"), stop: time(v: \"${stop}\")) |> filter(fn: (r) => r[\"_measurement\"] == ${measurement_literal}) |> filter(fn: (r) => r[\"_field\"] == \"value_kwh\") |> group(columns: [\"direction\", \"category\"]) |> count()" "$output"
  done < "$expected_file_counts_tsv"
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
print(f"[data-check] row difference: {expected_total - actual_total}")
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

compare_file_counts() {
  python3 - "$expected_file_counts_tsv" "$file_count_dir" <<'PY'
import csv
from pathlib import Path
import sys

expected_path = Path(sys.argv[1])
actual_dir = Path(sys.argv[2])


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


failures = []
print("[data-check] per-file count summary:")
with open(expected_path, newline="", encoding="utf-8") as expected_file:
    for expected in csv.DictReader(expected_file, delimiter="\t"):
        file_name = expected["file"]
        expected_total = int(expected["series_count"])
        expected_group_count = int(expected["expected_group_count"])
        expected_per_group = int(expected["expected_per_group"])
        actual_path = actual_dir / f"{file_name}.counts.csv"
        breakdown = []
        for record in records(actual_path):
            direction = record.get("direction") or ""
            category = record.get("category") or ""
            count = int(float(record.get("_value") or 0))
            breakdown.append((direction, category, count))
        actual_total = sum(count for _, _, count in breakdown)
        difference = expected_total - actual_total
        print(f"[data-check]   {file_name}: expected={expected_total} actual={actual_total} difference={difference}")
        if actual_total != expected_total:
            failures.append(f"{file_name} total rows mismatch: expected {expected_total}, actual {actual_total}")
        if len(breakdown) != expected_group_count:
            failures.append(
                f"{file_name} direction/category group count mismatch: expected {expected_group_count}, actual {len(breakdown)}"
            )
        for direction, category, count in sorted(breakdown):
            if count != expected_per_group:
                failures.append(
                    f"{file_name} {direction}/{category} count mismatch: expected {expected_per_group}, actual {count}"
                )

if failures:
    print("[data-check] per-file FAIL")
    for failure in failures[:30]:
        print(f"[data-check]   {failure}")
    if len(failures) > 30:
        print(f"[data-check]   ... {len(failures) - 30} more failure(s)")
    raise SystemExit(1)

print("[data-check] per-file PASS")
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

write_expected_file_counts

bucket_literal="$(flux_literal "$INFLUXDB_BUCKET")"
measurement_literal="$(flux_literal "$measurement")"

printf '[data-check] count imported rows in InfluxDB bucket=%s measurement=%s\n' "$INFLUXDB_BUCKET" "$measurement"
query_influx "from(bucket: ${bucket_literal}) |> range(start: time(v: \"1970-01-01T00:00:00Z\"), stop: time(v: \"2100-01-01T00:00:00Z\")) |> filter(fn: (r) => r[\"_measurement\"] == ${measurement_literal}) |> filter(fn: (r) => r[\"_field\"] == \"value_kwh\") |> group() |> count()" "$overall_count_csv"

printf '[data-check] count imported rows by direction and category\n'
query_influx "from(bucket: ${bucket_literal}) |> range(start: time(v: \"1970-01-01T00:00:00Z\"), stop: time(v: \"2100-01-01T00:00:00Z\")) |> filter(fn: (r) => r[\"_measurement\"] == ${measurement_literal}) |> filter(fn: (r) => r[\"_field\"] == \"value_kwh\") |> group(columns: [\"direction\", \"category\"]) |> count()" "$breakdown_count_csv"

query_file_counts

failed=0
if ! compare_counts; then
  failed=1
fi
if ! compare_file_counts; then
  failed=1
fi
if [ "$failed" -ne 0 ]; then
  exit 1
fi

printf '[data-check] reports written to %s\n' "$report_dir_abs"
