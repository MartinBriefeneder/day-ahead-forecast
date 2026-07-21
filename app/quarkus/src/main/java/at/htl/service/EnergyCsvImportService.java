package at.htl.service;

import at.htl.model.CsvValidationDiagnostic;
import at.htl.model.DirectionType;
import at.htl.model.EnergyCategory;
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
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.time.ZonedDateTime;
import java.time.zone.ZoneRules;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
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

            java.util.Map<LocalDateTime, List<RowTimestamp>> timestampRows = new java.util.LinkedHashMap<>();
            java.util.Map<LocalDateTime, Integer> ambiguousTimestampOccurrences = new java.util.HashMap<>();
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

                ParseTimestampResult timestampResult = parseTimestamp(columns[0], zoneId, rowNumber, ambiguousTimestampOccurrences, diagnostics);
                Instant timestamp = timestampResult == null ? null : timestampResult.timestamp();
                if (timestamp == null) {
                    continue;
                }
                LocalDateTime localDateTime = timestampResult.localDateTime();
                RowTimestamp rowTimestamp = new RowTimestamp(rowNumber, localDateTime, timestamp, timestampResult.ambiguous());
                rowTimestamps.add(rowTimestamp);
                timestampRows.computeIfAbsent(localDateTime, ignored -> new ArrayList<>()).add(rowTimestamp);
                for (ColumnGroup group : groups) {
                    addValue(series, group, timestamp, EnergyCategory.TOTAL,
                            parseNumber(columns, group.totalColumn(), rowNumber, labels, timestamp, diagnostics));
                    addValue(series, group, timestamp, EnergyCategory.COMMUNITY_EFFECTIVE,
                            parseNumber(columns, group.effectiveColumn(), rowNumber, labels, timestamp, diagnostics));
                    addValue(series, group, timestamp, EnergyCategory.RESIDUAL,
                            parseNumber(columns, group.residualColumn(), rowNumber, labels, timestamp, diagnostics));
                }
            }

            reportDuplicateTimestamps(timestampRows, diagnostics);

            if (dataRowCount == 0) {
                diagnostics.add(CsvValidationDiagnostic.error(
                        "CSV file contains no data rows",
                        null,
                        null,
                        null,
                        null
                ));
            }

            reportTimestampSequenceIssues(rowTimestamps, zoneId, diagnostics);
            return new EnergyCsvImportResult(series, diagnostics, dataRowCount, categories, structuralFingerprint);
        }
    }

    private void addValue(List<EnergySeries> series, ColumnGroup group, Instant timestamp, EnergyCategory category, double valueKwh) {
        series.add(new EnergySeries(group.meteringPoint(), timestamp, group.direction(), category, valueKwh));
    }

    private List<ColumnGroup> columnGroups(String[] labels, String[] meteringPoints, List<CsvValidationDiagnostic> diagnostics) {
        List<ColumnGroup> groups = new ArrayList<>();
        Set<String> seenColumnGroups = new HashSet<>();

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

            String columnGroupKey = meteringPoint + "|" + direction;
            if (!seenColumnGroups.add(columnGroupKey)) {
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

    private ParseTimestampResult parseTimestamp(String value, ZoneId zoneId, int rowNumber, java.util.Map<LocalDateTime, Integer> ambiguousTimestampOccurrences, List<CsvValidationDiagnostic> diagnostics) {
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
        }

        Instant timestamp;
        if (ambiguous) {
            int occurrence = ambiguousTimestampOccurrences.merge(localDateTime, 1, Integer::sum);
            ZoneOffset offset = offsets.get(Math.min(occurrence - 1, offsets.size() - 1));
            timestamp = ZonedDateTime.ofLocal(localDateTime, zoneId, offset).toInstant();
        } else {
            timestamp = localDateTime.atZone(zoneId).toInstant();
        }

        return new ParseTimestampResult(localDateTime, timestamp, ambiguous);
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

    private void reportDuplicateTimestamps(java.util.Map<LocalDateTime, List<RowTimestamp>> timestampRows, List<CsvValidationDiagnostic> diagnostics) {
        for (java.util.Map.Entry<LocalDateTime, List<RowTimestamp>> entry : timestampRows.entrySet()) {
            List<RowTimestamp> rows = entry.getValue();
            if (rows.size() > 1) {
                boolean daylightSavingOverlapDuplicate = rows.size() == 2 && rows.stream().allMatch(RowTimestamp::ambiguous);
                if (daylightSavingOverlapDuplicate) {
                    continue;
                }
                List<Integer> rowNumbers = rows.stream().map(RowTimestamp::rowNumber).toList();
                for (RowTimestamp row : rows) {
                    diagnostics.add(CsvValidationDiagnostic.error(
                            "Duplicate timestamp in CSV file",
                            row.rowNumber(),
                            "Zeitpunkt",
                            null,
                            "timestamp=" + entry.getKey() + ", rows=" + rowNumbers
                    ));
                }
            }
        }
    }

    private void reportTimestampSequenceIssues(List<RowTimestamp> rowTimestamps, ZoneId zoneId, List<CsvValidationDiagnostic> diagnostics) {
        for (int index = 1; index < rowTimestamps.size(); index++) {
            RowTimestamp previous = rowTimestamps.get(index - 1);
            RowTimestamp current = rowTimestamps.get(index);
            Duration interval = Duration.between(previous.localDateTime(), current.localDateTime());

            if (interval.isNegative() || interval.isZero()) {
                if (current.ambiguous()) {
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
                LocalDateTime firstMissing = previous.localDateTime().plusMinutes(15);
                LocalDateTime lastMissing = current.localDateTime().minusMinutes(15);
                if (isDaylightSavingGap(firstMissing, lastMissing, zoneId)) {
                    continue;
                }
                diagnostics.add(CsvValidationDiagnostic.warning(
                        "Missing quarter-hour interval(s)",
                        current.rowNumber(),
                        "Zeitpunkt",
                        current.timestamp(),
                        "previous=" + previous.localDateTime() + ", current=" + current.localDateTime()
                                + ", missing=" + (firstMissing.equals(lastMissing) ? firstMissing : firstMissing + ".." + lastMissing)
                ));
            }
        }
    }

    private boolean isDaylightSavingGap(LocalDateTime firstMissing, LocalDateTime lastMissing, ZoneId zoneId) {
        ZoneRules rules = zoneId.getRules();
        for (LocalDateTime timestamp = firstMissing; !timestamp.isAfter(lastMissing); timestamp = timestamp.plusMinutes(15)) {
            if (!rules.getValidOffsets(timestamp).isEmpty()) {
                return false;
            }
        }
        return true;
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

    private record ParseTimestampResult(LocalDateTime localDateTime, Instant timestamp, boolean ambiguous) {
    }
}
