package at.htl.service;

import at.htl.model.CsvValidationDiagnostic;
import at.htl.model.EnergyCsvImportResult;
import at.htl.model.EnergySeries;
import at.htl.repository.EnergySeriesRepository;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import org.jboss.logging.Logger;

import java.nio.file.Path;
import java.time.Duration;
import java.util.List;

@ApplicationScoped
public class EnergyImportService {

    @Inject
    EnergyCsvImportService csvImportService;

    @Inject
    EnergySeriesRepository energySeriesRepository;

    @Inject
    Logger logger;

    public int importCsv(Path csvFile) throws Exception {
        long started = System.nanoTime();
        EnergyCsvImportResult result = csvImportService.parse(csvFile);
        Duration parseDuration = Duration.ofNanos(System.nanoTime() - started);
        logDiagnostics(result.diagnostics());

        if (result.hasErrors()) {
            throw new IllegalArgumentException("CSV validation failed with " + result.diagnostics().stream().filter(CsvValidationDiagnostic::isError).count() + " error(s)");
        }

        List<EnergySeries> series = result.series();
        long writeStarted = System.nanoTime();
        energySeriesRepository.saveAll(series);
        Duration writeDuration = Duration.ofNanos(System.nanoTime() - writeStarted);
        Duration totalDuration = Duration.ofNanos(System.nanoTime() - started);
        logger.info("Imported " + series.size()
                + " energy points from " + csvFile.getFileName()
                + " in " + formatDuration(totalDuration)
                + " (parse=" + formatDuration(parseDuration)
                + ", write=" + formatDuration(writeDuration) + ")");
        return series.size();
    }

    private String formatDuration(Duration duration) {
        return duration.toMillis() + " ms";
    }

    private void logDiagnostics(List<CsvValidationDiagnostic> diagnostics) {
        for (CsvValidationDiagnostic diagnostic : diagnostics) {
            String message = formatDiagnostic(diagnostic);
            if (diagnostic.severity() == CsvValidationDiagnostic.Severity.ERROR) {
                logger.error(message);
            } else {
                logger.warn(message);
            }
        }
    }

    private String formatDiagnostic(CsvValidationDiagnostic diagnostic) {
        StringBuilder message = new StringBuilder("CSV validation ")
                .append(diagnostic.severity())
                .append(": ")
                .append(diagnostic.message());

        if (diagnostic.rowNumber() != null) {
            message.append(" row=").append(diagnostic.rowNumber());
        }
        if (diagnostic.columnName() != null) {
            message.append(" column=").append(diagnostic.columnName());
        }
        if (diagnostic.timestamp() != null) {
            message.append(" timestamp=").append(diagnostic.timestamp());
        }
        if (diagnostic.rawValue() != null) {
            message.append(" rawValue=").append(diagnostic.rawValue());
        }

        return message.toString();
    }
}
