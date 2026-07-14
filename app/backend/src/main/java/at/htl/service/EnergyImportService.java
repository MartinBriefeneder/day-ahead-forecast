package at.htl.service;

import at.htl.model.EnergySeries;
import at.htl.repository.EnergySeriesRepository;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;

import java.nio.file.Path;
import java.util.List;

@ApplicationScoped
public class EnergyImportService {

    @Inject
    EnergyCsvImportService csvImportService;

    @Inject
    EnergySeriesRepository influxDbEnergySeriesRepository;

    public int importCsv(Path csvFile) throws Exception {
        List<EnergySeries> series = csvImportService.parse(csvFile);
        influxDbEnergySeriesRepository.saveAll(series);
        return series.size();
    }
}
