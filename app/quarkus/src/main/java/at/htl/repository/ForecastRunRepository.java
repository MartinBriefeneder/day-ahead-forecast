package at.htl.repository;

import at.htl.model.ForecastComparisonPoint;
import at.htl.model.ForecastDatasetTarget;
import at.htl.model.ForecastDatasetValue;
import at.htl.model.ForecastMetric;
import at.htl.model.ForecastPoint;
import at.htl.model.ForecastRunRequest;
import at.htl.model.ForecastRunSummary;
import com.influxdb.client.InfluxDBClient;
import com.influxdb.client.InfluxDBClientFactory;
import com.influxdb.client.domain.WritePrecision;
import com.influxdb.client.write.Point;
import com.influxdb.query.FluxRecord;
import com.influxdb.query.FluxTable;
import jakarta.enterprise.context.ApplicationScoped;
import org.eclipse.microprofile.config.inject.ConfigProperty;

import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

@ApplicationScoped
public class ForecastRunRepository {

    @ConfigProperty(name = "energy.influx.url")
    String influxUrl;

    @ConfigProperty(name = "energy.influx.org")
    String org;

    @ConfigProperty(name = "energy.influx.bucket")
    String bucket;

    @ConfigProperty(name = "energy.influx.forecast-measurement", defaultValue = "energy_forecasts")
    String forecastMeasurement;

    @ConfigProperty(name = "energy.influx.forecast-evaluation-measurement", defaultValue = "forecast_evaluations")
    String evaluationMeasurement;

    @ConfigProperty(name = "energy.influx.forecast-run-metadata-measurement", defaultValue = "forecast_run_metadata")
    String metadataMeasurement;

    @ConfigProperty(name = "energy.influx.measurement", defaultValue = "energy_values")
    String actualMeasurement;

    @ConfigProperty(name = "energy.influx.token")
    Optional<String> token;

    public void save(ForecastRunRequest request) throws Exception {
        List<Point> points = new ArrayList<>(request.points().size() + request.metrics().size() + 1);
        points.add(toMetadataPoint(request));
        for (ForecastPoint forecastPoint : request.points()) {
            points.add(toForecastPoint(request, forecastPoint));
        }
        for (ForecastMetric metric : request.metrics()) {
            points.add(toEvaluationPoint(request, metric));
        }

        if (points.isEmpty()) {
            return;
        }

        try (InfluxDBClient client = newClient()) {
            client.getWriteApiBlocking().writePoints(bucket, org, points);
        }
    }

    public List<ForecastComparisonPoint> findComparison(String runId, int limit) throws Exception {
        String flux = buildComparisonFlux(runId, limit);
        try (InfluxDBClient client = newClient()) {
            return queryRecords(client, flux).stream().map(this::toComparisonPoint).toList();
        }
    }

    public List<ForecastComparisonPoint> findComparison(String runId, Instant from, Instant to, int limit) throws Exception {
        String flux = buildComparisonFlux(runId, from, to, limit);
        try (InfluxDBClient client = newClient()) {
            return queryRecords(client, flux).stream().map(this::toComparisonPoint).toList();
        }
    }

    public Optional<ForecastRunSummary> findRun(String runId) throws Exception {
        String flux = buildRunFlux(runId, true);
        try (InfluxDBClient client = newClient()) {
            try {
                return queryRecords(client, flux).stream().map(this::toRunSummary).findFirst();
            } catch (RuntimeException exception) {
                if (isMissingColumnException(exception, "report_path")) {
                    return queryRecords(client, buildRunFlux(runId, false)).stream().map(this::toRunSummary).findFirst();
                }
                throw exception;
            }
        }
    }

    public List<ForecastDatasetValue> findActualValues(ForecastDatasetTarget target, Instant from, Instant to, int limit) throws Exception {
        String flux = buildActualValuesFlux(target, from, to, limit);
        try (InfluxDBClient client = newClient()) {
            return queryRecords(client, flux).stream().map(this::toForecastDatasetValue).toList();
        }
    }

