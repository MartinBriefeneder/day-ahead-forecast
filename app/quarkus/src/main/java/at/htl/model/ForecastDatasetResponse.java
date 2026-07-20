package at.htl.model;

import java.util.List;

public record ForecastDatasetResponse(String sampleInterval, String targetColumn, String unit, List<ForecastDatasetPoint> points) {
}
