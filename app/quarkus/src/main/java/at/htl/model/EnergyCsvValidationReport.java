package at.htl.model;

import java.nio.file.Path;
import java.time.Instant;
import java.util.List;
import java.util.Set;

public record EnergyCsvValidationReport(
        List<FileSummary> files,
        long seriesCount,
        long errorCount,
        long warningCount,
        Set<String> meteringPoints,
        Set<String> categories,
        Set<DirectionType> directions,
        List<CsvValidationDiagnostic> crossFileDiagnostics
) {
    public boolean hasErrors() {
        return errorCount > 0 || crossFileDiagnostics.stream().anyMatch(CsvValidationDiagnostic::isError);
    }

    public record FileSummary(
            Path file,
            long dataRowCount,
            long seriesCount,
            long errorCount,
            long warningCount,
            Instant firstTimestamp,
            Instant lastTimestamp,
            Set<String> meteringPoints,
            Set<String> categories,
            Set<DirectionType> directions,
            List<String> structuralFingerprint,
            List<CsvValidationDiagnostic> diagnostics
    ) {
    }
}
