package at.htl.model;

import java.time.Instant;

public record EnergySeries(String identifier, Instant timestamp, DirectionType energyDirection, double total, double community_effective, double residual) {
}

