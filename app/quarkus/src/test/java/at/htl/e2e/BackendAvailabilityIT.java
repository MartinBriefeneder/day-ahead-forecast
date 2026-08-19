package at.htl.e2e;

import io.restassured.response.Response;
import org.junit.jupiter.api.Test;

import java.time.Duration;
import java.util.function.Supplier;

import static io.restassured.RestAssured.given;
import static org.hamcrest.Matchers.equalTo;
import static org.hamcrest.Matchers.hasKey;
import static org.hamcrest.Matchers.instanceOf;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.fail;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

class BackendAvailabilityIT {

    @Test
    void localStackRespondsThroughExternalPorts() {
        assumeTrue(Boolean.getBoolean("availability.test"), "Set -Davailability.test=true to run the availability test.");

        waitForStatus("InfluxDB", influxUrl(), "/health", 200)
                .then()
                .body("status", equalTo("pass"));

        waitForStatus("Grafana", grafanaUrl(), "/api/health", 200)
                .then()
                .body("database", equalTo("ok"));

        Response backendResponse = waitFor("backend forecast dataset API", () -> given()
                .baseUri(backendUrl())
                .queryParam("target", "consumption")
                .queryParam("from", "2025-06-01T00:00:00Z")
                .queryParam("to", "2025-06-01T00:15:00Z")
                .when()
                .get("/api/forecast-datasets"), 200);

        backendResponse.then()
                .body("sampleInterval", equalTo("PT15M"))
                .body("targetColumn", equalTo("consumption"))
                .body("unit", equalTo("kWh"))
                .body("points", instanceOf(java.util.List.class));
    }

    @Test
    void backendCanPersistAndReadForecastRun() {
        assumeTrue(Boolean.getBoolean("availability.test"), "Set -Davailability.test=true to run the availability test.");

        String runId = "availability-test-" + System.currentTimeMillis();
        String body = """
                {
                  "runId": "%s",
                  "target": "consumption",
                  "model": "availability-smoke-test",
                  "modelFamily": "smoke-test",
                  "generatedAt": "2026-08-19T00:00:00Z",
                  "trainStart": "2025-06-01T00:00:00Z",
                  "trainEnd": "2025-06-02T00:00:00Z",
                  "forecastStart": "2025-06-02T00:00:00Z",
                  "forecastEnd": "2025-06-02T00:15:00Z",
                  "sampleInterval": "PT15M",
                  "horizon": "PT15M",
                  "reportPath": "target/availability-test.html",
                  "points": [
                    {
                      "timestamp": "2025-06-02T00:00:00Z",
                      "forecastKwh": 1.25,
                      "actualKwh": 1.0
                    }
                  ],
                  "metrics": [
                    {
                      "name": "mae",
                      "value": 0.25
                    }
                  ]
                }
                """.formatted(runId);

        waitFor("backend forecast run write API", () -> given()
                .baseUri(backendUrl())
                .contentType("application/json")
                .body(body)
                .when()
                .post("/api/forecast-runs"), 200)
                .then()
                .body("runId", equalTo(runId));

        waitFor("backend forecast run list API", () -> given()
                .baseUri(backendUrl())
                .queryParam("target", "consumption")
                .queryParam("limit", 50)
                .when()
                .get("/api/forecast-runs"), 200)
                .then()
                .body("find { it.runId == '" + runId + "' }.model", equalTo("availability-smoke-test"))
                .body("find { it.runId == '" + runId + "' }.target", equalTo("consumption"));

        waitFor("backend forecast comparison API", () -> given()
                .baseUri(backendUrl())
                .queryParam("limit", 10)
                .when()
                .get("/api/forecast-runs/{runId}/comparison", runId), 200)
                .then()
                .body("runId", equalTo(runId))
                .body("points[0]", hasKey("forecastKwh"));
    }

    private Response waitForStatus(String name, String baseUrl, String path, int expectedStatus) {
        return waitFor(name, () -> given().baseUri(baseUrl).when().get(path), expectedStatus);
    }

    private Response waitFor(String name, Supplier<Response> request, int expectedStatus) {
        long deadline = System.nanoTime() + timeout().toNanos();
        Throwable lastFailure = null;
        Response lastResponse = null;

        while (System.nanoTime() < deadline) {
            try {
                Response response = request.get();
                if (response.statusCode() == expectedStatus) {
                    return response;
                }
                lastResponse = response;
            } catch (Throwable failure) {
                lastFailure = failure;
            }

            sleep();
        }

        if (lastResponse != null) {
            assertEquals(expectedStatus, lastResponse.statusCode(), name + " did not return the expected status. Body: " + lastResponse.asString());
        }
        fail(name + " did not become available before timeout", lastFailure);
        throw new IllegalStateException("unreachable");
    }

    private Duration timeout() {
        return Duration.ofSeconds(Long.getLong("availability.timeout-seconds", 90));
    }

    private void sleep() {
        try {
            Thread.sleep(1_000);
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("Interrupted while waiting for availability", exception);
        }
    }

    private String backendUrl() {
        return System.getProperty("availability.backend-url", "http://localhost:8080");
    }

    private String influxUrl() {
        return System.getProperty("availability.influx-url", "http://localhost:8086");
    }

    private String grafanaUrl() {
        return System.getProperty("availability.grafana-url", "http://localhost:3000");
    }
}
