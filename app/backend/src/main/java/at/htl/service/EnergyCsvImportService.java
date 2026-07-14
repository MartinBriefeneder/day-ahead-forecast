package at.htl.service;

import at.htl.model.CsvValidationDiagnostic;
import at.htl.model.DirectionType;
import at.htl.model.EnergyCsvImportResult;
import at.htl.model.EnergySeries;
import jakarta.enterprise.context.ApplicationScoped;

import java.io.BufferedReader;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.time.zone.ZoneOffsetTransition;
import java.time.zone.ZoneRules;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

@ApplicationScoped
public class EnergyCsvImportService {

    private static final DateTimeFormatter TIMESTAMP_FORMAT = DateTimeFormatter.ofPattern("d.M.yyyy, HH:mm:ss");
    private static final ZoneId DEFAULT_ZONE = ZoneId.of("Europe/Vienna");

    public EnergyCsvImportResult parse(Path csvFile) throws IOException {
        return parse(csvFile, DEFAULT_ZONE);
    }

    public EnergyCsvImportResult parse(Path csvFile, ZoneId zoneId) throws IOException {
        try (BufferedReader reader = Files.newBufferedReader(csvFile, StandardCharsets.UTF_8)) {
            String labelLine = reader.readLine();
            String identifierLine = reader.readLine();
            List<CsvValidationDiagnostic> diagnostics = new ArrayList<>();
            List<EnergySeries> series = new ArrayList<>();

            if (labelLine == null || identifierLine == null) {
                diagnostics.add(CsvValidationDiagnostic.error(
                        "CSV must contain two header rows: labels and identifiers",
                        null,
                        null,
                        null,
                        null
                ));
                return new EnergyCsvImportResult(series, diagnostics);
            }

            String[] labels = split(labelLine);
            String[] identifiers = split(identifierLine);
            if (labels.length == 0 || !"Zeitpunkt".equals(labels[0].trim())) {
                diagnostics.add(CsvValidationDiagnostic.error(
                        "First CSV column must be Zeitpunkt",
                        1,
                        labels.length == 0 ? null : labels[0].trim(),
                        null,
                        labels.length == 0 ? null : labels[0]
                ));
            }

            List<ColumnGroup> groups = columnGroups(labels, identifiers, diagnostics);
            if (groups.isEmpty()) {
                diagnostics.add(CsvValidationDiagnostic.error(
                        "No importable data columns were found",
                        1,
                        null,
                        null,
                        labelLine
                ));
            }

            Set<String> seenValues = new HashSet<>();
            List<RowTimestamp> rowTimestamps = new ArrayList<>();

            String line;
            int rowNumber = 2;
            while ((line = reader.readLine()) != null) {
                rowNumber++;
                if (line.isBlank()) {
                    continue;
                }

                String[] columns = split(line);
                if (columns.length == 0 || columns[0].isBlank()) {
                    diagnostics.add(CsvValidationDiagnostic.error(
                            "Missing timestamp value",
                            rowNumber,
                            "Zeitpunkt",
                            null,
                            columns.length == 0 ? null : columns[0]
                    ));
                    continue;
                }

                ParseTimestampResult timestampResult = parseTimestamp(columns[0], zoneId, rowNumber, diagnostics);
                Instant timestamp = timestampResult == null ? null : timestampResult.timestamp();
                if (timestamp == null) {
                    continue;
                }
                rowTimestamps.add(new RowTimestamp(rowNumber, LocalDateTime.parse(columns[0].trim(), TIMESTAMP_FORMAT), timestamp));
                for (ColumnGroup group : groups) {
                    if (!timestampResult.ambiguous()) {
                        recordDuplicateIfPresent(seenValues, rowNumber, timestamp, group, diagnostics);
                    }
                    series.add(new EnergySeries(
                            group.identifier(),
                            timestamp,
                            group.direction(),
                            parseNumber(columns, group.totalColumn(), rowNumber, labels, timestamp, diagnostics),
                            parseNumber(columns, group.effectiveColumn(), rowNumber, labels, timestamp, diagnostics),
                            parseNumber(columns, group.residualColumn(), rowNumber, labels, timestamp, diagnostics)
                    ));
                }
            }

            reportDaylightSavingAnomalies(rowTimestamps, zoneId, diagnostics);

            return new EnergyCsvImportResult(series, diagnostics);
        }
    }

    private List<ColumnGroup> columnGroups(String[] labels, String[] identifiers, List<CsvValidationDiagnostic> diagnostics) {
        List<ColumnGroup> groups = new ArrayList<>();

        for (int column = 1; column + 2 < labels.length; column += 3) {
            String identifier = identifiers.length > column ? identifiers[column].trim() : "";
            if (identifier.isBlank()) {
                continue;
            }

            DirectionType direction = direction(labels[column], diagnostics, column + 1);
            if (direction == null) {
                continue;
            }

            groups.add(new ColumnGroup(
                    identifier,
                    direction,
                    column,
                    column + 1,
                    column + 2
            ));
        }

        return groups;
    }

