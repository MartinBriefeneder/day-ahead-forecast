package at.htl.service;

import io.quarkus.runtime.Quarkus;
import io.quarkus.runtime.StartupEvent;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.enterprise.event.Observes;
import jakarta.inject.Inject;
import org.eclipse.microprofile.config.inject.ConfigProperty;
import org.jboss.logging.Logger;

import java.nio.file.Path;
import java.util.Optional;

@ApplicationScoped
public class EnergyImportCommandRunner {

    @Inject
    EnergyImportService energyImportService;
    @Inject
    Logger logger;

    @ConfigProperty(name = "energy.import.command.file")
    Optional<String> importFile;

    void importCsv(@Observes StartupEvent event) {
        if (importFile.isEmpty()) {
            return;
        }

        try {
            Path csvFile = Path.of(importFile.get());
            int imported = energyImportService.importCsv(csvFile);
            logger.info("Imported " + imported + " energy points from " + csvFile);
            Quarkus.asyncExit(0);
        } catch (Exception e) {
            throw new IllegalStateException("Failed to import energy CSV: " + importFile.get(), e);
        }
    }
}
