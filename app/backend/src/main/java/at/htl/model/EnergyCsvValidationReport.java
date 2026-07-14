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
        Set<String> identifiers,
        Set<DirectionType> directions
) {
    public boolean hasErrors() {
        return errorCount > 0;
    }

    public record FileSummary(
            Path file,
            long seriesCount,
            long errorCount,
            long warningCount,
            Instant firstTimestamp,
            Instant lastTimestamp,
            Set<String> identifiers,
            Set<DirectionType> directions,
            List<CsvValidationDiagnostic> diagnostics
    ) {
    }
}
