package at.htl.model;

import com.fasterxml.jackson.annotation.JsonAnyGetter;

import java.time.Instant;
import java.util.Map;

public class ForecastDatasetPoint {

    private final Instant timestamp;
    private final String targetColumn;
    private final double value;

    public ForecastDatasetPoint(Instant timestamp, String targetColumn, double value) {
        this.timestamp = timestamp;
        this.targetColumn = targetColumn;
        this.value = value;
    }

    public Instant getTimestamp() {
        return timestamp;
    }

    @JsonAnyGetter
    public Map<String, Double> targetValue() {
        return Map.of(targetColumn, value);
    }
}
