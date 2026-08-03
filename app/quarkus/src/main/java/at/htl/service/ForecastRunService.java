package at.htl.service;

import at.htl.model.ForecastComparisonResponse;
import at.htl.model.ForecastDatasetTarget;
import at.htl.model.ForecastMetric;
import at.htl.model.ForecastPoint;
import at.htl.model.ForecastRunRequest;
import at.htl.model.ForecastRunSaveResponse;
import at.htl.repository.ForecastRunRepository;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;

import java.time.Duration;
import java.time.Instant;
import java.util.List;

@ApplicationScoped
public class ForecastRunService {

    private static final Duration SAMPLE_INTERVAL = Duration.ofMinutes(15);

    @Inject
    ForecastRunRepository forecastRunRepository;

    public ForecastRunSaveResponse save(ForecastRunRequest request) throws Exception {
        validate(request);
        forecastRunRepository.save(request);
        return new ForecastRunSaveResponse(request.runId(), request.points().size(), request.metrics().size());
    }

    public ForecastComparisonResponse getComparison(String runId, int limit) throws Exception {
        if (runId == null || runId.isBlank()) {
            throw new IllegalArgumentException("runId must be provided");
        }
        return new ForecastComparisonResponse(runId, forecastRunRepository.findComparison(runId, limit));
    }

    private void validate(ForecastRunRequest request) {
        if (request == null) {
            throw new IllegalArgumentException("Forecast run request body is required");
        }
        requireText("runId", request.runId());
        requireText("model", request.model());
        ForecastDatasetTarget.parse(requireText("target", request.target()));
        if (request.forecastStart() == null || request.forecastEnd() == null) {
            throw new IllegalArgumentException("forecastStart and forecastEnd must be provided");
        }
        if (!request.forecastEnd().isAfter(request.forecastStart())) {
            throw new IllegalArgumentException("forecastEnd must be after forecastStart");
        }
        validateTrainWindow(request);
        if (!SAMPLE_INTERVAL.equals(parseSampleInterval(request.sampleInterval()))) {
            throw new IllegalArgumentException("sampleInterval must be PT15M");
        }
        parseOptionalDuration("horizon", request.horizon());

        List<ForecastPoint> points = requireList("points", request.points());
        for (ForecastPoint point : points) {
            validatePoint(point, request.forecastStart(), request.forecastEnd());
        }

        List<ForecastMetric> metrics = requireList("metrics", request.metrics());
        for (ForecastMetric metric : metrics) {
            requireText("metric.name", metric.name());
            requireFinite("metric.value", metric.value());
        }
    }

    private void validateTrainWindow(ForecastRunRequest request) {
        if (request.trainStart() == null && request.trainEnd() == null) {
            return;
        }
        if (request.trainStart() == null || request.trainEnd() == null) {
            throw new IllegalArgumentException("trainStart and trainEnd must be provided together");
        }
        if (!request.trainEnd().isAfter(request.trainStart())) {
            throw new IllegalArgumentException("trainEnd must be after trainStart");
        }
        if (request.trainEnd().isAfter(request.forecastStart())) {
            throw new IllegalArgumentException("trainEnd must not be after forecastStart");
        }
    }

    private void validatePoint(ForecastPoint point, Instant forecastStart, Instant forecastEnd) {
        if (point == null || point.timestamp() == null) {
            throw new IllegalArgumentException("Each forecast point must include a timestamp");
        }
        if (point.timestamp().isBefore(forecastStart) || !point.timestamp().isBefore(forecastEnd)) {
            throw new IllegalArgumentException("Forecast point timestamp must be inside [forecastStart, forecastEnd)");
        }
        requireFinite("forecastKwh", point.forecastKwh());
        if (point.actualKwh() != null) {
            requireFinite("actualKwh", point.actualKwh());
        }
    }

    private Duration parseSampleInterval(String value) {
        try {
            return Duration.parse(requireText("sampleInterval", value));
        } catch (RuntimeException exception) {
            throw new IllegalArgumentException("sampleInterval must use ISO-8601 duration format, for example PT15M", exception);
        }
    }

    private void parseOptionalDuration(String name, String value) {
        if (value == null || value.isBlank()) {
            return;
        }
        try {
            Duration.parse(value);
        } catch (RuntimeException exception) {
            throw new IllegalArgumentException(name + " must use ISO-8601 duration format, for example PT36H", exception);
        }
    }

    private String requireText(String name, String value) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException(name + " must be provided");
        }
        return value;
    }

    private <T> List<T> requireList(String name, List<T> values) {
        if (values == null || values.isEmpty()) {
            throw new IllegalArgumentException(name + " must not be empty");
        }
        return values;
    }

    private void requireFinite(String name, double value) {
        if (!Double.isFinite(value)) {
            throw new IllegalArgumentException(name + " must be finite");
        }
    }
}
