package at.htl.model;

import java.time.Instant;

public record ForecastPoint(Instant timestamp, double forecastKwh, Double actualKwh) {
}
