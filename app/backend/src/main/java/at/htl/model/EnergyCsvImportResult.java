package at.htl.model;

import java.util.List;
import java.util.Set;

public record EnergyCsvImportResult(
        List<EnergySeries> series,
        List<CsvValidationDiagnostic> diagnostics,
        long dataRowCount,
        Set<String> categories,
        List<String> structuralFingerprint
) {
    public EnergyCsvImportResult(List<EnergySeries> series, List<CsvValidationDiagnostic> diagnostics) {
        this(series, diagnostics, 0, Set.of(), List.of());
    }

    public boolean hasErrors() {
        return diagnostics.stream().anyMatch(CsvValidationDiagnostic::isError);
    }
}
