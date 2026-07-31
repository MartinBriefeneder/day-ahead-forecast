package at.htl.service;

import at.htl.model.ForecastMetric;
import at.htl.model.ForecastPoint;
import at.htl.model.ForecastRunRequest;
import at.htl.model.ForecastRunSaveResponse;
import at.htl.repository.ForecastRunRepository;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.time.Instant;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class ForecastRunServiceTest {

    @Test
    void saveValidatesAndDelegatesToRepository() throws Exception {
        StubRepository repository = new StubRepository();
        ForecastRunService service = serviceWithRepository(repository);
        ForecastRunRequest request = validRequest();

        ForecastRunSaveResponse response = service.save(request);

        assertEquals("run-1", response.runId());
        assertEquals(2, response.forecastPoints());
        assertEquals(2, response.metrics());
        assertEquals(request, repository.savedRequest);
    }

    @Test
    void rejectsInvalidForecastRuns() throws Exception {
        ForecastRunService service = serviceWithRepository(new StubRepository());
        ForecastRunRequest valid = validRequest();

        assertThrows(IllegalArgumentException.class, () -> service.save(null));
        assertThrows(IllegalArgumentException.class, () -> service.save(new ForecastRunRequest("", valid.model(), valid.target(), valid.generatedAt(), valid.forecastStart(), valid.forecastEnd(), valid.sampleInterval(), valid.points(), valid.metrics())));
        assertThrows(IllegalArgumentException.class, () -> service.save(new ForecastRunRequest(valid.runId(), valid.model(), "other", valid.generatedAt(), valid.forecastStart(), valid.forecastEnd(), valid.sampleInterval(), valid.points(), valid.metrics())));
        assertThrows(IllegalArgumentException.class, () -> service.save(new ForecastRunRequest(valid.runId(), valid.model(), valid.target(), valid.generatedAt(), valid.forecastEnd(), valid.forecastStart(), valid.sampleInterval(), valid.points(), valid.metrics())));
        assertThrows(IllegalArgumentException.class, () -> service.save(new ForecastRunRequest(valid.runId(), valid.model(), valid.target(), valid.generatedAt(), valid.forecastStart(), valid.forecastEnd(), "PT1H", valid.points(), valid.metrics())));
        assertThrows(IllegalArgumentException.class, () -> service.save(new ForecastRunRequest(valid.runId(), valid.model(), valid.target(), valid.generatedAt(), valid.forecastStart(), valid.forecastEnd(), valid.sampleInterval(), List.of(), valid.metrics())));
        assertThrows(IllegalArgumentException.class, () -> service.save(new ForecastRunRequest(valid.runId(), valid.model(), valid.target(), valid.generatedAt(), valid.forecastStart(), valid.forecastEnd(), valid.sampleInterval(), valid.points(), List.of())));
    }

    private ForecastRunService serviceWithRepository(ForecastRunRepository repository) throws Exception {
        ForecastRunService service = new ForecastRunService();
        Field field = ForecastRunService.class.getDeclaredField("forecastRunRepository");
        field.setAccessible(true);
        field.set(service, repository);
        return service;
    }

    private ForecastRunRequest validRequest() {
        return new ForecastRunRequest(
                "run-1",
                "historical-average",
                "consumption",
                Instant.parse("2026-01-01T00:00:00Z"),
                Instant.parse("2025-12-01T00:00:00Z"),
                Instant.parse("2025-12-02T00:00:00Z"),
                "PT15M",
                List.of(
                        new ForecastPoint(Instant.parse("2025-12-01T00:00:00Z"), 12.5, 12.0),
                        new ForecastPoint(Instant.parse("2025-12-01T00:15:00Z"), 13.0, null)
                ),
                List.of(
                        new ForecastMetric("mae_kwh", 0.5),
                        new ForecastMetric("rmse_kwh", 0.5)
                )
        );
    }

    private static class StubRepository extends ForecastRunRepository {
        private ForecastRunRequest savedRequest;

        @Override
        public void save(ForecastRunRequest request) {
            savedRequest = request;
        }
    }
}
