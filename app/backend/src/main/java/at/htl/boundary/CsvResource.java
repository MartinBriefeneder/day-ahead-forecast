package at.htl.boundary;

import at.htl.service.EnergyCsvImportService;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.Response;

import java.io.IOException;

@ApplicationScoped
@Path("/")
public class CsvResource {
    @Inject
    EnergyCsvImportService energyCsvImportService;

    @GET
    public Response getCsv() {
        try {
            return Response.status(200).entity(energyCsvImportService.parse(java.nio.file.Path.of("./src/main/resources/csv_Archiv_6_2025_bis_5_2026/RC105812_2025_6.csv"))).build();
        } catch (IOException e) {
            throw new RuntimeException(e);
        }
    }
}
