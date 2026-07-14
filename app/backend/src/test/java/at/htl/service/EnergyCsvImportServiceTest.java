package at.htl.service;

import at.htl.model.CsvValidationDiagnostic;
import at.htl.model.EnergyCsvImportResult;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.ZoneId;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class EnergyCsvImportServiceTest {

    @TempDir
    Path tempDir;

    private final EnergyCsvImportService service = new EnergyCsvImportService();

    @Test
    void validCsvProducesSeriesWithoutDiagnostics() throws IOException {
        EnergyCsvImportResult result = service.parse(csv("""
                Zeitpunkt;Bezug total;Bezug community;Bezug residual
                ;AT001;AT001;AT001
                1.6.2025, 00:00:00;1,25;0,50;0,75
                1.6.2025, 00:15:00;2;1;1
                """));

        assertTrue(result.diagnostics().isEmpty());
        assertEquals(2, result.series().size());
    }

    @Test
    void invalidStructureIsReported() throws IOException {
        EnergyCsvImportResult missingTimestamp = service.parse(csv("""
                Time;Bezug total;Bezug community;Bezug residual
                ;AT001;AT001;AT001
                1.6.2025, 00:00:00;1;1;0
                """));
        EnergyCsvImportResult missingColumns = service.parse(csv("""
                Zeitpunkt
                ;
                1.6.2025, 00:00:00
                """));

        assertTrue(missingTimestamp.diagnostics().stream().anyMatch(diagnostic ->
                diagnostic.severity() == CsvValidationDiagnostic.Severity.ERROR
                        && diagnostic.message().contains("Zeitpunkt")));
        assertTrue(missingColumns.diagnostics().stream().anyMatch(diagnostic ->
                diagnostic.message().contains("No importable data columns")));
    }

    @Test
    void invalidRowsAreReportedWithLocationContext() throws IOException {
        EnergyCsvImportResult result = service.parse(csv("""
                Zeitpunkt;Bezug total;Bezug community;Bezug residual
                ;AT001;AT001;AT001
                invalid;1;1;0
                1.6.2025, 00:10:00;1;1;0
                1.6.2025, 00:15:00;abc;;0
                """));

        assertTrue(result.diagnostics().stream().anyMatch(diagnostic ->
                diagnostic.message().contains("Invalid timestamp")
                        && diagnostic.rowNumber() == 3
                        && diagnostic.columnName().equals("Zeitpunkt")
                        && diagnostic.rawValue().equals("invalid")));
        assertTrue(result.diagnostics().stream().anyMatch(diagnostic ->
                diagnostic.message().contains("quarter-hour") && diagnostic.rowNumber() == 4));
        assertTrue(result.diagnostics().stream().anyMatch(diagnostic ->
                diagnostic.message().contains("Invalid numeric")
                        && diagnostic.rowNumber() == 5
                        && diagnostic.rawValue().equals("abc")));
        assertTrue(result.diagnostics().stream().anyMatch(diagnostic ->
                diagnostic.message().contains("Missing interval") && diagnostic.rowNumber() == 5));
    }

    @Test
    void duplicateValuesAndDaylightSavingAnomaliesAreReported() throws IOException {
        EnergyCsvImportResult duplicate = service.parse(csv("""
                Zeitpunkt;Bezug total;Bezug community;Bezug residual
                ;AT001;AT001;AT001
                1.6.2025, 00:00:00;1;1;0
                1.6.2025, 00:00:00;2;1;1
                """));
        EnergyCsvImportResult daylightSaving = service.parse(csv("""
                Zeitpunkt;Bezug total;Bezug community;Bezug residual
                ;AT001;AT001;AT001
                30.3.2025, 02:15:00;1;1;0
                """), ZoneId.of("Europe/Vienna"));

        assertTrue(duplicate.diagnostics().stream().anyMatch(diagnostic ->
                diagnostic.message().contains("Duplicate")));
        assertTrue(daylightSaving.diagnostics().stream().anyMatch(diagnostic ->
                diagnostic.message().contains("daylight-saving")));
    }

    private Path csv(String content) throws IOException {
        Path file = tempDir.resolve("energy.csv");
        Files.writeString(file, content);
        return file;
    }
}
