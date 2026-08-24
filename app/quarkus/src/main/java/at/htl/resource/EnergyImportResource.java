package at.htl.resource;

import at.htl.model.EnergyImportStatus;
import at.htl.service.EnergyImportService;
import jakarta.inject.Inject;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;

@Path("/api/energy-import")
@Produces(MediaType.APPLICATION_JSON)
public class EnergyImportResource {

    @Inject
    EnergyImportService energyImportService;

    @GET
    @Path("/status")
    public EnergyImportStatus getStatus() throws Exception {
        return new EnergyImportStatus(energyImportService.hasImportedData());
    }
}
