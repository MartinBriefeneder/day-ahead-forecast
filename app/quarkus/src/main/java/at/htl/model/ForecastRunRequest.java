package at.htl.model;

import java.time.Instant;
import java.util.List;

public record ForecastRunRequest(
        String runId,
        String model,
        String target,
        Instant generatedAt,
        Instant trainStart,
        Instant trainEnd,
        Instant forecastStart,
        Instant forecastEnd,
        String sampleInterval,
        String horizon,
        String modelFamily,
        String reportPath,
        List<ForecastPoint> points,
        List<ForecastMetric> metrics
) {
}
