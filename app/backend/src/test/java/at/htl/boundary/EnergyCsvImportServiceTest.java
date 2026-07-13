package at.htl.boundary;

import at.htl.model.DirectionType;
import at.htl.model.EnergySeries;
import at.htl.service.EnergyCsvImportService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.time.ZoneId;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;

class EnergyCsvImportServiceTest {

    @TempDir
    Path tempDir;

    @Test
    void parsesDoubleHeaderEnergyCsvIntoSeriesGroups() throws Exception {
        Path csv = tempDir.resolve("energy.csv");
        Files.writeString(csv, """
                Zeitpunkt;Gesamtlieferung [kWh];Effektiv an Gemeinschaft geliefert [kWh];Restlieferung [kWh];Gesamtbezug [kWh];Effektiv aus Gemeinschaft bezogen [kWh];Restbezug [kWh]
                ;AT001;AT001;AT001;AT002;AT002;AT002
                1.10.2025, 00:00:00;1,5;1,25;0,25;2;0,5;1,5
                """);

        List<EnergySeries> result = new EnergyCsvImportService().parse(csv, ZoneId.of("Europe/Vienna"));

        assertEquals(2, result.size());
        assertEquals(new EnergySeries(
                "AT001",
                Instant.parse("2025-09-30T22:00:00Z"),
                DirectionType.DELIVERY,
                1.5,
                1.25,
                0.25
        ), result.getFirst());
        assertEquals(new EnergySeries(
                "AT002",
                Instant.parse("2025-09-30T22:00:00Z"),
                DirectionType.CONSUMPTION,
                2.0,
                0.5,
                1.5
        ), result.get(1));
    }
}
