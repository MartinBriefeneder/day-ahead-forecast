package at.htl.service;

import at.htl.repository.EnergySeriesRepository;
import org.jboss.logging.Logger;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.lang.reflect.Field;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class EnergyImportServiceTest {

    @TempDir
    Path tempDir;

    @Test
    void importLogsDiagnosticsAndDoesNotMutateInput() throws Exception {
        String content = """
                Zeitpunkt;Gesamtbezug [kWh];Effektiv aus Gemeinschaft bezogen [kWh];Restbezug [kWh]
                ;AT001;AT001;AT001
                1.6.2025, 00:00:00;abc;1;0
                """;
        Path csv = tempDir.resolve("energy.csv");
        Files.writeString(csv, content);

        EnergyImportService service = new EnergyImportService();
        setField(service, "csvImportService", new EnergyCsvImportService());
        setField(service, "energySeriesRepository", new EnergySeriesRepository());
        setField(service, "logger", Logger.getLogger(EnergyImportService.class));

        IllegalArgumentException exception = assertThrows(IllegalArgumentException.class, () -> service.importCsv(csv));
        assertTrue(exception.getMessage().contains("CSV validation failed"));
        assertEquals(content, Files.readString(csv));
    }

    private void setField(Object target, String name, Object value) throws Exception {
        Field field = target.getClass().getDeclaredField(name);
        field.setAccessible(true);
        field.set(target, value);
    }
}
