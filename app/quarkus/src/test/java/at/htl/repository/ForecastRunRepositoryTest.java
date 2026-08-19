package at.htl.repository;

import at.htl.model.ForecastComparisonPoint;
import at.htl.model.ForecastDatasetTarget;
import at.htl.model.ForecastMetric;
import at.htl.model.ForecastPoint;
import at.htl.model.ForecastRunRequest;
import at.htl.model.ForecastRunSummary;
import com.influxdb.client.write.Point;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.time.Instant;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;

class ForecastRunRepositoryTest {

    @Test
    void buildComparisonFluxFiltersByRunIdAndLimit() throws Exception {
        ForecastRunRepository repository = new ForecastRunRepository();
        setField(repository, "forecastMeasurement", "energy_forecasts");
        setField(repository, "bucket", "energy");

        String flux = repository.buildComparisonFlux("run-1", 96);

        assertEquals("from(bucket: \"energy\") |> range(start: time(v: \"1970-01-01T00:00:00Z\")) |> filter(fn: (r) => r[\"_measurement\"] == \"energy_forecasts\") |> filter(fn: (r) => r[\"run_id\"] == \"run-1\") |> filter(fn: (r) => contains(value: r[\"_field\"], set: [\"forecast_kwh\", \"actual_kwh\", \"error_kwh\"])) |> pivot(rowKey: [\"_time\"], columnKey: [\"_field\"], valueColumn: \"_value\") |> group() |> sort(columns: [\"_time\"]) |> limit(n: 96)", flux);
    }

    @Test
    void buildComparisonFluxAllowsFourWeekQuarterHourLimit() throws Exception {
        ForecastRunRepository repository = new ForecastRunRepository();
        setField(repository, "forecastMeasurement", "energy_forecasts");
        setField(repository, "bucket", "energy");

        String flux = repository.buildComparisonFlux("run-1", 2688);

        assertEquals("from(bucket: \"energy\") |> range(start: time(v: \"1970-01-01T00:00:00Z\")) |> filter(fn: (r) => r[\"_measurement\"] == \"energy_forecasts\") |> filter(fn: (r) => r[\"run_id\"] == \"run-1\") |> filter(fn: (r) => contains(value: r[\"_field\"], set: [\"forecast_kwh\", \"actual_kwh\", \"error_kwh\"])) |> pivot(rowKey: [\"_time\"], columnKey: [\"_field\"], valueColumn: \"_value\") |> group() |> sort(columns: [\"_time\"]) |> limit(n: 2688)", flux);
    }

    @Test
    void buildComparisonFluxEscapesRunId() throws Exception {
        ForecastRunRepository repository = new ForecastRunRepository();
        setField(repository, "forecastMeasurement", "energy_forecasts");
        setField(repository, "bucket", "energy");

        String flux = repository.buildComparisonFlux("run\"1", 1);

        assertEquals("from(bucket: \"energy\") |> range(start: time(v: \"1970-01-01T00:00:00Z\")) |> filter(fn: (r) => r[\"_measurement\"] == \"energy_forecasts\") |> filter(fn: (r) => r[\"run_id\"] == \"run\\\"1\") |> filter(fn: (r) => contains(value: r[\"_field\"], set: [\"forecast_kwh\", \"actual_kwh\", \"error_kwh\"])) |> pivot(rowKey: [\"_time\"], columnKey: [\"_field\"], valueColumn: \"_value\") |> group() |> sort(columns: [\"_time\"]) |> limit(n: 1)", flux);
    }

    @Test
    void buildRunsFluxFiltersByTargetAndLimit() throws Exception {
        ForecastRunRepository repository = new ForecastRunRepository();
        setField(repository, "metadataMeasurement", "forecast_run_metadata");
        setField(repository, "bucket", "energy");

        String flux = repository.buildRunsFlux("generation", 25);

        assertEquals("from(bucket: \"energy\") |> range(start: time(v: \"1970-01-01T00:00:00Z\")) |> filter(fn: (r) => r[\"_measurement\"] == \"forecast_run_metadata\") |> filter(fn: (r) => contains(value: r[\"_field\"], set: [\"generated_at\", \"train_start\", \"train_end\", \"forecast_start\", \"forecast_end\", \"sample_interval\", \"horizon\", \"model_family\", \"report_path\"])) |> filter(fn: (r) => r[\"target\"] == \"generation\") |> pivot(rowKey: [\"_time\"], columnKey: [\"_field\"], valueColumn: \"_value\") |> group() |> sort(columns: [\"_time\"], desc: true) |> limit(n: 25)", flux);
    }

