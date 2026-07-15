package at.htl.model;

import java.time.Instant;

public record EnergySeries(String meteringPoint, Instant timestamp, DirectionType direction, double total, double communityEffective, double residual) {
}
