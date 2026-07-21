# load dataset 
from datetime import datetime, timedelta

from forecast_dataset_api import load_forecast_dataset

dataset = load_forecast_dataset()

train_start = datetime.fromisoformat("2025-06-01T00:00:00Z")
train_end = train_start + timedelta(days=105)
forecast_end = train_end + timedelta(days=7)

train_dataset = dataset.filter_by_range(start=train_start, end=train_end)

# Include 14 days of history before forecast start for lag feature computation
predict_dataset = dataset.filter_by_range(
    start=train_end - timedelta(days=14),
    end=forecast_end,
)

if train_dataset.data.empty:
    raise ValueError("Training dataset is empty. Check that InfluxDB contains data for the selected training range.")
if predict_dataset.data.empty:
    raise ValueError("Prediction dataset is empty. Check that InfluxDB contains data for the selected prediction range.")

print(
    f"Training:  {train_dataset.data.shape[0]:,} rows, "
    f"{train_dataset.data.index.min():%Y-%m-%d} to {train_dataset.data.index.max():%Y-%m-%d}"
)
print(
    f"Predict:   {predict_dataset.data.shape[0]:,} rows, "
    f"{predict_dataset.data.index.min():%Y-%m-%d} to {predict_dataset.data.index.max():%Y-%m-%d}"
)

# configure the workflow

from openstef_core.types import LeadTime, Q
from openstef_models.presets import ForecastingWorkflowConfig, create_forecasting_workflow

workflow = create_forecasting_workflow(
    config=ForecastingWorkflowConfig(
        model_id="quickstart_gblinear",
        model="gblinear",
        horizons=[LeadTime.from_string("PT36H")],
        quantiles=[Q(0.5), Q(0.2), Q(0.6)],
        target_column="load",
        temperature_column="temperature_2m",
        relative_humidity_column="relative_humidity_2m",
        wind_speed_column="wind_speed_10m",
        radiation_column="shortwave_radiation",
        pressure_column="surface_pressure",
        verbosity=0,
        mlflow_storage=None,
        sample_interval=timedelta(minutes=15),
    )
)
# train the model
result = workflow.fit(train_dataset)

if result is not None:
    print("Training metrics:")
    print(result.metrics_full.to_dataframe())

    if result.metrics_test is not None:
        print("\nTest-set metrics:")
        print(result.metrics_test.to_dataframe())
# generate forecast
from openstef_core.datasets import ForecastDataset

forecast: ForecastDataset = workflow.predict(predict_dataset, forecast_start=train_end)

print(f"Forecast rows: {len(forecast.data)}")
print(f"Quantiles:     {forecast.quantiles}")
forecast.data.tail()

from openstef_beam.analysis.plots import ForecastTimeSeriesPlotter

fig = (
    ForecastTimeSeriesPlotter()
    .add_measurements(measurements=predict_dataset.data["load"].loc[train_end:])
    .add_model(
        model_name="gblinear",
        forecast=forecast.median_series,
        quantiles=forecast.quantiles_data,
    )
    .plot()
)
fig.update_layout(
    title="Forecast vs actuals",
    yaxis_title="Load (MW)",
    xaxis_title="Time",
    height=500,
)
fig.show()
