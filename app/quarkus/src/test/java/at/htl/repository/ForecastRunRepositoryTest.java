package at.htl.repository;

import at.htl.model.ForecastComparisonPoint;
import at.htl.model.ForecastMetric;
import at.htl.model.ForecastPoint;
import at.htl.model.ForecastRunRequest;
import com.influxdb.v3.client.Point;
import com.influxdb.v3.client.write.WriteOptions;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.time.Instant;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;

class ForecastRunRepositoryTest {

    @Test
    void buildComparisonSqlFiltersByRunIdAndLimit() throws Exception {
        ForecastRunRepository repository = new ForecastRunRepository();
        setField(repository, "forecastMeasurement", "energy_forecasts");

        String sql = repository.buildComparisonSql("run-1", 96);

        assertEquals("SELECT time, forecast_kwh, actual_kwh, error_kwh FROM \"energy_forecasts\" WHERE run_id = 'run-1' ORDER BY time ASC LIMIT 96", sql);
    }

    @Test
    void buildComparisonSqlEscapesRunId() throws Exception {
        ForecastRunRepository repository = new ForecastRunRepository();
        setField(repository, "forecastMeasurement", "energy_forecasts");

        String sql = repository.buildComparisonSql("run'1", 1);

        assertEquals("SELECT time, forecast_kwh, actual_kwh, error_kwh FROM \"energy_forecasts\" WHERE run_id = 'run''1' ORDER BY time ASC LIMIT 1", sql);
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
    void toMetadataPointMapsRunMetadata() throws Exception {
        ForecastRunRepository repository = new ForecastRunRepository();
        setField(repository, "metadataMeasurement", "forecast_run_metadata");

        Point point = repository.toMetadataPoint(validRequest());

        assertEquals("forecast_run_metadata", point.getMeasurement());
        assertEquals("run-1", point.getTag("run_id"));
        assertEquals("consumption", point.getTag("target"));
        assertEquals("historical-average", point.getTag("model"));
        assertEquals("2026-01-01T00:00:00Z", point.getStringField("generated_at"));
        assertEquals("2025-11-01T00:00:00Z", point.getStringField("train_start"));
        assertEquals("2025-12-01T00:00:00Z", point.getStringField("train_end"));
        assertEquals("2025-12-01T00:00:00Z", point.getStringField("forecast_start"));
        assertEquals("2025-12-02T00:00:00Z", point.getStringField("forecast_end"));
        assertEquals("PT15M", point.getStringField("sample_interval"));
        assertEquals("simple-benchmark", point.getStringField("model_family"));
        assertEquals("app/reports/forecast-runs/forecast-backtest-report.md", point.getStringField("report_path"));
    }

    @Test
    void writeOptionsUseConfiguredGzipThreshold() throws Exception {
        ForecastRunRepository repository = new ForecastRunRepository();
        setField(repository, "gzipThresholdBytes", 1);

        WriteOptions options = repository.writeOptions();

        assertEquals(1, getField(options, "gzipThreshold"));
    }

    private void setField(Object target, String name, Object value) throws Exception {
        Field field = target.getClass().getDeclaredField(name);
        field.setAccessible(true);
        field.set(target, value);
    }

    private Object getField(Object target, String name) throws Exception {
        Field field = target.getClass().getDeclaredField(name);
        field.setAccessible(true);
        return field.get(target);
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
                null,
                "simple-benchmark",
                "app/reports/forecast-runs/forecast-backtest-report.md",
                List.of(new ForecastPoint(Instant.parse("2025-12-01T00:00:00Z"), 12.5, 12.0)),
                List.of(new ForecastMetric("mae_kwh", 0.5))
        );
    }
}
