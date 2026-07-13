package at.htl.service;

import org.junit.jupiter.api.Disabled;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.assertTrue;

@Disabled("Requires local InfluxDB 3 Core on localhost:8181 and writes real data")
class EnergyImportServiceManualIT {

    @TempDir
    Path tempDir;

    @Test
    void importsCsvIntoInfluxDb() throws Exception {
        Path csv = tempDir.resolve("energy.csv");
        Files.writeString(csv, """
                Zeitpunkt;Gesamtlieferung [kWh];Effektiv an Gemeinschaft geliefert [kWh];Restlieferung [kWh];Gesamtbezug [kWh];Effektiv aus Gemeinschaft bezogen [kWh];Restbezug [kWh]
                ;AT-MANUAL-001;AT-MANUAL-001;AT-MANUAL-001;AT-MANUAL-002;AT-MANUAL-002;AT-MANUAL-002
                1.10.2025, 00:00:00;1,5;1,25;0,25;2;0,5;1,5
                """);

        InfluxDbWriteService influxDbWriteService = new InfluxDbWriteService();
        influxDbWriteService.influxUrl = "http://localhost:8181";
        influxDbWriteService.database = "energy";
        influxDbWriteService.measurement = "energy_series";
        influxDbWriteService.batchSize = 10_000;

        EnergyImportService energyImportService = new EnergyImportService();
        energyImportService.csvImportService = new EnergyCsvImportService();
        energyImportService.influxDbWriteService = influxDbWriteService;

        int imported = energyImportService.importCsv(csv);

        assertTrue(imported == 2);
    }
}
