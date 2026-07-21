package at.htl.resource;

import at.htl.model.ForecastDatasetValue;
import at.htl.repository.EnergySeriesRepository;
import io.quarkus.test.InjectMock;
import io.quarkus.test.junit.QuarkusTest;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;

import static io.restassured.RestAssured.given;
import static org.hamcrest.Matchers.equalTo;
import static org.hamcrest.Matchers.hasSize;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

@QuarkusTest
class ForecastDatasetResourceTest {

    @InjectMock
    EnergySeriesRepository energySeriesRepository;

    @Test
    void returnsLoadDatasetResponse() throws Exception {
        when(energySeriesRepository.findForecastDataset(any(), any(), any())).thenReturn(List.of(
                new ForecastDatasetValue(Instant.parse("2025-06-01T00:00:00Z"), 12.25),
                new ForecastDatasetValue(Instant.parse("2025-06-01T00:15:00Z"), 13.5)
        ));

        given()
                .queryParam("target", "load")
                .queryParam("from", "2025-06-01T00:00:00Z")
                .queryParam("to", "2025-06-02T00:00:00Z")
                .when().get("/api/forecast-datasets")
                .then()
                .statusCode(200)
                .body("sampleInterval", equalTo("PT15M"))
                .body("targetColumn", equalTo("load"))
                .body("unit", equalTo("kWh"))
                .body("points", hasSize(2))
                .body("points[0].timestamp", equalTo("2025-06-01T00:00:00Z"))
                .body("points[0].load", equalTo(12.25F));
    }

    @Test
    void returnsGenerationDatasetResponse() throws Exception {
        when(energySeriesRepository.findForecastDataset(any(), any(), any())).thenReturn(List.of(
                new ForecastDatasetValue(Instant.parse("2025-06-01T00:00:00Z"), 3.0)
        ));

        given()
                .queryParam("target", "generation")
                .queryParam("from", "2025-06-01T00:00:00Z")
                .queryParam("to", "2025-06-02T00:00:00Z")
                .when().get("/api/forecast-datasets")
                .then()
                .statusCode(200)
                .body("targetColumn", equalTo("generation"))
                .body("points[0].generation", equalTo(3.0F));
    }

    @Test
    void returnsEmptyPointsForEmptyRange() throws Exception {
        when(energySeriesRepository.findForecastDataset(any(), any(), any())).thenReturn(List.of());

        given()
                .queryParam("target", "load")
                .queryParam("from", "2025-06-01T00:00:00Z")
                .queryParam("to", "2025-06-02T00:00:00Z")
                .when().get("/api/forecast-datasets")
                .then()
                .statusCode(200)
                .body("points", hasSize(0));
    }

    @Test
    void rejectsInvalidRequests() {
        given()
                .queryParam("target", "other")
                .queryParam("from", "2025-06-01T00:00:00Z")
                .queryParam("to", "2025-06-02T00:00:00Z")
                .when().get("/api/forecast-datasets")
                .then()
                .statusCode(400);

        given()
                .queryParam("target", "load")
                .queryParam("from", "2025-06-02T00:00:00Z")
                .queryParam("to", "2025-06-01T00:00:00Z")
                .when().get("/api/forecast-datasets")
                .then()
                .statusCode(400);
    }
}
