package at.htl.repository;

import at.htl.model.ForecastComparisonPoint;
import at.htl.model.ForecastMetric;
import at.htl.model.ForecastPoint;
import at.htl.model.ForecastRunRequest;
import com.influxdb.v3.client.InfluxDBClient;
import com.influxdb.v3.client.Point;
import com.influxdb.v3.client.write.WriteOptions;
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
public class ForecastRunRepository {

    @ConfigProperty(name = "energy.influx.url")
    String influxUrl;

    @ConfigProperty(name = "energy.influx.database")
    String database;

    @ConfigProperty(name = "energy.influx.forecast-measurement", defaultValue = "energy_forecasts")
    String forecastMeasurement;

    @ConfigProperty(name = "energy.influx.forecast-evaluation-measurement", defaultValue = "forecast_evaluations")
    String evaluationMeasurement;

    @ConfigProperty(name = "energy.influx.token")
    Optional<String> token;

    @ConfigProperty(name = "energy.influx.gzip-threshold-bytes", defaultValue = "1")
    int gzipThresholdBytes;

    public void save(ForecastRunRequest request) throws Exception {
        List<Point> points = new ArrayList<>(request.points().size() + request.metrics().size());
        for (ForecastPoint forecastPoint : request.points()) {
            points.add(toForecastPoint(request, forecastPoint));
        }
        for (ForecastMetric metric : request.metrics()) {
            points.add(toEvaluationPoint(request, metric));
        }

        if (points.isEmpty()) {
            return;
        }

        try (InfluxDBClient client = InfluxDBClient.getInstance(influxUrl, resolvedToken().toCharArray(), database)) {
            client.writePoints(points, writeOptions());
        }
    }

    public List<ForecastComparisonPoint> findComparison(String runId, int limit) throws Exception {
        String sql = buildComparisonSql(runId, limit);
        try (InfluxDBClient client = InfluxDBClient.getInstance(influxUrl, resolvedToken().toCharArray(), database);
             Stream<Object[]> stream = client.query(sql)) {
            return stream.map(this::toComparisonPoint).toList();
        }
    }

    String buildComparisonSql(String runId, int limit) {
        if (runId == null || runId.isBlank()) {
            throw new IllegalArgumentException("runId must be provided");
        }
        if (limit <= 0 || limit > 100_000) {
            throw new IllegalArgumentException("limit must be between 1 and 100000");
        }

        return new StringBuilder()
                .append("SELECT time, forecast_kwh, actual_kwh, error_kwh FROM ")
                .append(quoteIdentifier(forecastMeasurement))
                .append(" WHERE run_id = '").append(escapeSqlLiteral(runId)).append("'")
                .append(" ORDER BY time ASC LIMIT ").append(limit)
                .toString();
    }

    ForecastComparisonPoint toComparisonPoint(Object[] row) {
        return new ForecastComparisonPoint(
                parseTime(row[0]),
                ((Number) row[1]).doubleValue(),
                numberOrNull(row[2]),
                numberOrNull(row[3])
        );
    }

    WriteOptions writeOptions() {
        return new WriteOptions.Builder()
                .gzipThreshold(gzipThresholdBytes)
                .build();
    }

    private Point toForecastPoint(ForecastRunRequest request, ForecastPoint forecastPoint) {
        Point point = Point.measurement(forecastMeasurement)
                .setTag("run_id", request.runId())
                .setTag("target", request.target())
                .setTag("model", request.model())
                .setField("forecast_kwh", forecastPoint.forecastKwh())
                .setTimestamp(forecastPoint.timestamp());

        if (forecastPoint.actualKwh() != null) {
            point.setField("actual_kwh", forecastPoint.actualKwh());
            point.setField("error_kwh", forecastPoint.forecastKwh() - forecastPoint.actualKwh());
        }
        return point;
    }

    private Point toEvaluationPoint(ForecastRunRequest request, ForecastMetric metric) {
        Instant generatedAt = Optional.ofNullable(request.generatedAt()).orElseGet(Instant::now);
        return Point.measurement(evaluationMeasurement)
                .setTag("run_id", request.runId())
                .setTag("target", request.target())
                .setTag("model", request.model())
                .setTag("metric", metric.name())
                .setTag("forecast_start", request.forecastStart().toString())
                .setTag("forecast_end", request.forecastEnd().toString())
                .setTag("sample_interval", request.sampleInterval())
                .setField("value", metric.value())
                .setTimestamp(generatedAt);
    }

    private String resolvedToken() {
        return token.filter(value -> !value.isBlank())
                .orElseThrow(() -> new IllegalStateException("energy.influx.token must be configured for InfluxDB access"));
    }

    private Double numberOrNull(Object value) {
        if (value == null) {
            return null;
        }
        return ((Number) value).doubleValue();
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
