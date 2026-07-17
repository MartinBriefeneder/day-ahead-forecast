package at.htl.service;

import at.htl.model.EnergyCsvValidationReport;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class EnergyCsvValidationReportServiceTest {

    @TempDir
    Path tempDir;

    private final EnergyCsvValidationReportService service = new EnergyCsvValidationReportService(new EnergyCsvImportService());

    @Test
    void validatesDirectoryAndWritesMarkdownReport() throws Exception {
        Files.writeString(tempDir.resolve("b.csv"), validCsv("AT002"));
        Files.writeString(tempDir.resolve("a.csv"), validCsv("AT001"));
        Files.writeString(tempDir.resolve("ignored.txt"), "not a csv");

        EnergyCsvValidationReport report = service.validate(tempDir);
        Path output = tempDir.resolve("report.md");
        service.writeMarkdown(report, output);

        assertFalse(report.hasErrors());
        assertEquals(2, report.files().size());
        assertEquals(2, report.seriesCount());
        assertTrue(report.meteringPoints().contains("AT001"));
        assertTrue(report.meteringPoints().contains("AT002"));
        assertTrue(report.categories().contains("Gesamtbezug [kWh]"));

        String markdown = Files.readString(output);
        assertTrue(markdown.contains("# Energy CSV Validation Report"));
        assertTrue(markdown.contains("- Files checked: 2"));
        assertTrue(markdown.contains("- Data rows parsed: 1"));
        assertTrue(markdown.contains("## Categories"));
        assertTrue(markdown.contains("## Cross-File Validation"));
        assertTrue(markdown.contains("- First timestamp (local): 2025-06-01 00:00:00 Europe/Vienna"));
        assertTrue(markdown.contains("- First timestamp (UTC instant): 2025-05-31T22:00:00Z"));
        assertTrue(markdown.contains("### a.csv"));
        assertTrue(markdown.contains("### b.csv"));
    }

    @Test
    void reportsInvalidCsvWithoutThrowing() throws Exception {
        Files.writeString(tempDir.resolve("invalid.csv"), "Zeitpunkt\n;\n");

        EnergyCsvValidationReport report = service.validate(tempDir);

        assertTrue(report.hasErrors());
        assertEquals(2, report.errorCount());
        assertTrue(service.toMarkdown(report).contains("No importable data columns"));
        assertTrue(service.toMarkdown(report).contains("Diagnostic Details"));
    }

    @Test
    void reportsCrossFileGapsAndStructuralDifferences() throws Exception {
        Files.writeString(tempDir.resolve("a.csv"), """
                Zeitpunkt;Gesamtbezug [kWh];Effektiv aus Gemeinschaft bezogen [kWh];Restbezug [kWh]
                ;AT001;AT001;AT001
                1.6.2025, 00:00:00;1;1;0
                """);
        Files.writeString(tempDir.resolve("b.csv"), """
                Zeitpunkt;Gesamtlieferung [kWh];Effektiv an Gemeinschaft geliefert [kWh];Restlieferung [kWh]
                ;AT001;AT001;AT001
                1.6.2025, 00:30:00;1;1;0
                """);

        EnergyCsvValidationReport report = service.validate(tempDir);
        String markdown = service.toMarkdown(report);

        assertTrue(report.crossFileDiagnostics().stream().anyMatch(diagnostic ->
                diagnostic.message().contains("Cross-file date-range gap")));
        assertTrue(report.crossFileDiagnostics().stream().anyMatch(diagnostic ->
                diagnostic.message().contains("Category set differs")));
        assertTrue(markdown.contains("Cross-file date-range gap"));
    }

    private String validCsv(String meteringPoint) {
        return """
                Zeitpunkt;Gesamtbezug [kWh];Effektiv aus Gemeinschaft bezogen [kWh];Restbezug [kWh]
                ;%s;%s;%s
                1.6.2025, 00:00:00;1;1;0
                """.formatted(meteringPoint, meteringPoint, meteringPoint);
    }
}
