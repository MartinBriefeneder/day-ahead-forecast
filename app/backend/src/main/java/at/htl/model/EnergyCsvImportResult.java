package at.htl.model;

import java.util.List;

public record EnergyCsvImportResult(
        List<EnergySeries> series,
        List<CsvValidationDiagnostic> diagnostics
) {
    public boolean hasErrors() {
        return diagnostics.stream().anyMatch(CsvValidationDiagnostic::isError);
    }
}
