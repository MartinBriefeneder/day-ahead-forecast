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
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

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
        Logger logger = mock(Logger.class);
        setField(service, "csvImportService", new EnergyCsvImportService());
        setField(service, "energySeriesRepository", new EnergySeriesRepository());
        setField(service, "logger", logger);

        IllegalArgumentException exception = assertThrows(IllegalArgumentException.class, () -> service.importCsv(csv));
        assertTrue(exception.getMessage().contains("CSV validation failed"));
        assertTrue(exception.getMessage().contains("row=3"));
        assertTrue(exception.getMessage().contains("column=Gesamtbezug [kWh]"));
        assertTrue(exception.getMessage().contains("rawValue=abc"));
        verify(logger).error(contains("Invalid numeric interval value"));
        assertEquals(content, Files.readString(csv));
    }

    private void setField(Object target, String name, Object value) throws Exception {
        Field field = target.getClass().getDeclaredField(name);
        field.setAccessible(true);
        field.set(target, value);
    }
}
