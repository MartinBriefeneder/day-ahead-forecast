package at.htl.service;

import at.htl.model.EnergySeries;
import jakarta.enterprise.context.ApplicationScoped;
import org.eclipse.microprofile.config.inject.ConfigProperty;

import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.List;
import java.util.StringJoiner;

@ApplicationScoped
public class InfluxDbWriteService {

    private final HttpClient httpClient = HttpClient.newHttpClient();

    @ConfigProperty(name = "energy.influx.url")
    String influxUrl;

    @ConfigProperty(name = "energy.influx.database")
    String database;

    @ConfigProperty(name = "energy.influx.measurement")
    String measurement;

    @ConfigProperty(name = "energy.influx.batch-size")
    int batchSize;

    public void write(List<EnergySeries> series) throws IOException, InterruptedException {
        if (series.isEmpty()) {
            return;
        }
        if (batchSize <= 0) {
            throw new IllegalStateException("energy.influx.batch-size must be greater than 0");
        }

        for (int start = 0; start < series.size(); start += batchSize) {
            int end = Math.min(start + batchSize, series.size());
            writeBatch(series.subList(start, end));
        }
    }

    private void writeBatch(List<EnergySeries> batch) throws IOException, InterruptedException {
        StringJoiner body = new StringJoiner("\n");
        for (EnergySeries series : batch) {
            body.add(toLineProtocol(series));
        }

        HttpRequest request = HttpRequest.newBuilder(writeUri())
                .header("Content-Type", "text/plain; charset=utf-8")
                .POST(HttpRequest.BodyPublishers.ofString(body.toString(), StandardCharsets.UTF_8))
                .build();

        HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() < 200 || response.statusCode() >= 300) {
            throw new IOException("InfluxDB write failed with status " + response.statusCode() + ": " + response.body());
        }
    }

    URI writeUri() {
        String separator = influxUrl.endsWith("/") ? "" : "/";
        return URI.create(influxUrl + separator + "api/v3/write_lp?db=" + urlEncode(database));
    }

    String toLineProtocol(EnergySeries series) {
        return escapeMeasurement(measurement)
                + ",identifier=" + escapeTagValue(series.identifier())
                + ",direction=" + escapeTagValue(series.energyDirection().name())
                + " total=" + series.total()
                + ",community_effective=" + series.community_effective()
                + ",residual=" + series.residual()
                + " " + timestampNanos(series.timestamp());
    }

    private long timestampNanos(Instant timestamp) {
        return timestamp.getEpochSecond() * 1_000_000_000L + timestamp.getNano();
    }

    private String escapeMeasurement(String value) {
        return value.replace(" ", "\\ ").replace(",", "\\,");
    }

    private String escapeTagValue(String value) {
        return value.replace(" ", "\\ ").replace(",", "\\,").replace("=", "\\=");
    }

    private String urlEncode(String value) {
        return URLEncoder.encode(value, StandardCharsets.UTF_8);
    }
}
