package at.htl.repository;

import at.htl.model.DirectionType;
import at.htl.model.EnergyCategory;
import at.htl.model.EnergySeries;
import at.htl.model.ForecastDatasetValue;
import com.influxdb.v3.client.InfluxDBClient;
import com.influxdb.v3.client.Point;
import com.influxdb.v3.client.write.WriteOptions;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import org.eclipse.microprofile.config.inject.ConfigProperty;
import org.jboss.logging.Logger;

import java.time.Duration;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.stream.Stream;

@ApplicationScoped
public class EnergySeriesRepository {

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

    @ConfigProperty(name = "energy.influx.gzip-threshold-bytes", defaultValue = "1")
    int gzipThresholdBytes;

    @ConfigProperty(name = "energy.influx.forecast-dataset-query-window", defaultValue = "P1D")
    Duration forecastDatasetQueryWindow;

    public void saveAll(List<EnergySeries> series) throws Exception {
        if (series.isEmpty()) {
            return;
        }

        try (InfluxDBClient client = InfluxDBClient.getInstance(influxUrl, resolvedToken().toCharArray(), database)) {
            int batchSize = resolvedWriteBatchSize();
            WriteOptions writeOptions = writeOptions();
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
                client.writePoints(batch, writeOptions);
            }
        }
    }

    WriteOptions writeOptions() {
        return new WriteOptions.Builder()
                .gzipThreshold(gzipThresholdBytes)
                .build();
    }

    int resolvedWriteBatchSize() {
        if (writeBatchSize <= 0) {
            throw new IllegalStateException("energy.influx.write-batch-size must be positive");
        }
        return writeBatchSize;
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

    public List<ForecastDatasetValue> findForecastDataset(DirectionType direction, Instant from, Instant to) throws Exception {
        List<ForecastDatasetValue> values = new ArrayList<>();
        try (InfluxDBClient client = InfluxDBClient.getInstance(influxUrl, resolvedToken().toCharArray(), database)) {
            for (TimeWindow window : buildForecastDatasetWindows(from, to)) {
                String sql = buildForecastDatasetSql(direction, window.from(), window.to());
                try (Stream<Object[]> stream = client.query(sql)) {
                    stream.map(this::toForecastDatasetValue).forEach(values::add);
                }
            }
        }
        return values;
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
                .append("SELECT time, metering_point, direction, category, value_kwh FROM ")
                .append(quoteIdentifier(measurement));
        if (!conditions.isEmpty()) {
            sql.append(" WHERE ").append(String.join(" AND ", conditions));
        }
        sql.append(" ORDER BY time ASC LIMIT ").append(limit);
        return sql.toString();
    }

    String buildForecastDatasetSql(DirectionType direction, Instant from, Instant to) {
        if (direction == null) {
            throw new IllegalArgumentException("direction must be provided");
        }
        if (from == null || to == null) {
            throw new IllegalArgumentException("from and to must be provided");
        }

        return new StringBuilder()
                .append("SELECT time, SUM(value_kwh) AS value FROM ")
                .append(quoteIdentifier(measurement))
                .append(" WHERE direction = '").append(direction.name()).append("'")
                .append(" AND category = '").append(EnergyCategory.TOTAL.tagValue()).append("'")
                .append(" AND time >= '").append(from).append("'")
                .append(" AND time < '").append(to).append("'")
                .append(" GROUP BY time ORDER BY time ASC")
                .toString();
    }

    List<TimeWindow> buildForecastDatasetWindows(Instant from, Instant to) {
        if (from == null || to == null) {
            throw new IllegalArgumentException("from and to must be provided");
        }
        if (!to.isAfter(from)) {
            throw new IllegalArgumentException("to must be after from");
        }
        Duration windowSize = forecastDatasetQueryWindow;
        if (windowSize == null || windowSize.isZero() || windowSize.isNegative()) {
            throw new IllegalStateException("energy.influx.forecast-dataset-query-window must be positive");
        }

        List<TimeWindow> windows = new ArrayList<>();
        Instant windowFrom = from;
        while (windowFrom.isBefore(to)) {
            Instant windowTo = windowFrom.plus(windowSize);
            if (windowTo.isAfter(to)) {
                windowTo = to;
            }
            windows.add(new TimeWindow(windowFrom, windowTo));
            windowFrom = windowTo;
        }
        return windows;
    }

    record TimeWindow(Instant from, Instant to) {
    }

    private String resolvedToken() {
        return token.filter(value -> !value.isBlank())
                .orElseThrow(() -> new IllegalStateException("energy.influx.token must be configured for InfluxDB access"));
    }

    private Point toPoint(EnergySeries series) {
        return Point.measurement(measurement)
                .setTag("metering_point", series.meteringPoint())
                .setTag("direction", series.direction().name())
                .setTag("category", series.category().tagValue())
                .setField("value_kwh", series.valueKwh())
                .setTimestamp(series.timestamp());
    }

    private EnergySeries toEnergySeries(Object[] row) {
        return new EnergySeries(
                String.valueOf(row[1]),
                parseTime(row[0]),
                DirectionType.valueOf(String.valueOf(row[2])),
                EnergyCategory.fromTagValue(String.valueOf(row[3])),
                ((Number) row[4]).doubleValue()
        );
    }

    ForecastDatasetValue toForecastDatasetValue(Object[] row) {
        return new ForecastDatasetValue(parseTime(row[0]), ((Number) row[1]).doubleValue());
    }

    private Instant parseTime(Object value) {
        if (value instanceof Instant instant) {
            return instant;
        }
        if (value instanceof Number number) {
            long epochNanos = number.longValue();
            return Instant.ofEpochSecond(
                    Math.floorDiv(epochNanos, 1_000_000_000L),
                    Math.floorMod(epochNanos, 1_000_000_000L)
            );
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
