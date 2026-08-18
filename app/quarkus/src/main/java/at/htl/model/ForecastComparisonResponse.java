package at.htl.model;

import java.util.List;

public record ForecastComparisonResponse(
        String runId,
        List<ForecastComparisonPoint> points,
        ForecastComparisonDiagnostics diagnostics,
        List<ForecastMetric> metrics
) {
}
