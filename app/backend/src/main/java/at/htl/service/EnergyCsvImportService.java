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
import java.time.Duration;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.time.zone.ZoneOffsetTransition;
import java.time.zone.ZoneRules;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.HashSet;
import java.util.List;
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
            String meteringPointLine = reader.readLine();
            List<CsvValidationDiagnostic> diagnostics = new ArrayList<>();
            List<EnergySeries> series = new ArrayList<>();

            if (labelLine == null || meteringPointLine == null) {
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
            String[] meteringPoints = split(meteringPointLine);
            if (labels.length != meteringPoints.length) {
                diagnostics.add(CsvValidationDiagnostic.warning(
                        "Header row lengths differ",
                        2,
                        null,
                        null,
                        "labels=" + labels.length + ", meteringPoints=" + meteringPoints.length
                ));
            }
            if (labels.length == 0 || !"Zeitpunkt".equals(labels[0].trim())) {
                diagnostics.add(CsvValidationDiagnostic.error(
                        "First CSV column must be Zeitpunkt",
                        1,
                        labels.length == 0 ? null : labels[0].trim(),
                        null,
                        labels.length == 0 ? null : labels[0]
                ));
            }

            Set<String> categories = categories(labels);
            List<String> structuralFingerprint = structuralFingerprint(labels, meteringPoints);
            reportDuplicateColumnCombinations(labels, meteringPoints, diagnostics);

            List<ColumnGroup> groups = columnGroups(labels, meteringPoints, diagnostics);
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
            long dataRowCount = 0;

            String line;
            int rowNumber = 2;
            while ((line = reader.readLine()) != null) {
                rowNumber++;
                if (line.isBlank()) {
                    continue;
                }

                String[] columns = split(line);
                if (columns.length != labels.length) {
                    diagnostics.add(CsvValidationDiagnostic.warning(
                            "Data row length differs from header row length",
                            rowNumber,
                            null,
                            null,
                            "columns=" + columns.length + ", labels=" + labels.length
                    ));
                }
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
                dataRowCount++;

                ParseTimestampResult timestampResult = parseTimestamp(columns[0], zoneId, rowNumber, diagnostics);
                Instant timestamp = timestampResult == null ? null : timestampResult.timestamp();
                if (timestamp == null) {
                    continue;
                }
                rowTimestamps.add(new RowTimestamp(rowNumber, LocalDateTime.parse(columns[0].trim(), TIMESTAMP_FORMAT), timestamp, timestampResult.ambiguous()));
                for (ColumnGroup group : groups) {
                    if (!timestampResult.ambiguous()) {
                        recordDuplicateIfPresent(seenValues, rowNumber, timestamp, group, diagnostics);
                    }
                    series.add(new EnergySeries(
                            group.meteringPoint(),
                            timestamp,
                            group.direction(),
                            parseNumber(columns, group.totalColumn(), rowNumber, labels, timestamp, diagnostics),
                            parseNumber(columns, group.effectiveColumn(), rowNumber, labels, timestamp, diagnostics),
                            parseNumber(columns, group.residualColumn(), rowNumber, labels, timestamp, diagnostics)
                    ));
                }
            }

            if (dataRowCount == 0) {
                diagnostics.add(CsvValidationDiagnostic.error(
                        "CSV file contains no data rows",
                        null,
                        null,
                        null,
                        null
                ));
            }

            reportTimestampSequenceIssues(rowTimestamps, diagnostics);
            reportDaylightSavingAnomalies(rowTimestamps, zoneId, diagnostics);

            return new EnergyCsvImportResult(series, diagnostics, dataRowCount, categories, structuralFingerprint);
        }
    }

    private List<ColumnGroup> columnGroups(String[] labels, String[] meteringPoints, List<CsvValidationDiagnostic> diagnostics) {
        List<ColumnGroup> groups = new ArrayList<>();

        for (int column = 1; column + 2 < labels.length; column += 3) {
            String totalLabel = labels[column].trim();
            String effectiveLabel = labels[column + 1].trim();
            String residualLabel = labels[column + 2].trim();
            DirectionType direction = direction(totalLabel, diagnostics, column + 1);
            if (direction == null) {
                continue;
            }

            if (!hasExpectedCategorySequence(direction, totalLabel, effectiveLabel, residualLabel, column, diagnostics)) {
                continue;
            }

            String meteringPoint = meteringPoints.length > column ? meteringPoints[column].trim() : "";
            String effectiveMeteringPoint = meteringPoints.length > column + 1 ? meteringPoints[column + 1].trim() : "";
            String residualMeteringPoint = meteringPoints.length > column + 2 ? meteringPoints[column + 2].trim() : "";
            if (!hasConsistentMeteringPoint(meteringPoint, effectiveMeteringPoint, residualMeteringPoint, column, diagnostics)) {
                continue;
            }

            groups.add(new ColumnGroup(
                    meteringPoint,
                    direction,
                    column,
                    column + 1,
                    column + 2
            ));
        }

        return groups;
    }

    private boolean hasExpectedCategorySequence(DirectionType direction, String totalLabel, String effectiveLabel, String residualLabel, int zeroBasedColumn, List<CsvValidationDiagnostic> diagnostics) {
        String expectedTotal;
        String expectedEffective;
        String expectedResidual;
        if (direction == DirectionType.DELIVERY) {
            expectedTotal = "Gesamtlieferung [kWh]";
            expectedEffective = "Effektiv an Gemeinschaft geliefert [kWh]";
            expectedResidual = "Restlieferung [kWh]";
        } else {
            expectedTotal = "Gesamtbezug [kWh]";
            expectedEffective = "Effektiv aus Gemeinschaft bezogen [kWh]";
            expectedResidual = "Restbezug [kWh]";
        }

        boolean valid = true;
        if (!expectedTotal.equals(totalLabel)) {
            diagnostics.add(categorySequenceError("Unexpected total category", zeroBasedColumn + 1, expectedTotal, totalLabel));
            valid = false;
        }
        if (!expectedEffective.equals(effectiveLabel)) {
            diagnostics.add(categorySequenceError("Unexpected community-effective category", zeroBasedColumn + 2, expectedEffective, effectiveLabel));
            valid = false;
        }
        if (!expectedResidual.equals(residualLabel)) {
            diagnostics.add(categorySequenceError("Unexpected residual category", zeroBasedColumn + 3, expectedResidual, residualLabel));
            valid = false;
        }
        return valid;
    }

    private CsvValidationDiagnostic categorySequenceError(String message, int columnNumber, String expected, String actual) {
        return CsvValidationDiagnostic.error(
                message + ": expected `" + expected + "`",
                1,
                "column " + columnNumber,
                null,
                actual
        );
    }

    private boolean hasConsistentMeteringPoint(String totalMeteringPoint, String effectiveMeteringPoint, String residualMeteringPoint, int zeroBasedColumn, List<CsvValidationDiagnostic> diagnostics) {
        boolean valid = true;
        if (totalMeteringPoint.isBlank()) {
            diagnostics.add(missingMeteringPointError(zeroBasedColumn + 1, totalMeteringPoint));
            valid = false;
        }
        if (effectiveMeteringPoint.isBlank()) {
            diagnostics.add(missingMeteringPointError(zeroBasedColumn + 2, effectiveMeteringPoint));
            valid = false;
        }
        if (residualMeteringPoint.isBlank()) {
            diagnostics.add(missingMeteringPointError(zeroBasedColumn + 3, residualMeteringPoint));
            valid = false;
        }
        if (valid && (!totalMeteringPoint.equals(effectiveMeteringPoint) || !totalMeteringPoint.equals(residualMeteringPoint))) {
            diagnostics.add(CsvValidationDiagnostic.error(
                    "Inconsistent metering point identifiers within energy group",
                    2,
                    "columns " + (zeroBasedColumn + 1) + "-" + (zeroBasedColumn + 3),
                    null,
                    totalMeteringPoint + ", " + effectiveMeteringPoint + ", " + residualMeteringPoint
            ));
            return false;
        }
        return valid;
    }

    private CsvValidationDiagnostic missingMeteringPointError(int columnNumber, String rawValue) {
        return CsvValidationDiagnostic.error(
                "Missing metering point identifier",
                2,
                "column " + columnNumber,
                null,
                rawValue
        );
    }

    private Set<String> categories(String[] labels) {
        Set<String> categories = new java.util.TreeSet<>();
        for (int column = 1; column < labels.length; column++) {
            String label = labels[column].trim();
            if (!label.isBlank()) {
                categories.add(label);
            }
        }
        return categories;
    }

    private List<String> structuralFingerprint(String[] labels, String[] meteringPoints) {
        List<String> fingerprint = new ArrayList<>();
        for (int column = 1; column < labels.length; column++) {
            String meteringPoint = meteringPoints.length > column ? meteringPoints[column].trim() : "";
            fingerprint.add(labels[column].trim() + "|" + meteringPoint);
        }
        return fingerprint;
    }

    private void reportDuplicateColumnCombinations(String[] labels, String[] meteringPoints, List<CsvValidationDiagnostic> diagnostics) {
        Set<String> seen = new HashSet<>();
        for (int column = 1; column < labels.length; column++) {
            String category = labels[column].trim();
            String meteringPoint = meteringPoints.length > column ? meteringPoints[column].trim() : "";
            if (category.isBlank() || meteringPoint.isBlank()) {
                continue;
            }
            String key = category + "|" + meteringPoint;
            if (!seen.add(key)) {
                diagnostics.add(CsvValidationDiagnostic.warning(
                        "Duplicate category/metering-point column combination",
                        1,
                        "column " + (column + 1),
                        null,
                        category + " / " + meteringPoint
                ));
            }
        }
    }

    private DirectionType direction(String label, List<CsvValidationDiagnostic> diagnostics, int columnNumber) {
        if (isDeliveryLabel(label)) {
            return DirectionType.DELIVERY;
        }
        if (isConsumptionLabel(label)) {
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

    private boolean isDeliveryLabel(String label) {
        return "Gesamtlieferung [kWh]".equals(label)
                || "Effektiv an Gemeinschaft geliefert [kWh]".equals(label)
                || "Restlieferung [kWh]".equals(label);
    }

    private boolean isConsumptionLabel(String label) {
        return "Gesamtbezug [kWh]".equals(label)
                || "Effektiv aus Gemeinschaft bezogen [kWh]".equals(label)
                || "Restbezug [kWh]".equals(label);
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
            double parsed = Double.parseDouble(columns[column].trim().replace(',', '.'));
            if (parsed < 0) {
                diagnostics.add(CsvValidationDiagnostic.warning(
                        "Negative interval value",
                        rowNumber,
                        columnName,
                        timestamp,
                        columns[column]
                ));
            }
            return parsed;
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
        String key = timestamp + "|" + group.meteringPoint() + "|" + group.direction() + "|" + group.totalColumn();
        if (!seenValues.add(key)) {
            diagnostics.add(CsvValidationDiagnostic.error(
                    "Duplicate timestamp and data column value",
                    rowNumber,
                    group.meteringPoint(),
                    timestamp,
                    null
            ));
        }
    }

    private void reportTimestampSequenceIssues(List<RowTimestamp> rowTimestamps, List<CsvValidationDiagnostic> diagnostics) {
        for (int index = 1; index < rowTimestamps.size(); index++) {
            RowTimestamp previous = rowTimestamps.get(index - 1);
            RowTimestamp current = rowTimestamps.get(index);
            Duration interval = Duration.between(previous.localDateTime(), current.localDateTime());

            if (interval.isNegative() || interval.isZero()) {
                if (current.ambiguous()) {
                    diagnostics.add(CsvValidationDiagnostic.warning(
                            "Timestamp ordering deviation occurs during a daylight-saving overlap",
                            current.rowNumber(),
                            "Zeitpunkt",
                            current.timestamp(),
                            current.localDateTime().toString()
                    ));
                    continue;
                }
                diagnostics.add(CsvValidationDiagnostic.error(
                        "Timestamp ordering deviation",
                        current.rowNumber(),
                        "Zeitpunkt",
                        current.timestamp(),
                        current.localDateTime().toString()
                ));
                continue;
            }

            if (interval.toMinutes() > 15 && interval.toMinutes() % 15 == 0) {
                diagnostics.add(CsvValidationDiagnostic.warning(
                        "Missing quarter-hour interval(s)",
                        current.rowNumber(),
                        "Zeitpunkt",
                        current.timestamp(),
                        "previous=" + previous.localDateTime() + ", current=" + current.localDateTime()
                ));
            }
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
            String meteringPoint,
            DirectionType direction,
            int totalColumn,
            int effectiveColumn,
            int residualColumn
    ) {
    }

    private record RowTimestamp(int rowNumber, LocalDateTime localDateTime, Instant timestamp, boolean ambiguous) {
    }

    private record ParseTimestampResult(Instant timestamp, boolean ambiguous) {
    }
}
