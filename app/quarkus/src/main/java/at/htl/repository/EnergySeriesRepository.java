package at.htl.repository;

import at.htl.model.DirectionType;
import at.htl.model.EnergyCategory;
import at.htl.model.EnergySeries;
import at.htl.model.ForecastDatasetValue;
import com.influxdb.client.InfluxDBClient;
import com.influxdb.client.InfluxDBClientFactory;
import com.influxdb.client.domain.WritePrecision;
import com.influxdb.client.write.Point;
import com.influxdb.query.FluxRecord;
import com.influxdb.query.FluxTable;
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

@ApplicationScoped
public class EnergySeriesRepository {

    private static final int WRITE_PROGRESS_INTERVAL = 50_000;

    @Inject
    Logger logger;

    @ConfigProperty(name = "energy.influx.url")
    String influxUrl;

    @ConfigProperty(name = "energy.influx.org")
    String org;

    @ConfigProperty(name = "energy.influx.bucket")
    String bucket;

    @ConfigProperty(name = "energy.influx.measurement")
    String measurement;

    @ConfigProperty(name = "energy.influx.token")
    Optional<String> token;

    @ConfigProperty(name = "energy.influx.write-batch-size", defaultValue = "10000")
    int writeBatchSize;

    @ConfigProperty(name = "energy.influx.forecast-dataset-query-window", defaultValue = "P1D")
    Duration forecastDatasetQueryWindow;

    public void saveAll(List<EnergySeries> series) throws Exception {
        if (series.isEmpty()) {
            return;
        }

        try (InfluxDBClient client = newClient()) {
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
                client.getWriteApiBlocking().writePoints(bucket, org, batch);
            }
        }
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

        String flux = buildFlux(meteringPoint, direction, from, to, limit);
        try (InfluxDBClient client = newClient()) {
            return queryRecords(client, flux).stream().map(this::toEnergySeries).toList();
        }
    }

    public List<ForecastDatasetValue> findForecastDataset(DirectionType direction, Instant from, Instant to) throws Exception {
        List<ForecastDatasetValue> values = new ArrayList<>();
        try (InfluxDBClient client = newClient()) {
            for (TimeWindow window : buildForecastDatasetWindows(from, to)) {
                String flux = buildForecastDatasetFlux(direction, window.from(), window.to());
                queryRecords(client, flux).stream().map(this::toForecastDatasetValue).forEach(values::add);
            }
        }
        return values;
    }

    public boolean hasImportedValues() throws Exception {
        try (InfluxDBClient client = newClient()) {
            return !queryRecords(client, buildImportedValuesStatusFlux()).isEmpty();
        }
    }

    String buildImportedValuesStatusFlux() {
        return new StringBuilder()
                .append("from(bucket: ").append(fluxString(bucket)).append(")")
                .append(" |> range(start: time(v: \"1970-01-01T00:00:00Z\"), stop: time(v: \"2100-01-01T00:00:00Z\"))")
                .append(" |> filter(fn: (r) => r[\"_measurement\"] == ").append(fluxString(measurement)).append(")")
                .append(" |> filter(fn: (r) => r[\"_field\"] == \"value_kwh\")")
                .append(" |> limit(n: 1)")
                .toString();
    }

    String buildFlux(String meteringPoint, DirectionType direction, Instant from, Instant to, int limit) {
        if (meteringPoint != null && !meteringPoint.isBlank()) {
            meteringPoint = meteringPoint.trim();
        }
        StringBuilder flux = new StringBuilder()
                .append("from(bucket: ").append(fluxString(bucket)).append(")")
                .append(rangeFlux(from, to))
                .append(" |> filter(fn: (r) => r[\"_measurement\"] == ").append(fluxString(measurement)).append(")")
                .append(" |> filter(fn: (r) => r[\"_field\"] == \"value_kwh\")");
        if (meteringPoint != null && !meteringPoint.isBlank()) {
            flux.append(" |> filter(fn: (r) => r[\"metering_point\"] == ").append(fluxString(meteringPoint)).append(")");
        }
        if (direction != null) {
            flux.append(" |> filter(fn: (r) => r[\"direction\"] == ").append(fluxString(direction.name())).append(")");
        }
        return flux.append(" |> group()")
                .append(" |> sort(columns: [\"_time\"])")
                .append(" |> limit(n: ").append(limit).append(")")
                .toString();
    }

    String buildForecastDatasetFlux(DirectionType direction, Instant from, Instant to) {
        if (direction == null) {
            throw new IllegalArgumentException("direction must be provided");
        }
        if (from == null || to == null) {
            throw new IllegalArgumentException("from and to must be provided");
        }

        return new StringBuilder()
                .append("from(bucket: ").append(fluxString(bucket)).append(")")
                .append(rangeFlux(from, to))
                .append(" |> filter(fn: (r) => r[\"_measurement\"] == ").append(fluxString(measurement)).append(")")
                .append(" |> filter(fn: (r) => r[\"_field\"] == \"value_kwh\")")
                .append(" |> filter(fn: (r) => r[\"direction\"] == ").append(fluxString(direction.name())).append(")")
                .append(" |> filter(fn: (r) => r[\"category\"] == ").append(fluxString(EnergyCategory.TOTAL.tagValue())).append(")")
                .append(" |> group(columns: [\"_time\"])")
                .append(" |> sum(column: \"_value\")")
                .append(" |> group()")
                .append(" |> sort(columns: [\"_time\"])")
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

    private InfluxDBClient newClient() {
        return InfluxDBClientFactory.create(influxUrl, resolvedToken().toCharArray(), org, bucket);
    }

    private List<FluxRecord> queryRecords(InfluxDBClient client, String flux) {
        return client.getQueryApi().query(flux, org).stream()
                .map(FluxTable::getRecords)
                .flatMap(List::stream)
                .toList();
    }

    private Point toPoint(EnergySeries series) {
        return Point.measurement(measurement)
                .addTag("metering_point", series.meteringPoint())
                .addTag("direction", series.direction().name())
                .addTag("category", series.category().tagValue())
                .addField("value_kwh", series.valueKwh())
                .time(series.timestamp(), WritePrecision.NS);
    }

    private EnergySeries toEnergySeries(FluxRecord record) {
        return new EnergySeries(
                String.valueOf(record.getValueByKey("metering_point")),
                parseTime(record.getTime()),
                DirectionType.valueOf(String.valueOf(record.getValueByKey("direction"))),
                EnergyCategory.fromTagValue(String.valueOf(record.getValueByKey("category"))),
                ((Number) record.getValue()).doubleValue()
        );
    }

    ForecastDatasetValue toForecastDatasetValue(Object[] row) {
        return new ForecastDatasetValue(parseTime(row[0]), ((Number) row[1]).doubleValue());
    }

    ForecastDatasetValue toForecastDatasetValue(FluxRecord record) {
        return new ForecastDatasetValue(parseTime(record.getTime()), ((Number) record.getValue()).doubleValue());
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

    private String rangeFlux(Instant from, Instant to) {
        Instant start = Optional.ofNullable(from).orElse(Instant.EPOCH);
        StringBuilder range = new StringBuilder(" |> range(start: time(v: ")
                .append(fluxString(start.toString()))
                .append(")");
        if (to != null) {
            range.append(", stop: time(v: ").append(fluxString(to.toString())).append(")");
        }
        return range.append(")").toString();
    }

    private String fluxString(String value) {
        return '"' + value.replace("\\", "\\\\").replace("\"", "\\\"") + '"';
    }
}
