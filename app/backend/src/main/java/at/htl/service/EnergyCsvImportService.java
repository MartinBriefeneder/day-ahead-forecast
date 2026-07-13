package at.htl.service;

import at.htl.model.DirectionType;
import at.htl.model.EnergySeries;
import jakarta.enterprise.context.ApplicationScoped;

import java.io.BufferedReader;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

@ApplicationScoped
public class EnergyCsvImportService {

    private static final DateTimeFormatter TIMESTAMP_FORMAT = DateTimeFormatter.ofPattern("d.M.yyyy, HH:mm:ss");
    private static final ZoneId DEFAULT_ZONE = ZoneId.of("Europe/Vienna");

    public List<EnergySeries> parse(Path csvFile) throws IOException {
        return parse(csvFile, DEFAULT_ZONE);
    }

    public List<EnergySeries> parse(Path csvFile, ZoneId zoneId) throws IOException {
        try (BufferedReader reader = Files.newBufferedReader(csvFile, StandardCharsets.UTF_8)) {
            String labelLine = reader.readLine();
            String identifierLine = reader.readLine();

            if (labelLine == null || identifierLine == null) {
                throw new IllegalArgumentException("CSV malformed. CSV must contain two header rows: labels and identifiers");
            }

            List<ColumnGroup> groups = columnGroups(split(labelLine), split(identifierLine));
            List<EnergySeries> series = new ArrayList<>();

            String line;
            while ((line = reader.readLine()) != null) {
                if (line.isBlank()) {
                    continue;
                }

                String[] columns = split(line);
                if (columns.length == 0 || columns[0].isBlank()) {
                    continue;
                }

                Instant timestamp = parseTimestamp(columns[0], zoneId);
                for (ColumnGroup group : groups) {
                    series.add(new EnergySeries(
                            group.identifier(),
                            timestamp,
                            group.direction(),
                            parseNumber(columns, group.totalColumn()),
                            parseNumber(columns, group.effectiveColumn()),
                            parseNumber(columns, group.residualColumn())
                    ));
                }
            }

            return series;
        }
    }

    private List<ColumnGroup> columnGroups(String[] labels, String[] identifiers) {
        List<ColumnGroup> groups = new ArrayList<>();

        for (int column = 1; column + 2 < labels.length; column += 3) {
            String identifier = identifiers.length > column ? identifiers[column].trim() : "";
            if (identifier.isBlank()) {
                continue;
            }

            groups.add(new ColumnGroup(
                    identifier,
                    direction(labels[column]),
                    column,
                    column + 1,
                    column + 2
            ));
        }

        return groups;
    }

    private DirectionType direction(String label) {
        String normalized = label.toLowerCase(Locale.ROOT);
        if (normalized.contains("lieferung")) {
            return DirectionType.DELIVERY;
        }
        if (normalized.contains("bezug")) {
            return DirectionType.CONSUMPTION;
        }
        throw new IllegalArgumentException("Cannot determine energy direction from header: " + label);
    }

    private Instant parseTimestamp(String value, ZoneId zoneId) {
        return LocalDateTime.parse(value.trim(), TIMESTAMP_FORMAT).atZone(zoneId).toInstant();
    }

    private double parseNumber(String[] columns, int column) {
        if (column >= columns.length || columns[column].isBlank()) {
            return 0;
        }
        return Double.parseDouble(columns[column].trim().replace(',', '.'));
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
}
