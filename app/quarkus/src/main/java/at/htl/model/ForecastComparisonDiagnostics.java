package at.htl.model;

public record ForecastComparisonDiagnostics(
        int forecastPointCount,
        int actualPointCount,
        int alignedPointCount,
        int missingActualCount
) {
}
