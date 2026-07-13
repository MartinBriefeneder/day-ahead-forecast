package at.htl.service;

import at.htl.model.DirectionType;
import at.htl.model.EnergySeries;
import org.junit.jupiter.api.Test;

import java.time.Instant;

import static org.junit.jupiter.api.Assertions.assertEquals;

class InfluxDbWriteServiceTest {

    @Test
    void convertsEnergySeriesToInfluxLineProtocol() {
        InfluxDbWriteService service = new InfluxDbWriteService();
        service.measurement = "energy_series";

        String lineProtocol = service.toLineProtocol(new EnergySeries(
                "AT001",
                Instant.parse("2025-09-30T22:00:00.123456789Z"),
                DirectionType.DELIVERY,
                1.5,
                1.25,
                0.25
        ));

        assertEquals(
                "energy_series,identifier=AT001,direction=DELIVERY total=1.5,community_effective=1.25,residual=0.25 1759269600123456789",
                lineProtocol
        );
    }

    @Test
    void escapesMeasurementAndTagValues() {
        InfluxDbWriteService service = new InfluxDbWriteService();
        service.measurement = "energy series";

        String lineProtocol = service.toLineProtocol(new EnergySeries(
                "AT 001,main=house",
                Instant.parse("2025-09-30T22:00:00Z"),
                DirectionType.CONSUMPTION,
                2.0,
                0.5,
                1.5
        ));

        assertEquals(
                "energy\\ series,identifier=AT\\ 001\\,main\\=house,direction=CONSUMPTION total=2.0,community_effective=0.5,residual=1.5 1759269600000000000",
                lineProtocol
        );
    }

    @Test
    void buildsInfluxWriteUriForConfiguredDatabase() {
        InfluxDbWriteService service = new InfluxDbWriteService();
        service.influxUrl = "http://localhost:8181";
        service.database = "energy data";

        assertEquals("http://localhost:8181/api/v3/write_lp?db=energy+data", service.writeUri().toString());
    }
}
