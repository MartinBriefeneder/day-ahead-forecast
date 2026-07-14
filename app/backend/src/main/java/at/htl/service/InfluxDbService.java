package at.htl.service;

import at.htl.model.DirectionType;
import at.htl.model.EnergySeries;
import com.influxdb.v3.client.InfluxDBClient;
import com.influxdb.v3.client.Point;
import jakarta.enterprise.context.ApplicationScoped;
import org.eclipse.microprofile.config.inject.ConfigProperty;

import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.stream.Stream;

@ApplicationScoped
public class InfluxDbService {

    @ConfigProperty(name = "energy.influx.url")
    String influxUrl;

    @ConfigProperty(name = "energy.influx.database")
    String database;

    @ConfigProperty(name = "energy.influx.measurement")
    String measurement;

    @ConfigProperty(name = "energy.influx.token")
    Optional<String> token;

    public void write(List<EnergySeries> series) throws Exception {
        if (series.isEmpty()) {
            return;
        }

        try (InfluxDBClient client = InfluxDBClient.getInstance(influxUrl, tokenChars(), database)) {
            for (EnergySeries item : series) {
                client.writePoint(toPoint(item));
            }
        }
    }

    public List<EnergySeries> query(String identifier, DirectionType direction, Instant from, Instant to, int limit) throws Exception {
        if (limit <= 0 || limit > 10_000) {
            throw new IllegalArgumentException("limit must be between 1 and 10000");
        }

        String sql = buildSql(identifier, direction, from, to, limit);
        try (InfluxDBClient client = InfluxDBClient.getInstance(influxUrl, tokenChars(), database);
             Stream<Object[]> stream = client.query(sql)) {
            return stream.map(this::toEnergySeries).toList();
        }
    }

    String buildSql(String identifier, DirectionType direction, Instant from, Instant to, int limit) {
        List<String> conditions = new ArrayList<>();
        if (identifier != null && !identifier.isBlank()) {
            conditions.add("identifier = '" + escapeSqlLiteral(identifier) + "'");
        }
        if (direction != null) {
            conditions.add("direction = '" + direction.name() + "'");
        }
        if (from != null) {
            conditions.add("time >= '" + from + "'");
        }
        if (to != null) {
            conditions.add("time < '" + to + "'");
        }

        StringBuilder sql = new StringBuilder()
                .append("SELECT time, identifier, direction, total, community_effective, residual FROM ")
                .append(quoteIdentifier(measurement));
        if (!conditions.isEmpty()) {
            sql.append(" WHERE ").append(String.join(" AND ", conditions));
        }
        sql.append(" ORDER BY time ASC LIMIT ").append(limit);
        return sql.toString();
    }

    private Point toPoint(EnergySeries series) {
        return Point.measurement(measurement)
                .setTag("identifier", series.identifier())
                .setTag("direction", series.energyDirection().name())
                .setField("total", series.total())
                .setField("community_effective", series.community_effective())
                .setField("residual", series.residual())
                .setTimestamp(series.timestamp());
    }

    private EnergySeries toEnergySeries(Object[] row) {
        return new EnergySeries(
                String.valueOf(row[1]),
                parseInfluxTime(row[0]),
                DirectionType.valueOf(String.valueOf(row[2])),
                ((Number) row[3]).doubleValue(),
                ((Number) row[4]).doubleValue(),
                ((Number) row[5]).doubleValue()
        );
    }

    private Instant parseInfluxTime(Object value) {
        if (value instanceof Instant instant) {
            return instant;
        }
        String text = String.valueOf(value);
        if (text.endsWith("Z") || text.contains("+")) {
            return Instant.parse(text);
        }
        return LocalDateTime.parse(text).toInstant(ZoneOffset.UTC);
    }

    private char[] tokenChars() {
        return token.filter(value -> !value.isBlank())
                .map(String::toCharArray)
                .orElse(null);
    }

    private String quoteIdentifier(String value) {
        return '"' + value.replace("\"", "\"\"") + '"';
    }

    private String escapeSqlLiteral(String value) {
        return value.replace("'", "''");
    }
}
