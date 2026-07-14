package at.htl.service;

import at.htl.model.DirectionType;
import at.htl.model.EnergySeries;
import at.htl.repository.EnergySeriesRepository;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;

import java.time.Instant;
import java.util.List;

@ApplicationScoped
public class EnergySeriesService {

    @Inject
    EnergySeriesRepository energySeriesRepository;

    public List<EnergySeries> find(String identifier, DirectionType direction, Instant from, Instant to, int limit) throws Exception {
        return energySeriesRepository.find(identifier, direction, from, to, limit);
    }
}