    @Test
    void buildRunsFluxAllowsAllTargets() throws Exception {
        ForecastRunRepository repository = new ForecastRunRepository();
        setField(repository, "metadataMeasurement", "forecast_run_metadata");
        setField(repository, "bucket", "energy");

        String flux = repository.buildRunsFlux(null, 10);

        assertEquals("from(bucket: \"energy\") |> range(start: time(v: \"1970-01-01T00:00:00Z\")) |> filter(fn: (r) => r[\"_measurement\"] == \"forecast_run_metadata\") |> filter(fn: (r) => contains(value: r[\"_field\"], set: [\"generated_at\", \"train_start\", \"train_end\", \"forecast_start\", \"forecast_end\", \"sample_interval\", \"horizon\", \"model_family\", \"report_path\"])) |> pivot(rowKey: [\"_time\"], columnKey: [\"_field\"], valueColumn: \"_value\") |> group() |> sort(columns: [\"_time\"], desc: true) |> limit(n: 10)", flux);
    }

    @Test
    void buildRunsFluxCanOmitMissingReportPath() throws Exception {
        ForecastRunRepository repository = new ForecastRunRepository();
        setField(repository, "metadataMeasurement", "forecast_run_metadata");
        setField(repository, "bucket", "energy");

        String flux = repository.buildRunsFlux("generation", 25, false);

        assertEquals("from(bucket: \"energy\") |> range(start: time(v: \"1970-01-01T00:00:00Z\")) |> filter(fn: (r) => r[\"_measurement\"] == \"forecast_run_metadata\") |> filter(fn: (r) => contains(value: r[\"_field\"], set: [\"generated_at\", \"train_start\", \"train_end\", \"forecast_start\", \"forecast_end\", \"sample_interval\", \"horizon\", \"model_family\"])) |> filter(fn: (r) => r[\"target\"] == \"generation\") |> pivot(rowKey: [\"_time\"], columnKey: [\"_field\"], valueColumn: \"_value\") |> group() |> sort(columns: [\"_time\"], desc: true) |> limit(n: 25)", flux);
    }

    @Test
    void buildRunFluxFiltersByRunId() throws Exception {
        ForecastRunRepository repository = new ForecastRunRepository();
        setField(repository, "metadataMeasurement", "forecast_run_metadata");
        setField(repository, "bucket", "energy");

        String flux = repository.buildRunFlux("run\"1", true);

        assertEquals("from(bucket: \"energy\") |> range(start: time(v: \"1970-01-01T00:00:00Z\")) |> filter(fn: (r) => r[\"_measurement\"] == \"forecast_run_metadata\") |> filter(fn: (r) => r[\"run_id\"] == \"run\\\"1\") |> filter(fn: (r) => contains(value: r[\"_field\"], set: [\"generated_at\", \"train_start\", \"train_end\", \"forecast_start\", \"forecast_end\", \"sample_interval\", \"horizon\", \"model_family\", \"report_path\"])) |> pivot(rowKey: [\"_time\"], columnKey: [\"_field\"], valueColumn: \"_value\") |> group() |> sort(columns: [\"_time\"], desc: true) |> limit(n: 1)", flux);
    }

    @Test
    void buildActualValuesFluxUsesTargetDirectionAndTotalCategory() throws Exception {
        ForecastRunRepository repository = new ForecastRunRepository();
        setField(repository, "actualMeasurement", "energy_values");
        setField(repository, "bucket", "energy");

        String flux = repository.buildActualValuesFlux(
                ForecastDatasetTarget.GENERATION,
                Instant.parse("2025-12-01T00:00:00Z"),
                Instant.parse("2025-12-02T00:00:00Z"),
                96
        );

        assertEquals("from(bucket: \"energy\") |> range(start: time(v: \"2025-12-01T00:00:00Z\"), stop: time(v: \"2025-12-02T00:00:00Z\")) |> filter(fn: (r) => r[\"_measurement\"] == \"energy_values\") |> filter(fn: (r) => r[\"_field\"] == \"value_kwh\") |> filter(fn: (r) => r[\"direction\"] == \"DELIVERY\") |> filter(fn: (r) => r[\"category\"] == \"total\") |> group(columns: [\"_time\"]) |> sum(column: \"_value\") |> group() |> sort(columns: [\"_time\"]) |> limit(n: 96)", flux);
    }

    @Test
    void toComparisonPointMapsNullableActualAndError() {
        ForecastRunRepository repository = new ForecastRunRepository();

        ForecastComparisonPoint point = repository.toComparisonPoint(new Object[]{"2025-12-01T00:00:00Z", 10.0, null, null});

        assertEquals(Instant.parse("2025-12-01T00:00:00Z"), point.timestamp());
        assertEquals(10.0, point.forecastKwh());
        assertEquals(null, point.actualKwh());
        assertEquals(null, point.errorKwh());
    }

