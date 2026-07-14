package at.htl.service;

import io.quarkus.runtime.Quarkus;
import io.quarkus.runtime.StartupEvent;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.enterprise.event.Observes;
import jakarta.inject.Inject;
import org.eclipse.microprofile.config.inject.ConfigProperty;
import org.jboss.logging.Logger;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Optional;

@ApplicationScoped
public class EnergyImportCommandRunner {

    @Inject
    EnergyImportService energyImportService;
    @Inject
    EnergyCsvValidationReportService validationReportService;
    @Inject
    Logger logger;

    @ConfigProperty(name = "energy.import.command.file")
    Optional<String> importFile;

    @ConfigProperty(name = "energy.import.command.directory")
    Optional<String> importDirectory;

    @ConfigProperty(name = "energy.validation.input")
    Optional<String> validationInput;

    @ConfigProperty(name = "energy.validation.report", defaultValue = "target/energy-csv-validation-report.md")
    String validationReport;

    void importCsv(@Observes StartupEvent event) {
        if (validationInput.isPresent()) {
            validateCsv();
            return;
        }

        if (importFile.isEmpty() && importDirectory.isEmpty()) {
            return;
        }

        try {
            int imported = 0;
            List<Path> files = importFiles();
            logger.info("Importing " + files.size() + " energy CSV file(s)");
            for (int i = 0; i < files.size(); i++) {
                Path csvFile = files.get(i);
                logger.info("Importing CSV file " + (i + 1) + "/" + files.size() + ": " + csvFile);
                int importedFromFile = energyImportService.importCsv(csvFile);
                imported += importedFromFile;
                logger.info("Imported " + importedFromFile + " energy points from " + csvFile.getFileName());
            }
            logger.info("Imported " + imported + " energy points");
            Quarkus.asyncExit(0);
        } catch (Exception e) {
            throw new IllegalStateException("Failed to import energy CSV input", e);
        }
    }

    private void validateCsv() {
        try {
            Path input = Path.of(validationInput.get());
            Path reportPath = Path.of(validationReport);
            var report = validationReportService.validate(input);
            validationReportService.writeMarkdown(report, reportPath);
            logger.info("Validated " + report.files().size() + " CSV file(s), found " + report.errorCount() + " error(s) and " + report.warningCount() + " warning(s)");
            logger.info("Validation report has been generated at: " + reportPath.toAbsolutePath());
            Quarkus.asyncExit(report.hasErrors() ? 1 : 0);
        } catch (Exception e) {
            throw new IllegalStateException("Failed to validate energy CSV input: " + validationInput.get(), e);
        }
    }

    private List<Path> importFiles() throws IOException {
        if (importFile.isPresent()) {
            return List.of(Path.of(importFile.get()));
        }
        Path directory = Path.of(importDirectory.get());
        try (var stream = Files.list(directory)) {
            return stream
                    .filter(Files::isRegularFile)
                    .filter(path -> path.getFileName().toString().toLowerCase().endsWith(".csv"))
                    .sorted()
                    .toList();
        }
    }
}
