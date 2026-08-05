package at.htl.model;

import java.time.Instant;

public record ForecastRunSummary(
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
        String reportPath
) {
}
