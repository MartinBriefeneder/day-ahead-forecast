package at.htl.service;

import at.htl.model.CsvValidationDiagnostic;
import at.htl.model.DirectionType;
import at.htl.model.EnergyCsvImportResult;
import at.htl.model.EnergyCsvValidationReport;
import at.htl.model.EnergySeries;
import jakarta.enterprise.context.ApplicationScoped;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;

@ApplicationScoped
public class EnergyCsvValidationReportService {

    private final EnergyCsvImportService csvImportService;

    public EnergyCsvValidationReportService(EnergyCsvImportService csvImportService) {
        this.csvImportService = csvImportService;
    }

    public EnergyCsvValidationReport validate(Path input) throws IOException {
        List<Path> files = csvFiles(input);
        List<EnergyCsvValidationReport.FileSummary> summaries = files.stream()
                .map(this::validateFile)
                .toList();

        return new EnergyCsvValidationReport(
                summaries,
                summaries.stream().mapToLong(EnergyCsvValidationReport.FileSummary::seriesCount).sum(),
                summaries.stream().mapToLong(EnergyCsvValidationReport.FileSummary::errorCount).sum(),
                summaries.stream().mapToLong(EnergyCsvValidationReport.FileSummary::warningCount).sum(),
                summaries.stream().flatMap(summary -> summary.identifiers().stream()).collect(java.util.stream.Collectors.toCollection(TreeSet::new)),
                summaries.stream().flatMap(summary -> summary.directions().stream()).collect(java.util.stream.Collectors.toCollection(() -> new TreeSet<>(Comparator.comparing(Enum::name))))
        );
    }

    public void writeMarkdown(EnergyCsvValidationReport report, Path output) throws IOException {
        Path parent = output.getParent();
        if (parent != null) {
            Files.createDirectories(parent);
        }
        Files.writeString(output, toMarkdown(report));
    }

    public String toMarkdown(EnergyCsvValidationReport report) {
        StringBuilder markdown = new StringBuilder();
        markdown.append("# Energy CSV Validation Report\n\n");
        markdown.append("- Files checked: ").append(report.files().size()).append('\n');
        markdown.append("- Series parsed: ").append(report.seriesCount()).append('\n');
        markdown.append("- Errors: ").append(report.errorCount()).append('\n');
        markdown.append("- Warnings: ").append(report.warningCount()).append('\n');
        markdown.append("- Metering points: ").append(report.identifiers().size()).append('\n');
        markdown.append("- Directions: ").append(report.directions()).append("\n\n");

        markdown.append("## Metering Points\n\n");
        if (report.identifiers().isEmpty()) {
            markdown.append("No metering points found.\n\n");
        } else {
            for (String identifier : report.identifiers()) {
                markdown.append("- `").append(identifier).append("`\n");
            }
            markdown.append('\n');
        }

        markdown.append("## Files\n\n");
        for (EnergyCsvValidationReport.FileSummary file : report.files()) {
            markdown.append("### ").append(file.file().getFileName()).append("\n\n");
            markdown.append("- Path: `").append(file.file()).append("`\n");
            markdown.append("- Series parsed: ").append(file.seriesCount()).append('\n');
            markdown.append("- Errors: ").append(file.errorCount()).append('\n');
            markdown.append("- Warnings: ").append(file.warningCount()).append('\n');
            markdown.append("- First timestamp: ").append(file.firstTimestamp() == null ? "n/a" : file.firstTimestamp()).append('\n');
            markdown.append("- Last timestamp: ").append(file.lastTimestamp() == null ? "n/a" : file.lastTimestamp()).append('\n');
            markdown.append("- Metering points: ").append(file.identifiers().size()).append('\n');
            markdown.append("- Directions: ").append(file.directions()).append("\n\n");

            if (!file.diagnostics().isEmpty()) {
                markdown.append("Diagnostics:\n\n");
                for (Map.Entry<String, Long> diagnostic : groupedDiagnostics(file.diagnostics()).entrySet()) {
                    markdown.append("- ").append(diagnostic.getValue()).append("x ").append(diagnostic.getKey()).append('\n');
                }
                markdown.append('\n');
            }
        }

        return markdown.toString();
    }

    private Map<String, Long> groupedDiagnostics(List<CsvValidationDiagnostic> diagnostics) {
        Map<String, Long> grouped = new LinkedHashMap<>();
        for (CsvValidationDiagnostic diagnostic : diagnostics) {
            String key = diagnostic.severity() + ": " + diagnostic.message();
            if (diagnostic.columnName() != null) {
                key += " column=`" + diagnostic.columnName() + '`';
            }
            if (diagnostic.rawValue() != null) {
                key += " raw=`" + diagnostic.rawValue() + '`';
            }
            grouped.merge(key, 1L, Long::sum);
        }
        return grouped;
    }

    private EnergyCsvValidationReport.FileSummary validateFile(Path file) {
        try {
            EnergyCsvImportResult result = csvImportService.parse(file);
            List<EnergySeries> series = result.series();
            return new EnergyCsvValidationReport.FileSummary(
                    file,
                    series.size(),
                    result.diagnostics().stream().filter(CsvValidationDiagnostic::isError).count(),
                    result.diagnostics().stream().filter(diagnostic -> !diagnostic.isError()).count(),
                    series.stream().map(EnergySeries::timestamp).min(Instant::compareTo).orElse(null),
                    series.stream().map(EnergySeries::timestamp).max(Instant::compareTo).orElse(null),
                    series.stream().map(EnergySeries::identifier).collect(java.util.stream.Collectors.toCollection(TreeSet::new)),
                    series.stream().map(EnergySeries::energyDirection).collect(java.util.stream.Collectors.toCollection(() -> new TreeSet<>(Comparator.comparing(Enum::name)))),
                    result.diagnostics()
            );
        } catch (IOException e) {
            CsvValidationDiagnostic diagnostic = CsvValidationDiagnostic.error("Failed to read CSV file: " + e.getMessage(), null, null, null, file.toString());
            return new EnergyCsvValidationReport.FileSummary(file, 0, 1, 0, null, null, Set.of(), Set.of(), List.of(diagnostic));
        }
    }

    private List<Path> csvFiles(Path input) throws IOException {
        if (Files.isRegularFile(input)) {
            return List.of(input);
        }
        if (!Files.isDirectory(input)) {
            throw new IOException("CSV input does not exist or is not a file/directory: " + input);
        }
        try (var stream = Files.list(input)) {
            return stream
                    .filter(Files::isRegularFile)
                    .filter(path -> path.getFileName().toString().toLowerCase().endsWith(".csv"))
                    .sorted()
                    .toList();
        }
    }
}
