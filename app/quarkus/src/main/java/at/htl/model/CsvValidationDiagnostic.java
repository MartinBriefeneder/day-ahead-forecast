package at.htl.model;

import java.time.Instant;

public record CsvValidationDiagnostic(
        Severity severity,
        String message,
        Integer rowNumber,
        String columnName,
        Instant timestamp,
        String rawValue
) {
    public enum Severity {
        WARNING,
        ERROR
    }

    public static CsvValidationDiagnostic warning(String message, Integer rowNumber, String columnName, Instant timestamp, String rawValue) {
        return new CsvValidationDiagnostic(Severity.WARNING, message, rowNumber, columnName, timestamp, rawValue);
    }

    public static CsvValidationDiagnostic error(String message, Integer rowNumber, String columnName, Instant timestamp, String rawValue) {
        return new CsvValidationDiagnostic(Severity.ERROR, message, rowNumber, columnName, timestamp, rawValue);
    }

    public boolean isError() {
        return severity == Severity.ERROR;
    }
}
