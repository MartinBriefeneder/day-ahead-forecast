package at.htl.service;

import at.htl.model.ForecastDatasetPoint;
import at.htl.model.ForecastDatasetResponse;
import at.htl.model.ForecastDatasetTarget;
import at.htl.model.ForecastDatasetValue;
import at.htl.repository.EnergySeriesRepository;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import org.eclipse.microprofile.config.inject.ConfigProperty;

import java.time.Duration;
import java.time.Instant;
import java.time.format.DateTimeParseException;
import java.util.List;

@ApplicationScoped
public class ForecastDatasetService {

    private static final String SAMPLE_INTERVAL = "PT15M";
    private static final String UNIT = "kWh";

    @Inject
    EnergySeriesRepository energySeriesRepository;

    public ForecastDatasetResponse getDataset(String targetValue, String fromValue, String toValue) throws Exception {
        ForecastDatasetTarget target = ForecastDatasetTarget.parse(requirePresent("target", targetValue));
        Instant from = parseInstant("from", fromValue);
        Instant to = parseInstant("to", toValue);
        validateRange(from, to);

        List<ForecastDatasetPoint> points = energySeriesRepository.findForecastDataset(target.direction(), from, to).stream()
                .map(value -> toPoint(target, value))
                .toList();

        return new ForecastDatasetResponse(SAMPLE_INTERVAL, target.columnName(), UNIT, points);
    }

    private ForecastDatasetPoint toPoint(ForecastDatasetTarget target, ForecastDatasetValue value) {
        return new ForecastDatasetPoint(value.timestamp(), target.columnName(), value.value());
    }

    private String requirePresent(String name, String value) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException("Missing required query parameter: " + name);
        }
        return value;
    }

    private Instant parseInstant(String name, String value) {
        requirePresent(name, value);
        try {
            return Instant.parse(value);
        } catch (DateTimeParseException exception) {
            throw new IllegalArgumentException("Invalid " + name + " timestamp. Use ISO-8601 UTC format, for example 2025-06-01T00:00:00Z.", exception);
        }
    }

    private void validateRange(Instant from, Instant to) {
        if (!to.isAfter(from)) {
            throw new IllegalArgumentException("Query parameter to must be after from.");
        }
    }
}
