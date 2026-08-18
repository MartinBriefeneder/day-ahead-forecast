package at.htl.service;

import at.htl.model.ForecastComparisonDiagnostics;
import at.htl.model.ForecastComparisonResponse;
import at.htl.model.ForecastComparisonPoint;
import at.htl.model.ForecastDatasetTarget;
import at.htl.model.ForecastDatasetValue;
import at.htl.model.ForecastMetric;
import at.htl.model.ForecastPoint;
import at.htl.model.ForecastRunRequest;
import at.htl.model.ForecastRunSaveResponse;
import at.htl.model.ForecastRunSummary;
import at.htl.repository.ForecastRunRepository;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;

import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

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
        List<ForecastComparisonPoint> forecastPoints = forecastRunRepository.findComparison(runId, limit);
        if (forecastPoints.isEmpty()) {
            return response(runId, forecastPoints, 0);
        }

        ForecastRunSummary summary = forecastRunRepository.findRun(runId).orElse(null);
        if (summary == null) {
            return response(runId, forecastPoints, 0);
        }

        ForecastDatasetTarget target = ForecastDatasetTarget.parse(summary.target());
        List<ForecastDatasetValue> actualValues = forecastRunRepository.findActualValues(
                target,
                summary.forecastStart(),
                summary.forecastEnd(),
                limit
        );
        Map<Instant, Double> actualByTimestamp = new LinkedHashMap<>();
        for (ForecastDatasetValue actualValue : actualValues) {
            actualByTimestamp.put(actualValue.timestamp(), actualValue.value());
        }

        List<ForecastComparisonPoint> aligned = new ArrayList<>(forecastPoints.size());
        for (ForecastComparisonPoint point : forecastPoints) {
            Double actualKwh = point.actualKwh() != null ? point.actualKwh() : actualByTimestamp.get(point.timestamp());
            Double errorKwh = actualKwh == null ? null : point.forecastKwh() - actualKwh;
            aligned.add(new ForecastComparisonPoint(point.timestamp(), point.forecastKwh(), actualKwh, errorKwh));
        }
        return response(runId, aligned, actualValues.size());
    }

    private ForecastComparisonResponse response(String runId, List<ForecastComparisonPoint> points, int actualPointCount) {
        int alignedPointCount = 0;
        double absError = 0.0;
        double squaredError = 0.0;
        double error = 0.0;
        double totalForecast = 0.0;
        double totalActual = 0.0;
        for (ForecastComparisonPoint point : points) {
            totalForecast += point.forecastKwh();
            if (point.actualKwh() != null && point.errorKwh() != null) {
                alignedPointCount++;
                absError += Math.abs(point.errorKwh());
                squaredError += point.errorKwh() * point.errorKwh();
                error += point.errorKwh();
                totalActual += point.actualKwh();
            }
        }
        List<ForecastMetric> metrics = new ArrayList<>();
        metrics.add(new ForecastMetric("forecast_intervals", points.size()));
        metrics.add(new ForecastMetric("actual_intervals", actualPointCount));
        metrics.add(new ForecastMetric("aligned_intervals", alignedPointCount));
        metrics.add(new ForecastMetric("missing_actual_intervals", points.size() - alignedPointCount));
        metrics.add(new ForecastMetric("total_forecast_kwh", totalForecast));
        if (alignedPointCount > 0) {
            metrics.add(new ForecastMetric("mae_kwh", absError / alignedPointCount));
            metrics.add(new ForecastMetric("rmse_kwh", Math.sqrt(squaredError / alignedPointCount)));
            metrics.add(new ForecastMetric("bias_kwh", error / alignedPointCount));
            metrics.add(new ForecastMetric("total_actual_kwh", totalActual));
            metrics.add(new ForecastMetric("total_energy_error_kwh", error));
        }
        ForecastComparisonDiagnostics diagnostics = new ForecastComparisonDiagnostics(
                points.size(),
                actualPointCount,
                alignedPointCount,
                points.size() - alignedPointCount
        );
        return new ForecastComparisonResponse(runId, points, diagnostics, metrics);
    }

    public List<ForecastRunSummary> listRuns(String target, int limit) throws Exception {
        if (target != null && !target.isBlank()) {
            ForecastDatasetTarget.parse(target);
        }
        if (limit <= 0 || limit > 1000) {
            throw new IllegalArgumentException("limit must be between 1 and 1000");
        }
        return forecastRunRepository.findRuns(target, limit);
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