    @Test
    void toRunSummaryMapsMetadataRow() {
        ForecastRunRepository repository = new ForecastRunRepository();

        ForecastRunSummary summary = repository.toRunSummary(new Object[]{
                "run-1",
                "historical-average",
                "consumption",
                "2026-01-01T00:00:00Z",
                "2025-11-01T00:00:00Z",
                "2025-12-01T00:00:00Z",
                "2025-12-01T00:00:00Z",
                "2025-12-02T00:00:00Z",
                "PT15M",
                "P14D",
                "simple-benchmark",
                "app/reports/forecast-runs/forecast-backtest-report.md"
        });

        assertEquals("run-1", summary.runId());
        assertEquals("historical-average", summary.model());
        assertEquals("consumption", summary.target());
        assertEquals(Instant.parse("2025-12-01T00:00:00Z"), summary.forecastStart());
        assertEquals("PT15M", summary.sampleInterval());
        assertEquals("P14D", summary.horizon());
    }

    @Test
    void toRunSummaryAllowsMissingReportPathColumn() {
        ForecastRunRepository repository = new ForecastRunRepository();

        ForecastRunSummary summary = repository.toRunSummary(new Object[]{
                "run-1",
                "historical-average",
                "consumption",
                "2026-01-01T00:00:00Z",
                "2025-11-01T00:00:00Z",
                "2025-12-01T00:00:00Z",
                "2025-12-01T00:00:00Z",
                "2025-12-02T00:00:00Z",
                "PT15M",
                "P14D",
                "simple-benchmark"
        });

        assertEquals(null, summary.reportPath());
    }

    @Test
    void isMissingTableExceptionRecognizesMetadataTable() {
        ForecastRunRepository repository = new ForecastRunRepository();
        RuntimeException exception = new RuntimeException("INVALID_ARGUMENT: Error while logically planning query: Error during planning: table 'public.iox.forecast_run_metadata' not found");

        assertEquals(true, repository.isMissingTableException(exception, "forecast_run_metadata"));
        assertEquals(false, repository.isMissingTableException(exception, "energy_forecasts"));
    }

    @Test
    void isMissingColumnExceptionRecognizesReportPath() {
        ForecastRunRepository repository = new ForecastRunRepository();
        RuntimeException exception = new RuntimeException("INVALID_ARGUMENT: Error while logically planning query: Schema error: No field named report_path. Valid fields are forecast_run_metadata.forecast_end");

        assertEquals(true, repository.isMissingColumnException(exception, "report_path"));
        assertEquals(false, repository.isMissingColumnException(exception, "model_family"));
    }

    @Test
    void toMetadataPointMapsRunMetadata() throws Exception {
        ForecastRunRepository repository = new ForecastRunRepository();
        setField(repository, "metadataMeasurement", "forecast_run_metadata");

        Point point = repository.toMetadataPoint(validRequest());
        String lineProtocol = point.toLineProtocol();

        assertEquals(true, lineProtocol.startsWith("forecast_run_metadata,"));
        assertEquals(true, lineProtocol.contains("run_id=run-1"));
        assertEquals(true, lineProtocol.contains("target=consumption"));
        assertEquals(true, lineProtocol.contains("model=historical-average"));
        assertEquals(true, lineProtocol.contains("generated_at=\"2026-01-01T00:00:00Z\""));
        assertEquals(true, lineProtocol.contains("train_start=\"2025-11-01T00:00:00Z\""));
        assertEquals(true, lineProtocol.contains("train_end=\"2025-12-01T00:00:00Z\""));
        assertEquals(true, lineProtocol.contains("forecast_start=\"2025-12-01T00:00:00Z\""));
        assertEquals(true, lineProtocol.contains("forecast_end=\"2025-12-02T00:00:00Z\""));
        assertEquals(true, lineProtocol.contains("sample_interval=\"PT15M\""));
        assertEquals(true, lineProtocol.contains("horizon=\"P14D\""));
        assertEquals(true, lineProtocol.contains("model_family=\"simple-benchmark\""));
        assertEquals(true, lineProtocol.contains("report_path=\"app/reports/forecast-runs/forecast-backtest-report.md\""));
    }

    private void setField(Object target, String name, Object value) throws Exception {
        Field field = target.getClass().getDeclaredField(name);
        field.setAccessible(true);
        field.set(target, value);
    }

    private ForecastRunRequest validRequest() {
        return new ForecastRunRequest(
                "run-1",
                "historical-average",
                "consumption",
                Instant.parse("2026-01-01T00:00:00Z"),
                Instant.parse("2025-11-01T00:00:00Z"),
                Instant.parse("2025-12-01T00:00:00Z"),
                Instant.parse("2025-12-01T00:00:00Z"),
                Instant.parse("2025-12-02T00:00:00Z"),
                "PT15M",
                "P14D",
                "simple-benchmark",
                "app/reports/forecast-runs/forecast-backtest-report.md",
                List.of(new ForecastPoint(Instant.parse("2025-12-01T00:00:00Z"), 12.5, 12.0)),
                List.of(new ForecastMetric("mae_kwh", 0.5))
        );
    }
}
