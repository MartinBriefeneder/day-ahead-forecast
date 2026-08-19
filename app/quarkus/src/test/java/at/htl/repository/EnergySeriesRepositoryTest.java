package at.htl.repository;

import at.htl.model.DirectionType;
import at.htl.model.ForecastDatasetValue;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.time.Duration;
import java.time.Instant;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class EnergySeriesRepositoryTest {

    @Test
    void buildForecastDatasetFluxAggregatesTotalByTimeAndDirection() throws Exception {
        EnergySeriesRepository repository = new EnergySeriesRepository();
        setField(repository, "measurement", "energy_values");
        setField(repository, "bucket", "energy");

        String flux = repository.buildForecastDatasetFlux(
                DirectionType.CONSUMPTION,
                Instant.parse("2025-06-01T00:00:00Z"),
                Instant.parse("2025-06-02T00:00:00Z")
        );

        assertEquals("from(bucket: \"energy\") |> range(start: time(v: \"2025-06-01T00:00:00Z\"), stop: time(v: \"2025-06-02T00:00:00Z\")) |> filter(fn: (r) => r[\"_measurement\"] == \"energy_values\") |> filter(fn: (r) => r[\"_field\"] == \"value_kwh\") |> filter(fn: (r) => r[\"direction\"] == \"CONSUMPTION\") |> filter(fn: (r) => r[\"category\"] == \"total\") |> group(columns: [\"_time\"]) |> sum(column: \"_value\") |> group() |> sort(columns: [\"_time\"])", flux);
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

    @Test
    void buildForecastDatasetWindowsSplitsRangeIntoHalfOpenChunks() throws Exception {
        EnergySeriesRepository repository = new EnergySeriesRepository();
        setField(repository, "forecastDatasetQueryWindow", Duration.ofDays(1));

        List<EnergySeriesRepository.TimeWindow> windows = repository.buildForecastDatasetWindows(
                Instant.parse("2025-06-01T00:00:00Z"),
                Instant.parse("2025-06-03T06:00:00Z")
        );

        assertEquals(3, windows.size());
        assertEquals(Instant.parse("2025-06-01T00:00:00Z"), windows.get(0).from());
        assertEquals(Instant.parse("2025-06-02T00:00:00Z"), windows.get(0).to());
        assertEquals(Instant.parse("2025-06-02T00:00:00Z"), windows.get(1).from());
        assertEquals(Instant.parse("2025-06-03T00:00:00Z"), windows.get(1).to());
        assertEquals(Instant.parse("2025-06-03T00:00:00Z"), windows.get(2).from());
        assertEquals(Instant.parse("2025-06-03T06:00:00Z"), windows.get(2).to());
    }

    @Test
    void resolvedWriteBatchSizeRejectsNonPositiveValues() throws Exception {
        EnergySeriesRepository repository = new EnergySeriesRepository();
        setField(repository, "writeBatchSize", 0);

        IllegalStateException exception = assertThrows(IllegalStateException.class, repository::resolvedWriteBatchSize);

        assertEquals("energy.influx.write-batch-size must be positive", exception.getMessage());
    }

    private void setField(Object target, String name, Object value) throws Exception {
        Field field = target.getClass().getDeclaredField(name);
        field.setAccessible(true);
        field.set(target, value);
    }

}
