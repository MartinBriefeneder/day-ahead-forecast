package at.htl.service;

import at.htl.model.CsvValidationDiagnostic;
import at.htl.model.EnergyCsvImportResult;
import at.htl.model.EnergySeries;
import at.htl.repository.EnergySeriesRepository;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import org.jboss.logging.Logger;

import java.nio.file.Path;
import java.util.List;

@ApplicationScoped
public class EnergyImportService {

    @Inject
    EnergyCsvImportService csvImportService;

    @Inject
    EnergySeriesRepository influxDbEnergySeriesRepository;

    @Inject
    Logger logger;

    public int importCsv(Path csvFile) throws Exception {
        EnergyCsvImportResult result = csvImportService.parse(csvFile);
        logDiagnostics(result.diagnostics());

        if (result.hasErrors()) {
            throw new IllegalArgumentException("CSV validation failed with " + result.diagnostics().stream().filter(CsvValidationDiagnostic::isError).count() + " error(s)");
        }

        List<EnergySeries> series = result.series();
        influxDbEnergySeriesRepository.saveAll(series);
        return series.size();
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
