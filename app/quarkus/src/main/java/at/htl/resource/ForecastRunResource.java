package at.htl.resource;

import at.htl.model.ForecastComparisonResponse;
import at.htl.model.ForecastRunRequest;
import at.htl.model.ForecastRunSaveResponse;
import at.htl.service.ForecastRunService;
import jakarta.inject.Inject;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.DefaultValue;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.WebApplicationException;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;

@Path("/api/forecast-runs")
@Consumes(MediaType.APPLICATION_JSON)
@Produces(MediaType.APPLICATION_JSON)
public class ForecastRunResource {

    @Inject
    ForecastRunService forecastRunService;

    @POST
    public ForecastRunSaveResponse save(ForecastRunRequest request) throws Exception {
        try {
            return forecastRunService.save(request);
        } catch (IllegalArgumentException exception) {
            throw new WebApplicationException(exception.getMessage(), Response.Status.BAD_REQUEST);
        }
    }

    @GET
    @Path("/{runId}/comparison")
    public ForecastComparisonResponse getComparison(@PathParam("runId") String runId,
                                                    @QueryParam("limit") @DefaultValue("10000") int limit) throws Exception {
        try {
            return forecastRunService.getComparison(runId, limit);
        } catch (IllegalArgumentException exception) {
            throw new WebApplicationException(exception.getMessage(), Response.Status.BAD_REQUEST);
        }
    }
}
