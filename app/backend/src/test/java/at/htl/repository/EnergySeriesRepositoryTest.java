package at.htl.repository;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class EnergySeriesRepositoryTest {

    @Test
    void resolvesConfiguredWriteBatchSize() {
        EnergySeriesRepository repository = new EnergySeriesRepository();

        repository.writeBatchSize = 25_000;

        assertEquals(25_000, repository.resolvedWriteBatchSize());
    }

    @Test
    void fallsBackToDefaultWriteBatchSizeWhenConfiguredValueIsInvalid() {
        EnergySeriesRepository repository = new EnergySeriesRepository();

        repository.writeBatchSize = 0;

        assertEquals(10_000, repository.resolvedWriteBatchSize());
    }
}
