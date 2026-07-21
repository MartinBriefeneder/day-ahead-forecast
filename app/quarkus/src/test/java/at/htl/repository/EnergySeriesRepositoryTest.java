package at.htl.repository;

import at.htl.model.DirectionType;
import at.htl.model.ForecastDatasetValue;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.time.Instant;

import static org.junit.jupiter.api.Assertions.assertEquals;

class EnergySeriesRepositoryTest {

    @Test
    void buildForecastDatasetSqlAggregatesTotalByTimeAndDirection() throws Exception {
        EnergySeriesRepository repository = new EnergySeriesRepository();
        setField(repository, "measurement", "energy_values");

        String sql = repository.buildForecastDatasetSql(
                DirectionType.CONSUMPTION,
                Instant.parse("2025-06-01T00:00:00Z"),
                Instant.parse("2025-06-02T00:00:00Z")
        );

        assertEquals("SELECT time, SUM(value_kwh) AS value FROM \"energy_values\" WHERE direction = 'CONSUMPTION' AND category = 'total' AND time >= '2025-06-01T00:00:00Z' AND time < '2025-06-02T00:00:00Z' GROUP BY time ORDER BY time ASC", sql);
    }

    @Test
    void toForecastDatasetValueMapsTimestampAndNumericValue() {
        EnergySeriesRepository repository = new EnergySeriesRepository();

        ForecastDatasetValue value = repository.toForecastDatasetValue(new Object[]{"2025-06-01T00:00:00Z", 12.5});

        assertEquals(Instant.parse("2025-06-01T00:00:00Z"), value.timestamp());
        assertEquals(12.5, value.value());
    }

    @Test
    void toForecastDatasetValueMapsEpochNanosecondTimestamp() {
        EnergySeriesRepository repository = new EnergySeriesRepository();

        ForecastDatasetValue value = repository.toForecastDatasetValue(new Object[]{1759276800000000000L, 24.72825});

        assertEquals(Instant.parse("2025-10-01T00:00:00Z"), value.timestamp());
        assertEquals(24.72825, value.value());
    }

    private void setField(Object target, String name, Object value) throws Exception {
        Field field = target.getClass().getDeclaredField(name);
        field.setAccessible(true);
        field.set(target, value);
    }
}
