package at.htl.resource;

import at.htl.repository.EnergySeriesRepository;
import io.quarkus.test.InjectMock;
import io.quarkus.test.junit.QuarkusTest;
import org.junit.jupiter.api.Test;

import static io.restassured.RestAssured.given;
import static org.hamcrest.Matchers.equalTo;
import static org.mockito.Mockito.when;

@QuarkusTest
class EnergyImportResourceTest {

    @InjectMock
    EnergySeriesRepository energySeriesRepository;

    @Test
    void returnsImportedDataStatus() throws Exception {
        when(energySeriesRepository.hasImportedValues()).thenReturn(true);

        given()
                .when().get("/api/energy-import/status")
                .then()
                .statusCode(200)
                .body("hasImportedData", equalTo(true));
    }
}
