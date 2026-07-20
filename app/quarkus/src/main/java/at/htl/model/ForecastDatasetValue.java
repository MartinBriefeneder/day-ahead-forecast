package at.htl.model;

import java.time.Instant;

public record ForecastDatasetValue(Instant timestamp, double value) {
}
