package at.htl.service;

import at.htl.model.DirectionType;
import at.htl.model.ForecastDatasetResponse;
import at.htl.model.ForecastDatasetValue;
import at.htl.repository.EnergySeriesRepository;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.time.Instant;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class ForecastDatasetServiceTest {

    @Test
    void loadDatasetUsesConsumptionDirectionAndMetadata() throws Exception {
        ForecastDatasetService service = serviceWithRepository(new StubRepository(List.of(
                new ForecastDatasetValue(Instant.parse("2025-06-01T00:00:00Z"), 10.0),
                new ForecastDatasetValue(Instant.parse("2025-06-01T00:15:00Z"), 11.5)
        )));

        ForecastDatasetResponse response = service.getDataset("load", "2025-06-01T00:00:00Z", "2025-06-02T00:00:00Z");

        assertEquals("PT15M", response.sampleInterval());
        assertEquals("load", response.targetColumn());
        assertEquals("kWh", response.unit());
        assertEquals(2, response.points().size());
    }

    @Test
    void generationDatasetUsesDeliveryDirection() throws Exception {
        StubRepository repository = new StubRepository(List.of());
        ForecastDatasetService service = serviceWithRepository(repository);

        service.getDataset("generation", "2025-06-01T00:00:00Z", "2025-06-02T00:00:00Z");

        assertEquals(DirectionType.DELIVERY, repository.direction);
    }

    @Test
    void rejectsInvalidRequestParameters() throws Exception {
        ForecastDatasetService service = serviceWithRepository(new StubRepository(List.of()));

        assertThrows(IllegalArgumentException.class, () -> service.getDataset("unknown", "2025-06-01T00:00:00Z", "2025-06-02T00:00:00Z"));
        assertThrows(IllegalArgumentException.class, () -> service.getDataset("load", "invalid", "2025-06-02T00:00:00Z"));
        assertThrows(IllegalArgumentException.class, () -> service.getDataset("load", "2025-06-02T00:00:00Z", "2025-06-01T00:00:00Z"));
        assertThrows(IllegalArgumentException.class, () -> service.getDataset("load", "2025-06-01T00:00:00Z", "2026-07-01T00:00:00Z"));
    }

    private ForecastDatasetService serviceWithRepository(EnergySeriesRepository repository) throws Exception {
        ForecastDatasetService service = new ForecastDatasetService();
        setField(service, "energySeriesRepository", repository);
        setField(service, "maxDays", 370L);
        return service;
    }

    private void setField(Object target, String name, Object value) throws Exception {
        Field field = target.getClass().getDeclaredField(name);
        field.setAccessible(true);
        field.set(target, value);
    }

    private static class StubRepository extends EnergySeriesRepository {
        private final List<ForecastDatasetValue> values;
        private DirectionType direction;

        private StubRepository(List<ForecastDatasetValue> values) {
            this.values = values;
        }

        @Override
        public List<ForecastDatasetValue> findForecastDataset(DirectionType direction, Instant from, Instant to) {
            this.direction = direction;
            return values;
        }
    }
}