    private DirectionType direction(String label, List<CsvValidationDiagnostic> diagnostics, int columnNumber) {
        String normalized = label.toLowerCase(Locale.ROOT);
        if (normalized.contains("lieferung")) {
            return DirectionType.DELIVERY;
        }
        if (normalized.contains("bezug")) {
            return DirectionType.CONSUMPTION;
        }
        diagnostics.add(CsvValidationDiagnostic.error(
                "Cannot determine energy direction from header",
                1,
                "column " + columnNumber,
                null,
                label
        ));
        return null;
    }

    private ParseTimestampResult parseTimestamp(String value, ZoneId zoneId, int rowNumber, List<CsvValidationDiagnostic> diagnostics) {
        LocalDateTime localDateTime;
        try {
            localDateTime = LocalDateTime.parse(value.trim(), TIMESTAMP_FORMAT);
        } catch (DateTimeParseException e) {
            diagnostics.add(CsvValidationDiagnostic.error(
                    "Invalid timestamp value",
                    rowNumber,
                    "Zeitpunkt",
                    null,
                    value
            ));
            return null;
        }

        if (localDateTime.getMinute() % 15 != 0 || localDateTime.getSecond() != 0 || localDateTime.getNano() != 0) {
            diagnostics.add(CsvValidationDiagnostic.error(
                    "Timestamp is not aligned to a quarter-hour interval",
                    rowNumber,
                    "Zeitpunkt",
                    null,
                    value
            ));
        }

        ZoneRules rules = zoneId.getRules();
        List<ZoneOffset> offsets = rules.getValidOffsets(localDateTime);
        boolean ambiguous = false;
        if (offsets.isEmpty()) {
            diagnostics.add(CsvValidationDiagnostic.warning(
                    "Timestamp falls into a daylight-saving gap",
                    rowNumber,
                    "Zeitpunkt",
                    null,
                    value
            ));
        } else if (offsets.size() > 1) {
            ambiguous = true;
            diagnostics.add(CsvValidationDiagnostic.warning(
                    "Timestamp is ambiguous because of a daylight-saving overlap",
                    rowNumber,
                    "Zeitpunkt",
                    null,
                    value
            ));
        }

        return new ParseTimestampResult(localDateTime.atZone(zoneId).toInstant(), ambiguous);
    }

    private double parseNumber(String[] columns, int column, int rowNumber, String[] labels, Instant timestamp, List<CsvValidationDiagnostic> diagnostics) {
        String columnName = column < labels.length ? labels[column] : "column " + (column + 1);
        if (column >= columns.length || columns[column].isBlank()) {
            diagnostics.add(CsvValidationDiagnostic.warning(
                    "Missing interval value",
                    rowNumber,
                    columnName,
                    timestamp,
                    column >= columns.length ? null : columns[column]
            ));
            return 0;
        }
        try {
            return Double.parseDouble(columns[column].trim().replace(',', '.'));
        } catch (NumberFormatException e) {
            diagnostics.add(CsvValidationDiagnostic.error(
                    "Invalid numeric interval value",
                    rowNumber,
                    columnName,
                    timestamp,
                    columns[column]
            ));
            return 0;
        }
    }

    private void recordDuplicateIfPresent(Set<String> seenValues, int rowNumber, Instant timestamp, ColumnGroup group, List<CsvValidationDiagnostic> diagnostics) {
        String key = timestamp + "|" + group.identifier() + "|" + group.direction() + "|" + group.totalColumn();
        if (!seenValues.add(key)) {
            diagnostics.add(CsvValidationDiagnostic.error(
                    "Duplicate timestamp and data column value",
                    rowNumber,
                    group.identifier(),
                    timestamp,
                    null
            ));
        }
    }

    private void reportDaylightSavingAnomalies(List<RowTimestamp> rowTimestamps, ZoneId zoneId, List<CsvValidationDiagnostic> diagnostics) {
        if (rowTimestamps.isEmpty()) {
            return;
        }

        Set<LocalDate> dates = new HashSet<>();
        for (RowTimestamp rowTimestamp : rowTimestamps) {
            dates.add(rowTimestamp.localDateTime().toLocalDate());
        }

        for (LocalDate date : dates) {
            ZoneOffsetTransition transition = zoneId.getRules().nextTransition(date.atStartOfDay(zoneId).toInstant().minusSeconds(1));
            if (transition != null && transition.getDateTimeBefore().toLocalDate().equals(date)) {
                diagnostics.add(CsvValidationDiagnostic.warning(
                        "CSV contains rows on a daylight-saving transition date; verify missing, repeated, or ambiguous quarter-hour timestamps",
                        null,
                        "Zeitpunkt",
                        null,
                        date.toString()
                ));
            }
        }
    }

    private String[] split(String line) {
        return line.split(";", -1);
    }

    private record ColumnGroup(
            String identifier,
            DirectionType direction,
            int totalColumn,
            int effectiveColumn,
            int residualColumn
    ) {
    }

    private record RowTimestamp(int rowNumber, LocalDateTime localDateTime, Instant timestamp) {
    }

    private record ParseTimestampResult(Instant timestamp, boolean ambiguous) {
    }
}
