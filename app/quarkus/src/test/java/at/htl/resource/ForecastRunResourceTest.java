package at.htl.resource;

import at.htl.model.ForecastComparisonPoint;
import at.htl.model.ForecastRunSummary;
import at.htl.repository.ForecastRunRepository;
import io.quarkus.test.InjectMock;
import io.quarkus.test.junit.QuarkusTest;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;

import static io.restassured.RestAssured.given;
import static org.hamcrest.Matchers.equalTo;
import static org.hamcrest.Matchers.hasSize;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@QuarkusTest
class ForecastRunResourceTest {

    @InjectMock
    ForecastRunRepository forecastRunRepository;

    @Test
    void savesForecastRun() throws Exception {
        given()
                .contentType("application/json")
                .body("""
                        {
                          "runId": "run-1",
                          "model": "historical-average",
                          "target": "consumption",
                          "generatedAt": "2026-01-01T00:00:00Z",
                          "forecastStart": "2025-12-01T00:00:00Z",
                          "forecastEnd": "2025-12-15T00:00:00Z",
                          "sampleInterval": "PT15M",
                          "horizon": "P14D",
                          "points": [
                            {"timestamp": "2025-12-01T00:00:00Z", "forecastKwh": 12.5}
                          ],
                          "metrics": [
                            {"name": "mae_kwh", "value": 0.5}
                          ]
                        }
                        """)
                .when().post("/api/forecast-runs")
                .then()
                .statusCode(200)
                .body("runId", equalTo("run-1"))
                .body("forecastPoints", equalTo(1))
                .body("metrics", equalTo(1));

        verify(forecastRunRepository).save(any());
    }

    @Test
    void rejectsInvalidForecastRun() {
        given()
                .contentType("application/json")
                .body("{}")
                .when().post("/api/forecast-runs")
                .then()
                .statusCode(400);
    }

    @Test
    void returnsComparison() throws Exception {
        when(forecastRunRepository.findComparison(anyString(), anyInt())).thenReturn(List.of(
                new ForecastComparisonPoint(Instant.parse("2025-12-01T00:00:00Z"), 12.5, 12.0, 0.5)
        ));

        given()
                .queryParam("limit", 50)
                .when().get("/api/forecast-runs/run-1/comparison")
                .then()
                .statusCode(200)
                .body("runId", equalTo("run-1"))
                .body("points", hasSize(1))
                .body("points[0].forecastKwh", equalTo(12.5F))
                .body("points[0].actualKwh", equalTo(12.0F))
                .body("points[0].errorKwh", equalTo(0.5F));
    }

    @Test
    void listsForecastRuns() throws Exception {
        when(forecastRunRepository.findRuns("generation", 25)).thenReturn(List.of(
                new ForecastRunSummary(
                        "run-1",
                        "openstef-default-xgboost",
                        "generation",
                        Instant.parse("2026-01-01T00:00:00Z"),
                        Instant.parse("2025-11-01T00:00:00Z"),
                        Instant.parse("2025-12-01T00:00:00Z"),
                        Instant.parse("2025-12-01T00:00:00Z"),
                        Instant.parse("2025-12-02T00:00:00Z"),
                        "PT15M",
                        "PT36H",
                        "openstef-xgboost",
                        "app/reports/forecast-runs/openstef-default-xgboost-report.md"
                )
        ));

        given()
                .queryParam("target", "generation")
                .queryParam("limit", 25)
                .when().get("/api/forecast-runs")
                .then()
                .statusCode(200)
                .body("[0].runId", equalTo("run-1"))
                .body("[0].model", equalTo("openstef-default-xgboost"))
                .body("[0].target", equalTo("generation"))
                .body("[0].forecastStart", equalTo("2025-12-01T00:00:00Z"));
    }
}
