package at.htl.service;

import at.htl.model.ForecastComparisonResponse;
import at.htl.model.ForecastDatasetTarget;
import at.htl.model.ForecastDatasetValue;
import at.htl.model.ForecastMetric;
import at.htl.model.ForecastPoint;
import at.htl.model.ForecastRunRequest;
import at.htl.model.ForecastRunSaveResponse;
import at.htl.model.ForecastRunSummary;
import at.htl.repository.ForecastRunRepository;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

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
    void savesComingWeeksRunWithoutActualValues() throws Exception {
        StubRepository repository = new StubRepository();
        ForecastRunService service = serviceWithRepository(repository);
        ForecastRunRequest request = new ForecastRunRequest(
                "consumption-historical-average-20251201T000000Z",
                "historical-average",
                "consumption",
                Instant.parse("2025-12-01T00:00:00Z"),
                Instant.parse("2025-09-01T00:00:00Z"),
                Instant.parse("2025-12-01T00:00:00Z"),
                Instant.parse("2025-12-01T00:00:00Z"),
                Instant.parse("2025-12-15T00:00:00Z"),
                "PT15M",
                "P14D",
                "simple-benchmark",
                null,
                List.of(new ForecastPoint(Instant.parse("2025-12-01T00:00:00Z"), 12.5, null)),
                List.of(new ForecastMetric("total_forecast_kwh", 12.5))
        );

        ForecastRunSaveResponse response = service.save(request);

        assertEquals("consumption-historical-average-20251201T000000Z", response.runId());
        assertEquals("P14D", repository.savedRequest.horizon());
        assertEquals(null, repository.savedRequest.points().getFirst().actualKwh());
    }

    @Test
    void rejectsInvalidForecastRuns() throws Exception {
        ForecastRunService service = serviceWithRepository(new StubRepository());
        ForecastRunRequest valid = validRequest();

        assertThrows(IllegalArgumentException.class, () -> service.save(null));
        assertThrows(IllegalArgumentException.class, () -> service.save(new ForecastRunRequest("", valid.model(), valid.target(), valid.generatedAt(), valid.trainStart(), valid.trainEnd(), valid.forecastStart(), valid.forecastEnd(), valid.sampleInterval(), valid.horizon(), valid.modelFamily(), valid.reportPath(), valid.points(), valid.metrics())));
        assertThrows(IllegalArgumentException.class, () -> service.save(new ForecastRunRequest(valid.runId(), valid.model(), "other", valid.generatedAt(), valid.trainStart(), valid.trainEnd(), valid.forecastStart(), valid.forecastEnd(), valid.sampleInterval(), valid.horizon(), valid.modelFamily(), valid.reportPath(), valid.points(), valid.metrics())));
        assertThrows(IllegalArgumentException.class, () -> service.save(new ForecastRunRequest(valid.runId(), valid.model(), valid.target(), valid.generatedAt(), valid.trainStart(), valid.trainEnd(), valid.forecastEnd(), valid.forecastStart(), valid.sampleInterval(), valid.horizon(), valid.modelFamily(), valid.reportPath(), valid.points(), valid.metrics())));
        assertThrows(IllegalArgumentException.class, () -> service.save(new ForecastRunRequest(valid.runId(), valid.model(), valid.target(), valid.generatedAt(), valid.trainStart(), valid.trainEnd(), valid.forecastStart(), valid.forecastEnd(), "PT1H", valid.horizon(), valid.modelFamily(), valid.reportPath(), valid.points(), valid.metrics())));
        assertThrows(IllegalArgumentException.class, () -> service.save(new ForecastRunRequest(valid.runId(), valid.model(), valid.target(), valid.generatedAt(), valid.trainStart(), valid.trainEnd(), valid.forecastStart(), valid.forecastEnd(), valid.sampleInterval(), valid.horizon(), valid.modelFamily(), valid.reportPath(), List.of(), valid.metrics())));
        assertThrows(IllegalArgumentException.class, () -> service.save(new ForecastRunRequest(valid.runId(), valid.model(), valid.target(), valid.generatedAt(), valid.trainStart(), valid.trainEnd(), valid.forecastStart(), valid.forecastEnd(), valid.sampleInterval(), valid.horizon(), valid.modelFamily(), valid.reportPath(), valid.points(), List.of())));
        assertThrows(IllegalArgumentException.class, () -> service.save(new ForecastRunRequest(valid.runId(), valid.model(), valid.target(), valid.generatedAt(), valid.trainStart(), null, valid.forecastStart(), valid.forecastEnd(), valid.sampleInterval(), valid.horizon(), valid.modelFamily(), valid.reportPath(), valid.points(), valid.metrics())));
        assertThrows(IllegalArgumentException.class, () -> service.save(new ForecastRunRequest(valid.runId(), valid.model(), valid.target(), valid.generatedAt(), valid.trainStart(), valid.trainStart(), valid.forecastStart(), valid.forecastEnd(), valid.sampleInterval(), valid.horizon(), valid.modelFamily(), valid.reportPath(), valid.points(), valid.metrics())));
        assertThrows(IllegalArgumentException.class, () -> service.save(new ForecastRunRequest(valid.runId(), valid.model(), valid.target(), valid.generatedAt(), valid.trainStart(), valid.trainEnd(), valid.forecastStart(), valid.forecastEnd(), valid.sampleInterval(), "tomorrow", valid.modelFamily(), valid.reportPath(), valid.points(), valid.metrics())));
    }

    @Test
    void comparisonFillsActualValuesFromImportedEnergyData() throws Exception {
        StubRepository repository = new StubRepository();
        repository.comparisonPoints = List.of(
                new at.htl.model.ForecastComparisonPoint(Instant.parse("2025-12-01T00:00:00Z"), 10.0, null, null),
                new at.htl.model.ForecastComparisonPoint(Instant.parse("2025-12-01T00:15:00Z"), 20.0, null, null)
        );
        repository.summary = Optional.of(new ForecastRunSummary(
                "run-1",
                "weekly-persistence",
                "generation",
                Instant.parse("2026-01-01T00:00:00Z"),
                Instant.parse("2025-09-01T00:00:00Z"),
                Instant.parse("2025-12-01T00:00:00Z"),
                Instant.parse("2025-12-01T00:00:00Z"),
                Instant.parse("2025-12-01T00:30:00Z"),
                "PT15M",
                "PT36H",
                "simple-benchmark",
                null
        ));
        repository.actualValues = List.of(
                new ForecastDatasetValue(Instant.parse("2025-12-01T00:00:00Z"), 8.0)
        );
        ForecastRunService service = serviceWithRepository(repository);

        ForecastComparisonResponse response = service.getComparison("run-1", 100);

        assertEquals(2, response.diagnostics().forecastPointCount());
        assertEquals(1, response.diagnostics().actualPointCount());
        assertEquals(1, response.diagnostics().alignedPointCount());
        assertEquals(1, response.diagnostics().missingActualCount());
        assertEquals(8.0, response.points().get(0).actualKwh());
        assertEquals(2.0, response.points().get(0).errorKwh());
        assertEquals(null, response.points().get(1).actualKwh());
        assertEquals(ForecastDatasetTarget.GENERATION, repository.actualTarget);
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
                Instant.parse("2025-11-01T00:00:00Z"),
                Instant.parse("2025-12-01T00:00:00Z"),
                Instant.parse("2025-12-01T00:00:00Z"),
                Instant.parse("2025-12-02T00:00:00Z"),
                "PT15M",
                "P14D",
                "simple-benchmark",
                "app/reports/forecast-runs/forecast-backtest-report.md",
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
        private List<at.htl.model.ForecastComparisonPoint> comparisonPoints = List.of();
        private Optional<ForecastRunSummary> summary = Optional.empty();
        private List<ForecastDatasetValue> actualValues = List.of();
        private ForecastDatasetTarget actualTarget;

        @Override
        public void save(ForecastRunRequest request) {
            savedRequest = request;
        }

        @Override
        public List<at.htl.model.ForecastComparisonPoint> findComparison(String runId, int limit) {
            return comparisonPoints;
        }

        @Override
        public Optional<ForecastRunSummary> findRun(String runId) {
            return summary;
        }

        @Override
        public List<ForecastDatasetValue> findActualValues(ForecastDatasetTarget target, Instant from, Instant to, int limit) {
            actualTarget = target;
            return actualValues;
        }
    }
}
