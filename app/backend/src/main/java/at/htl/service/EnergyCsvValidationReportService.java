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
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;

@ApplicationScoped
public class EnergyCsvValidationReportService {

    private static final ZoneId REPORT_ZONE = ZoneId.of("Europe/Vienna");
    private static final DateTimeFormatter REPORT_TIMESTAMP_FORMAT = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss VV");

    private final EnergyCsvImportService csvImportService;

    public EnergyCsvValidationReportService(EnergyCsvImportService csvImportService) {
        this.csvImportService = csvImportService;
    }

    public EnergyCsvValidationReport validate(Path input) throws IOException {
        List<Path> files = csvFiles(input);
        List<EnergyCsvValidationReport.FileSummary> summaries = files.stream()
                .map(this::validateFile)
                .toList();
        List<CsvValidationDiagnostic> crossFileDiagnostics = crossFileDiagnostics(summaries);

        return new EnergyCsvValidationReport(
                summaries,
                summaries.stream().mapToLong(EnergyCsvValidationReport.FileSummary::seriesCount).sum(),
                summaries.stream().mapToLong(EnergyCsvValidationReport.FileSummary::errorCount).sum()
                        + crossFileDiagnostics.stream().filter(CsvValidationDiagnostic::isError).count(),
                summaries.stream().mapToLong(EnergyCsvValidationReport.FileSummary::warningCount).sum()
                        + crossFileDiagnostics.stream().filter(diagnostic -> !diagnostic.isError()).count(),
                summaries.stream().flatMap(summary -> summary.meteringPoints().stream()).collect(java.util.stream.Collectors.toCollection(TreeSet::new)),
                summaries.stream().flatMap(summary -> summary.categories().stream()).collect(java.util.stream.Collectors.toCollection(TreeSet::new)),
                summaries.stream().flatMap(summary -> summary.directions().stream()).collect(java.util.stream.Collectors.toCollection(() -> new TreeSet<>(Comparator.comparing(Enum::name)))),
                crossFileDiagnostics
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
        markdown.append("- Metering points: ").append(report.meteringPoints().size()).append('\n');
        markdown.append("- Categories: ").append(report.categories().size()).append('\n');
        markdown.append("- Directions: ").append(report.directions()).append("\n\n");

        markdown.append("## Categories\n\n");
        if (report.categories().isEmpty()) {
            markdown.append("No categories found.\n\n");
        } else {
            for (String category : report.categories()) {
                markdown.append("- `").append(category).append("`\n");
            }
            markdown.append('\n');
        }

        markdown.append("## Metering Points\n\n");
        if (report.meteringPoints().isEmpty()) {
            markdown.append("No metering points found.\n\n");
        } else {
            for (String meteringPoint : report.meteringPoints()) {
                markdown.append("- `").append(meteringPoint).append("`\n");
            }
            markdown.append('\n');
        }

        markdown.append("## Cross-File Validation\n\n");
        if (report.crossFileDiagnostics().isEmpty()) {
            markdown.append("- No cross-file date-range or structural issues detected.\n\n");
        } else {
            for (Map.Entry<String, Long> diagnostic : groupedDiagnostics(report.crossFileDiagnostics()).entrySet()) {
                markdown.append("- ").append(diagnostic.getValue()).append("x ").append(diagnostic.getKey()).append('\n');
            }
            markdown.append('\n');
        }

        markdown.append("## Files\n\n");
        for (EnergyCsvValidationReport.FileSummary file : report.files()) {
            markdown.append("### ").append(file.file().getFileName()).append("\n\n");
            markdown.append("- Path: `").append(file.file()).append("`\n");
            markdown.append("- Data rows parsed: ").append(file.dataRowCount()).append('\n');
            markdown.append("- Series parsed: ").append(file.seriesCount()).append('\n');
            markdown.append("- Errors: ").append(file.errorCount()).append('\n');
            markdown.append("- Warnings: ").append(file.warningCount()).append('\n');
            markdown.append("- First timestamp (local): ").append(formatLocalTimestamp(file.firstTimestamp())).append('\n');
            markdown.append("- First timestamp (UTC instant): ").append(formatInstant(file.firstTimestamp())).append('\n');
            markdown.append("- Last timestamp (local): ").append(formatLocalTimestamp(file.lastTimestamp())).append('\n');
            markdown.append("- Last timestamp (UTC instant): ").append(formatInstant(file.lastTimestamp())).append('\n');
            markdown.append("- Metering points: ").append(file.meteringPoints().size()).append('\n');
            markdown.append("- Categories: ").append(file.categories()).append('\n');
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

    private List<CsvValidationDiagnostic> crossFileDiagnostics(List<EnergyCsvValidationReport.FileSummary> summaries) {
        List<CsvValidationDiagnostic> diagnostics = new ArrayList<>();
        List<EnergyCsvValidationReport.FileSummary> ordered = summaries.stream()
                .filter(summary -> summary.firstTimestamp() != null && summary.lastTimestamp() != null)
                .sorted(Comparator.comparing(EnergyCsvValidationReport.FileSummary::firstTimestamp))
                .toList();

        for (int index = 1; index < ordered.size(); index++) {
            EnergyCsvValidationReport.FileSummary previous = ordered.get(index - 1);
            EnergyCsvValidationReport.FileSummary current = ordered.get(index);
            Instant expectedStart = previous.lastTimestamp().plusSeconds(15 * 60);
            if (current.firstTimestamp().isAfter(expectedStart)) {
                diagnostics.add(CsvValidationDiagnostic.warning(
                        "Cross-file date-range gap",
                        null,
                        null,
                        current.firstTimestamp(),
                        previous.file().getFileName() + " -> " + current.file().getFileName() + ", expected=" + expectedStart
                ));
            } else if (current.firstTimestamp().isBefore(expectedStart)) {
                diagnostics.add(CsvValidationDiagnostic.warning(
                        "Cross-file date-range overlap",
                        null,
                        null,
                        current.firstTimestamp(),
                        previous.file().getFileName() + " -> " + current.file().getFileName() + ", expected=" + expectedStart
                ));
            }
        }

        if (!ordered.isEmpty()) {
            EnergyCsvValidationReport.FileSummary reference = ordered.getFirst();
            for (EnergyCsvValidationReport.FileSummary summary : ordered.subList(1, ordered.size())) {
                if (!summary.categories().equals(reference.categories())) {
                    diagnostics.add(CsvValidationDiagnostic.warning(
                            "Category set differs from reference file",
                            null,
                            summary.file().getFileName().toString(),
                            null,
                            "reference=" + reference.file().getFileName()
                    ));
                }
                if (!summary.structuralFingerprint().equals(reference.structuralFingerprint())) {
                    diagnostics.add(CsvValidationDiagnostic.warning(
                            "Column structure differs from reference file",
                            null,
                            summary.file().getFileName().toString(),
                            null,
                            "reference=" + reference.file().getFileName()
                    ));
                }
            }
        }
        return diagnostics;
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

    private String formatInstant(Instant timestamp) {
        return timestamp == null ? "n/a" : timestamp.toString();
    }

    private String formatLocalTimestamp(Instant timestamp) {
        return timestamp == null ? "n/a" : REPORT_TIMESTAMP_FORMAT.format(timestamp.atZone(REPORT_ZONE));
    }

    private EnergyCsvValidationReport.FileSummary validateFile(Path file) {
        try {
            EnergyCsvImportResult result = csvImportService.parse(file);
            List<EnergySeries> series = result.series();
            return new EnergyCsvValidationReport.FileSummary(
                    file,
                    result.dataRowCount(),
                    series.size(),
                    result.diagnostics().stream().filter(CsvValidationDiagnostic::isError).count(),
                    result.diagnostics().stream().filter(diagnostic -> !diagnostic.isError()).count(),
                    series.stream().map(EnergySeries::timestamp).min(Instant::compareTo).orElse(null),
                    series.stream().map(EnergySeries::timestamp).max(Instant::compareTo).orElse(null),
                    series.stream().map(EnergySeries::meteringPoint).collect(java.util.stream.Collectors.toCollection(TreeSet::new)),
                    result.categories().stream().collect(java.util.stream.Collectors.toCollection(TreeSet::new)),
                    series.stream().map(EnergySeries::direction).collect(java.util.stream.Collectors.toCollection(() -> new TreeSet<>(Comparator.comparing(Enum::name)))),
                    result.structuralFingerprint(),
                    result.diagnostics()
            );
        } catch (IOException e) {
            CsvValidationDiagnostic diagnostic = CsvValidationDiagnostic.error("Failed to read CSV file: " + e.getMessage(), null, null, null, file.toString());
            return new EnergyCsvValidationReport.FileSummary(file, 0, 0, 1, 0, null, null, Set.of(), Set.of(), Set.of(), List.of(), List.of(diagnostic));
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
