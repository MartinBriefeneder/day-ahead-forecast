package at.htl.service;

import at.htl.model.EnergySeries;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;

import java.io.IOException;
import java.nio.file.Path;
import java.util.List;

@ApplicationScoped
public class EnergyImportService {

    @Inject
    EnergyCsvImportService csvImportService;

    @Inject
    InfluxDbWriteService influxDbWriteService;

    public int importCsv(Path csvFile) throws IOException, InterruptedException {
        List<EnergySeries> series = csvImportService.parse(csvFile);
        influxDbWriteService.write(series);
        return series.size();
    }
}
