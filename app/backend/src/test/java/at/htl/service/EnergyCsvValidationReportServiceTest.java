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
        assertTrue(report.identifiers().contains("AT001"));
        assertTrue(report.identifiers().contains("AT002"));

        String markdown = Files.readString(output);
        assertTrue(markdown.contains("# Energy CSV Validation Report"));
        assertTrue(markdown.contains("- Files checked: 2"));
        assertTrue(markdown.contains("### a.csv"));
        assertTrue(markdown.contains("### b.csv"));
    }

    @Test
    void reportsInvalidCsvWithoutThrowing() throws Exception {
        Files.writeString(tempDir.resolve("invalid.csv"), "Zeitpunkt\n;\n");

        EnergyCsvValidationReport report = service.validate(tempDir);

        assertTrue(report.hasErrors());
        assertEquals(1, report.errorCount());
        assertTrue(service.toMarkdown(report).contains("No importable data columns"));
    }

    private String validCsv(String identifier) {
        return """
                Zeitpunkt;Bezug total;Bezug community;Bezug residual
                ;%s;%s;%s
                1.6.2025, 00:00:00;1;1;0
                """.formatted(identifier, identifier, identifier);
    }
}
