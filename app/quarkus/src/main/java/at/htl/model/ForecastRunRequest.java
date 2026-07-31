package at.htl.model;

import java.time.Instant;
import java.util.List;

public record ForecastRunRequest(
        String runId,
        String model,
        String target,
        Instant generatedAt,
        Instant forecastStart,
        Instant forecastEnd,
        String sampleInterval,
        List<ForecastPoint> points,
        List<ForecastMetric> metrics
) {
}
