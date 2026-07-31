package at.htl.model;

import java.time.Instant;

public record ForecastComparisonPoint(Instant timestamp, double forecastKwh, Double actualKwh, Double errorKwh) {
}
