package at.htl.service;

import at.htl.model.CsvValidationDiagnostic;
import at.htl.model.EnergyCsvImportResult;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
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
                Zeitpunkt;Gesamtbezug [kWh];Effektiv aus Gemeinschaft bezogen [kWh];Restbezug [kWh]
                ;AT001;AT001;AT001
                1.6.2025, 00:00:00;1,25;0,50;0,75
                1.6.2025, 00:15:00;2;1;1
                """));

        assertTrue(result.diagnostics().isEmpty());
        assertEquals(2, result.series().size());
        assertEquals(Instant.parse("2025-05-31T22:00:00Z"), result.series().getFirst().timestamp());
    }

    @Test
    void validDeliveryCsvProducesDeliverySeries() throws IOException {
        EnergyCsvImportResult result = service.parse(csv("""
                Zeitpunkt;Gesamtlieferung [kWh];Effektiv an Gemeinschaft geliefert [kWh];Restlieferung [kWh]
                ;AT001;AT001;AT001
                1.6.2025, 00:00:00;1,25;0,50;0,75
                """));

        assertTrue(result.diagnostics().isEmpty());
        assertEquals(1, result.series().size());
        assertEquals(at.htl.model.DirectionType.DELIVERY, result.series().getFirst().direction());
    }

    @Test
    void parsesCsvTimestampsAsViennaLocalTime() throws IOException {
        EnergyCsvImportResult result = service.parse(csv("""
                Zeitpunkt;Gesamtbezug [kWh];Effektiv aus Gemeinschaft bezogen [kWh];Restbezug [kWh]
                ;AT001;AT001;AT001
                1.6.2025, 00:00:00;1;1;0
                1.1.2026, 00:00:00;1;1;0
                """));

        assertEquals(Instant.parse("2025-05-31T22:00:00Z"), result.series().get(0).timestamp());
        assertEquals(Instant.parse("2025-12-31T23:00:00Z"), result.series().get(1).timestamp());
    }

    @Test
    void invalidStructureIsReported() throws IOException {
        EnergyCsvImportResult missingTimestamp = service.parse(csv("""
                Time;Gesamtbezug [kWh];Effektiv aus Gemeinschaft bezogen [kWh];Restbezug [kWh]
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
                Zeitpunkt;Gesamtbezug [kWh];Effektiv aus Gemeinschaft bezogen [kWh];Restbezug [kWh]
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
    void reportsMissingHeaderRowsUnknownCategoriesAndMalformedNumericValues() throws IOException {
        EnergyCsvImportResult missingHeaderRow = service.parse(csv("""
                Zeitpunkt;Gesamtbezug [kWh]
                """));
        EnergyCsvImportResult unknownCategory = service.parse(csv("""
                Zeitpunkt;Unbekannte Kategorie [kWh];Effektiv aus Gemeinschaft bezogen [kWh];Restbezug [kWh]
                ;AT001;AT001;AT001
                1.6.2025, 00:00:00;1;1;0
                """));
        EnergyCsvImportResult malformedNumber = service.parse(csv("""
                Zeitpunkt;Gesamtbezug [kWh];Effektiv aus Gemeinschaft bezogen [kWh];Restbezug [kWh]
                ;AT001;AT001;AT001
                1.6.2025, 00:00:00;not-a-number;1;0
                """));

        assertTrue(missingHeaderRow.diagnostics().stream().anyMatch(diagnostic ->
                diagnostic.message().contains("two header rows")));
        assertTrue(unknownCategory.diagnostics().stream().anyMatch(diagnostic ->
                diagnostic.message().contains("Cannot determine energy direction")
                        && diagnostic.rawValue().contains("Unbekannte Kategorie")));
        assertTrue(malformedNumber.diagnostics().stream().anyMatch(diagnostic ->
                diagnostic.message().contains("Invalid numeric")
                        && diagnostic.rowNumber() == 3
                        && diagnostic.rawValue().equals("not-a-number")));
    }

    @Test
    void duplicateValuesAndDaylightSavingAnomaliesAreReported() throws IOException {
        EnergyCsvImportResult duplicate = service.parse(csv("""
                Zeitpunkt;Gesamtbezug [kWh];Effektiv aus Gemeinschaft bezogen [kWh];Restbezug [kWh]
                ;AT001;AT001;AT001
                1.6.2025, 00:00:00;1;1;0
                1.6.2025, 00:00:00;2;1;1
                """));
        EnergyCsvImportResult daylightSaving = service.parse(csv("""
                Zeitpunkt;Gesamtbezug [kWh];Effektiv aus Gemeinschaft bezogen [kWh];Restbezug [kWh]
                ;AT001;AT001;AT001
                30.3.2025, 02:15:00;1;1;0
                """), ZoneId.of("Europe/Vienna"));

        assertTrue(duplicate.diagnostics().stream().anyMatch(diagnostic ->
                diagnostic.message().contains("Duplicate")));
        assertEquals(2, duplicate.diagnostics().stream()
                .filter(diagnostic -> diagnostic.message().contains("Duplicate timestamp"))
                .count());
        assertTrue(daylightSaving.diagnostics().stream().anyMatch(diagnostic ->
                diagnostic.message().contains("daylight-saving")));
    }

    @Test
    void missingIntervalsAndOrderingDeviationsAreReported() throws IOException {
        EnergyCsvImportResult result = service.parse(csv("""
                Zeitpunkt;Gesamtbezug [kWh];Effektiv aus Gemeinschaft bezogen [kWh];Restbezug [kWh]
                ;AT001;AT001;AT001
                1.6.2025, 00:00:00;1;1;0
                1.6.2025, 00:30:00;1;1;0
                1.6.2025, 00:15:00;1;1;0
                """));

        assertTrue(result.diagnostics().stream().anyMatch(diagnostic ->
                diagnostic.message().contains("Missing quarter-hour")
                        && diagnostic.rawValue().contains("missing=2025-06-01T00:15")));
        assertTrue(result.diagnostics().stream().anyMatch(diagnostic ->
                diagnostic.message().contains("Timestamp ordering deviation")));
    }

    @Test
    void reportsDstSpringGapAutumnOverlapAndNoDiagnosticOutsideTransitions() throws IOException {
        EnergyCsvImportResult springGap = service.parse(csv("""
                Zeitpunkt;Gesamtbezug [kWh];Effektiv aus Gemeinschaft bezogen [kWh];Restbezug [kWh]
                ;AT001;AT001;AT001
                30.3.2025, 02:15:00;1;1;0
                """), ZoneId.of("Europe/Vienna"));
        EnergyCsvImportResult autumnOverlap = service.parse(csv("""
                Zeitpunkt;Gesamtbezug [kWh];Effektiv aus Gemeinschaft bezogen [kWh];Restbezug [kWh]
                ;AT001;AT001;AT001
                26.10.2025, 02:15:00;1;1;0
                """), ZoneId.of("Europe/Vienna"));
        EnergyCsvImportResult nonTransition = service.parse(csv("""
                Zeitpunkt;Gesamtbezug [kWh];Effektiv aus Gemeinschaft bezogen [kWh];Restbezug [kWh]
                ;AT001;AT001;AT001
                1.6.2025, 00:00:00;1;1;0
                1.6.2025, 00:15:00;1;1;0
                """), ZoneId.of("Europe/Vienna"));

        assertTrue(springGap.diagnostics().stream().anyMatch(diagnostic ->
                diagnostic.message().contains("daylight-saving gap")));
        assertTrue(autumnOverlap.diagnostics().stream().anyMatch(diagnostic ->
                diagnostic.message().contains("daylight-saving overlap")));
        assertTrue(nonTransition.diagnostics().stream().noneMatch(diagnostic ->
                diagnostic.message().contains("daylight-saving")));
    }

    @Test
    void reportsNegativeValuesAndRowLengthDifferences() throws IOException {
        EnergyCsvImportResult result = service.parse(csv("""
                Zeitpunkt;Gesamtbezug [kWh];Effektiv aus Gemeinschaft bezogen [kWh];Restbezug [kWh]
                ;AT001;AT001;AT001
                1.6.2025, 00:00:00;-1;1
                """));

        assertTrue(result.diagnostics().stream().anyMatch(diagnostic ->
                diagnostic.message().contains("Negative interval value")));
        assertTrue(result.diagnostics().stream().anyMatch(diagnostic ->
                diagnostic.message().contains("Data row length differs")));
    }

    @Test
    void invalidCategorySequenceAndMeteringPointMismatchAreReported() throws IOException {
        EnergyCsvImportResult invalidCategory = service.parse(csv("""
                Zeitpunkt;Gesamtbezug [kWh];Restbezug [kWh];Effektiv aus Gemeinschaft bezogen [kWh]
                ;AT001;AT001;AT001
                1.6.2025, 00:00:00;1;1;0
                """));
        EnergyCsvImportResult mismatchedMeteringPoint = service.parse(csv("""
                Zeitpunkt;Gesamtbezug [kWh];Effektiv aus Gemeinschaft bezogen [kWh];Restbezug [kWh]
                ;AT001;AT999;AT001
                1.6.2025, 00:00:00;1;1;0
                """));

        assertTrue(invalidCategory.diagnostics().stream().anyMatch(diagnostic ->
                diagnostic.message().contains("Unexpected community-effective category")));
        assertTrue(mismatchedMeteringPoint.diagnostics().stream().anyMatch(diagnostic ->
                diagnostic.message().contains("Inconsistent metering point")));
    }

    @Test
    void duplicateColumnCombinationsAndNoDataRowsAreReported() throws IOException {
        EnergyCsvImportResult duplicateColumn = service.parse(csv("""
                Zeitpunkt;Gesamtbezug [kWh];Effektiv aus Gemeinschaft bezogen [kWh];Restbezug [kWh];Gesamtbezug [kWh];Effektiv aus Gemeinschaft bezogen [kWh];Restbezug [kWh]
                ;AT001;AT001;AT001;AT001;AT001;AT001
                1.6.2025, 00:00:00;1;1;0;1;1;0
                """));
        EnergyCsvImportResult noDataRows = service.parse(csv("""
                Zeitpunkt;Gesamtbezug [kWh];Effektiv aus Gemeinschaft bezogen [kWh];Restbezug [kWh]
                ;AT001;AT001;AT001
                """));

        assertTrue(duplicateColumn.diagnostics().stream().anyMatch(diagnostic ->
                diagnostic.message().contains("Duplicate category/metering-point")));
        assertTrue(noDataRows.diagnostics().stream().anyMatch(diagnostic ->
                diagnostic.message().contains("no data rows")));
    }

    private Path csv(String content) throws IOException {
        Path file = tempDir.resolve("energy.csv");
        Files.writeString(file, content);
        return file;
    }
}