    public List<ForecastRunSummary> findRuns(String target, int limit) throws Exception {
        String flux = buildRunsFlux(target, limit);
        try (InfluxDBClient client = newClient()) {
            try {
                return queryRecords(client, flux).stream().map(this::toRunSummary).toList();
            } catch (RuntimeException exception) {
                if (isMissingTableException(exception, metadataMeasurement)) {
                    return List.of();
                }
                if (isMissingColumnException(exception, "report_path")) {
                    return queryRecords(client, buildRunsFlux(target, limit, false)).stream().map(this::toRunSummary).toList();
                }
                throw exception;
            }
        }
    }

    String buildComparisonFlux(String runId, int limit) {
        return buildComparisonFlux(runId, Instant.EPOCH, null, limit);
    }

    String buildComparisonFlux(String runId, Instant from, Instant to, int limit) {
        if (runId == null || runId.isBlank()) {
            throw new IllegalArgumentException("runId must be provided");
        }
        if (from == null) {
            throw new IllegalArgumentException("from must be provided");
        }
        if (to != null && !to.isAfter(from)) {
            throw new IllegalArgumentException("to must be after from");
        }
        if (limit <= 0 || limit > 100_000) {
            throw new IllegalArgumentException("limit must be between 1 and 100000");
        }

        return new StringBuilder()
                .append("from(bucket: ").append(fluxString(bucket)).append(")")
                .append(rangeFlux(from, to))
                .append(" |> filter(fn: (r) => r[\"_measurement\"] == ").append(fluxString(forecastMeasurement)).append(")")
                .append(" |> filter(fn: (r) => r[\"run_id\"] == ").append(fluxString(runId)).append(")")
                .append(" |> filter(fn: (r) => contains(value: r[\"_field\"], set: [\"forecast_kwh\", \"actual_kwh\", \"error_kwh\"]))")
                .append(" |> pivot(rowKey: [\"_time\"], columnKey: [\"_field\"], valueColumn: \"_value\")")
                .append(" |> group()")
                .append(" |> sort(columns: [\"_time\"])")
                .append(" |> limit(n: ").append(limit).append(")")
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

    ForecastComparisonPoint toComparisonPoint(FluxRecord record) {
        return new ForecastComparisonPoint(
                parseTime(record.getTime()),
                ((Number) record.getValueByKey("forecast_kwh")).doubleValue(),
                numberOrNull(record.getValueByKey("actual_kwh")),
                numberOrNull(record.getValueByKey("error_kwh"))
        );
    }

    String buildRunsFlux(String target, int limit) {
        return buildRunsFlux(target, limit, true);
    }

    String buildRunsFlux(String target, int limit, boolean includeReportPath) {
        if (limit <= 0 || limit > 1000) {
            throw new IllegalArgumentException("limit must be between 1 and 1000");
        }

        StringBuilder fields = new StringBuilder("[\"generated_at\", \"train_start\", \"train_end\", \"forecast_start\", \"forecast_end\", \"sample_interval\", \"horizon\", \"model_family\"");
        if (includeReportPath) {
            fields.append(", \"report_path\"");
        }
        fields.append("]");

        StringBuilder flux = new StringBuilder()
                .append("from(bucket: ").append(fluxString(bucket)).append(")")
                .append(allTimeRangeFlux())
                .append(" |> filter(fn: (r) => r[\"_measurement\"] == ").append(fluxString(metadataMeasurement)).append(")")
                .append(" |> filter(fn: (r) => contains(value: r[\"_field\"], set: ").append(fields).append("))");
        if (target != null && !target.isBlank()) {
            flux.append(" |> filter(fn: (r) => r[\"target\"] == ").append(fluxString(target)).append(")");
        }
        return flux.append(" |> pivot(rowKey: [\"_time\"], columnKey: [\"_field\"], valueColumn: \"_value\")")
                .append(" |> group()")
                .append(" |> sort(columns: [\"_time\"], desc: true)")
                .append(" |> limit(n: ").append(limit).append(")")
                .toString();
    }

    String buildRunFlux(String runId, boolean includeReportPath) {
        if (runId == null || runId.isBlank()) {
            throw new IllegalArgumentException("runId must be provided");
        }
        StringBuilder fields = new StringBuilder("[\"generated_at\", \"train_start\", \"train_end\", \"forecast_start\", \"forecast_end\", \"sample_interval\", \"horizon\", \"model_family\"");
        if (includeReportPath) {
            fields.append(", \"report_path\"");
        }
        fields.append("]");

        return new StringBuilder()
                .append("from(bucket: ").append(fluxString(bucket)).append(")")
                .append(allTimeRangeFlux())
                .append(" |> filter(fn: (r) => r[\"_measurement\"] == ").append(fluxString(metadataMeasurement)).append(")")
                .append(" |> filter(fn: (r) => r[\"run_id\"] == ").append(fluxString(runId)).append(")")
                .append(" |> filter(fn: (r) => contains(value: r[\"_field\"], set: ").append(fields).append("))")
                .append(" |> pivot(rowKey: [\"_time\"], columnKey: [\"_field\"], valueColumn: \"_value\")")
                .append(" |> group()")
                .append(" |> sort(columns: [\"_time\"], desc: true)")
                .append(" |> limit(n: 1)")
                .toString();
    }

    String buildActualValuesFlux(ForecastDatasetTarget target, Instant from, Instant to, int limit) {
        if (target == null) {
            throw new IllegalArgumentException("target must be provided");
        }
        if (from == null || to == null || !to.isAfter(from)) {
            throw new IllegalArgumentException("from and to must define a non-empty range");
        }
        if (limit <= 0 || limit > 100_000) {
            throw new IllegalArgumentException("limit must be between 1 and 100000");
        }
        return new StringBuilder()
                .append("from(bucket: ").append(fluxString(bucket)).append(")")
                .append(rangeFlux(from, to))
                .append(" |> filter(fn: (r) => r[\"_measurement\"] == ").append(fluxString(actualMeasurement)).append(")")
                .append(" |> filter(fn: (r) => r[\"_field\"] == \"value_kwh\")")
                .append(" |> filter(fn: (r) => r[\"direction\"] == ").append(fluxString(target.direction().name())).append(")")
                .append(" |> filter(fn: (r) => r[\"category\"] == \"total\")")
                .append(" |> group(columns: [\"_time\"])")
                .append(" |> sum(column: \"_value\")")
                .append(" |> group()")
                .append(" |> sort(columns: [\"_time\"])")
                .append(" |> limit(n: ").append(limit).append(")")
                .toString();
    }

    ForecastRunSummary toRunSummary(Object[] row) {
        return new ForecastRunSummary(
                String.valueOf(row[0]),
                String.valueOf(row[1]),
                String.valueOf(row[2]),
                parseNullableInstant(row[3]),
                parseNullableInstant(row[4]),
                parseNullableInstant(row[5]),
                parseNullableInstant(row[6]),
                parseNullableInstant(row[7]),
                stringOrNull(row[8]),
                stringOrNull(row[9]),
                stringOrNull(row[10]),
                row.length > 11 ? stringOrNull(row[11]) : null
        );
    }

    ForecastRunSummary toRunSummary(FluxRecord record) {
        return new ForecastRunSummary(
                String.valueOf(record.getValueByKey("run_id")),
                String.valueOf(record.getValueByKey("model")),
                String.valueOf(record.getValueByKey("target")),
                parseNullableInstant(record.getValueByKey("generated_at")),
                parseNullableInstant(record.getValueByKey("train_start")),
                parseNullableInstant(record.getValueByKey("train_end")),
                parseNullableInstant(record.getValueByKey("forecast_start")),
                parseNullableInstant(record.getValueByKey("forecast_end")),
                stringOrNull(record.getValueByKey("sample_interval")),
                stringOrNull(record.getValueByKey("horizon")),
                stringOrNull(record.getValueByKey("model_family")),
                stringOrNull(record.getValueByKey("report_path"))
        );
    }

    ForecastDatasetValue toForecastDatasetValue(Object[] row) {
        return new ForecastDatasetValue(parseTime(row[0]), ((Number) row[1]).doubleValue());
    }

    ForecastDatasetValue toForecastDatasetValue(FluxRecord record) {
        return new ForecastDatasetValue(parseTime(record.getTime()), ((Number) record.getValue()).doubleValue());
    }

    boolean isMissingColumnException(RuntimeException exception, String column) {
        String message = exception.getMessage();
        return message != null && (message.contains("No field named " + column + ".")
                || message.contains("column \"" + column + "\" does not exist"));
    }

    boolean isMissingTableException(RuntimeException exception, String table) {
        String message = exception.getMessage();
        return message != null && (message.contains("table 'public.iox." + table + "' not found")
                || message.contains("measurement \"" + table + "\" not found"));
    }

    private Point toForecastPoint(ForecastRunRequest request, ForecastPoint forecastPoint) {
        Point point = Point.measurement(forecastMeasurement)
                .addTag("run_id", request.runId())
                .addTag("target", request.target())
                .addTag("model", request.model())
                .addField("forecast_kwh", forecastPoint.forecastKwh())
                .time(forecastPoint.timestamp(), WritePrecision.NS);

        if (forecastPoint.actualKwh() != null) {
            point.addField("actual_kwh", forecastPoint.actualKwh());
            point.addField("error_kwh", forecastPoint.forecastKwh() - forecastPoint.actualKwh());
        }
        return point;
    }

    Point toMetadataPoint(ForecastRunRequest request) {
        Instant generatedAt = Optional.ofNullable(request.generatedAt()).orElseGet(Instant::now);
        Point point = Point.measurement(metadataMeasurement)
                .addTag("run_id", request.runId())
                .addTag("target", request.target())
                .addTag("model", request.model())
                .addField("generated_at", generatedAt.toString())
                .addField("forecast_start", request.forecastStart().toString())
                .addField("forecast_end", request.forecastEnd().toString())
                .addField("sample_interval", request.sampleInterval())
                .time(generatedAt, WritePrecision.NS);

        setOptionalInstant(point, "train_start", request.trainStart());
        setOptionalInstant(point, "train_end", request.trainEnd());
        setOptionalString(point, "horizon", request.horizon());
        setOptionalString(point, "model_family", request.modelFamily());
        setOptionalString(point, "report_path", request.reportPath());
        return point;
    }

    private Point toEvaluationPoint(ForecastRunRequest request, ForecastMetric metric) {
        Instant generatedAt = Optional.ofNullable(request.generatedAt()).orElseGet(Instant::now);
        return Point.measurement(evaluationMeasurement)
                .addTag("run_id", request.runId())
                .addTag("target", request.target())
                .addTag("model", request.model())
                .addTag("metric", metric.name())
                .addTag("forecast_start", request.forecastStart().toString())
                .addTag("forecast_end", request.forecastEnd().toString())
                .addTag("sample_interval", request.sampleInterval())
                .addField("value", metric.value())
                .time(generatedAt, WritePrecision.NS);
    }

    private void setOptionalInstant(Point point, String field, Instant value) {
        if (value != null) {
            point.addField(field, value.toString());
        }
    }

    private void setOptionalString(Point point, String field, String value) {
        if (value != null && !value.isBlank()) {
            point.addField(field, value);
        }
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

    private Double numberOrNull(Object value) {
        if (value == null) {
            return null;
        }
        return ((Number) value).doubleValue();
    }

    private String stringOrNull(Object value) {
        return value == null ? null : String.valueOf(value);
    }

    private Instant parseNullableInstant(Object value) {
        return value == null ? null : Instant.parse(String.valueOf(value));
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

    private String allTimeRangeFlux() {
        return rangeFlux(Instant.EPOCH, null);
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
