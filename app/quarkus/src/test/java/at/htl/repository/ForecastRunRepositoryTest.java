package at.htl.repository;

import at.htl.model.ForecastComparisonPoint;
import com.influxdb.v3.client.write.WriteOptions;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.time.Instant;

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
}
