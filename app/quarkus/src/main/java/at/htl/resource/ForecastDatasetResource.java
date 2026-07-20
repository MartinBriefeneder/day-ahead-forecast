package at.htl.resource;

import at.htl.model.ForecastDatasetResponse;
import at.htl.service.ForecastDatasetService;
import jakarta.inject.Inject;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.WebApplicationException;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;

@Path("/api/forecast-datasets")
@Produces(MediaType.APPLICATION_JSON)
public class ForecastDatasetResource {

    @Inject
    ForecastDatasetService forecastDatasetService;

    @GET
    public ForecastDatasetResponse getDataset(@QueryParam("target") String target,
                                              @QueryParam("from") String from,
                                              @QueryParam("to") String to) throws Exception {
        try {
            return forecastDatasetService.getDataset(target, from, to);
        } catch (IllegalArgumentException exception) {
            throw new WebApplicationException(exception.getMessage(), Response.Status.BAD_REQUEST);
        }
    }
}
