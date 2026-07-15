package at.htl.repository;

import at.htl.model.DirectionType;
import at.htl.model.EnergySeries;
import com.influxdb.v3.client.InfluxDBClient;
import com.influxdb.v3.client.Point;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import org.eclipse.microprofile.config.inject.ConfigProperty;
import org.jboss.logging.Logger;

import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.stream.Stream;

@ApplicationScoped
public class EnergySeriesRepository {

    private static final int DEFAULT_WRITE_BATCH_SIZE = 10_000;
    private static final int WRITE_PROGRESS_INTERVAL = 50_000;

    @Inject
    Logger logger;

    @ConfigProperty(name = "energy.influx.url")
    String influxUrl;

    @ConfigProperty(name = "energy.influx.database")
    String database;

    @ConfigProperty(name = "energy.influx.measurement")
    String measurement;

    @ConfigProperty(name = "energy.influx.token")
    Optional<String> token;

    @ConfigProperty(name = "energy.influx.write-batch-size", defaultValue = "10000")
    int writeBatchSize;

    public void saveAll(List<EnergySeries> series) throws Exception {
        if (series.isEmpty()) {
            return;
        }

        try (InfluxDBClient client = InfluxDBClient.getInstance(influxUrl, resolvedToken().toCharArray(), database)) {
            int batchSize = resolvedWriteBatchSize();
            List<Point> batch = new ArrayList<>(batchSize);
            for (int start = 0; start < series.size(); start += batchSize) {
                int end = Math.min(start + batchSize, series.size());
                if (start == 0 || end == series.size() || end % WRITE_PROGRESS_INTERVAL == 0) {
                    logger.info("Writing energy points " + (start + 1) + "-" + end + " of " + series.size() + " to InfluxDB");
                }
                batch.clear();
                for (int index = start; index < end; index++) {
                    batch.add(toPoint(series.get(index)));
                }
                client.writePoints(batch);
            }
        }
    }

    int resolvedWriteBatchSize() {
        return writeBatchSize > 0 ? writeBatchSize : DEFAULT_WRITE_BATCH_SIZE;
    }

    public List<EnergySeries> find(String meteringPoint, DirectionType direction, Instant from, Instant to, int limit) throws Exception {
        if (limit <= 0 || limit > 10_000) {
            throw new IllegalArgumentException("limit must be between 1 and 10000");
        }

        String sql = buildSql(meteringPoint, direction, from, to, limit);
        try (InfluxDBClient client = InfluxDBClient.getInstance(influxUrl, resolvedToken().toCharArray(), database);
             Stream<Object[]> stream = client.query(sql)) {
            return stream.map(this::toEnergySeries).toList();
        }
    }

    String buildSql(String meteringPoint, DirectionType direction, Instant from, Instant to, int limit) {
        List<String> conditions = new ArrayList<>();
        if (meteringPoint != null && !meteringPoint.isBlank()) {
            conditions.add("metering_point = '" + escapeSqlLiteral(meteringPoint) + "'");
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
                .append("SELECT time, metering_point, direction, total, community_effective, residual FROM ")
                .append(quoteIdentifier(measurement));
        if (!conditions.isEmpty()) {
            sql.append(" WHERE ").append(String.join(" AND ", conditions));
        }
        sql.append(" ORDER BY time ASC LIMIT ").append(limit);
        return sql.toString();
    }

    private String resolvedToken() {
        return token.filter(value -> !value.isBlank())
                .orElseThrow(() -> new IllegalStateException("energy.influx.token must be configured for InfluxDB access"));
    }

    private Point toPoint(EnergySeries series) {
        return Point.measurement(measurement)
                .setTag("metering_point", series.meteringPoint())
                .setTag("direction", series.direction().name())
                .setField("total", series.total())
                .setField("community_effective", series.communityEffective())
                .setField("residual", series.residual())
                .setTimestamp(series.timestamp());
    }

    private EnergySeries toEnergySeries(Object[] row) {
        return new EnergySeries(
                String.valueOf(row[1]),
                parseTime(row[0]),
                DirectionType.valueOf(String.valueOf(row[2])),
                ((Number) row[3]).doubleValue(),
                ((Number) row[4]).doubleValue(),
                ((Number) row[5]).doubleValue()
        );
    }

    private Instant parseTime(Object value) {
        if (value instanceof Instant instant) {
            return instant;
        }
        String text = String.valueOf(value);
        if (text.endsWith("Z") || text.contains("+")) {
            return Instant.parse(text);
        }
        return LocalDateTime.parse(text).toInstant(ZoneOffset.UTC);
    }

    private String quoteIdentifier(String value) {
        return '"' + value.replace("\"", "\"\"") + '"';
    }

    private String escapeSqlLiteral(String value) {
        return value.replace("'", "''");
    }
}
