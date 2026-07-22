# Fetch dataset
from datetime import datetime, timedelta

from forecast_dataset_api import fetch_forecast_dataset

train_start = datetime.fromisoformat("2025-06-01T00:00:00Z")
forecast_target = "consumption"
target_label = {
    "consumption": "Consumption",
    "generation": "Generation",
}[forecast_target]
train_days = 200
forecast_days = 7
train_end = train_start + timedelta(days=train_days)
forecast_end = train_end + timedelta(days=forecast_days)


def format_utc(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


dataset = fetch_forecast_dataset(
    target=forecast_target,
    start=format_utc(train_start),
    end=format_utc(forecast_end),
)

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


quantiles=[Q(0.5), Q(0.1), Q(0.6)] 

config=ForecastingWorkflowConfig(
    model_id="quickstart_gblinear",
    quantiles=quantiles,
    model="xgboost",
    horizons=[LeadTime.from_string("PT36H")],
    target_column=forecast_target,
    temperature_column="temperature_2m",
    relative_humidity_column="relative_humidity_2m",
    wind_speed_column="wind_speed_10m",
    radiation_column="shortwave_radiation",
    pressure_column="surface_pressure",
    verbosity=0,
    mlflow_storage=None,
    sample_interval=timedelta(minutes=15),
)

workflow = create_forecasting_workflow(
        config
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
    .add_measurements(measurements=predict_dataset.data[forecast_target].loc[train_end:])
    .add_model(
        model_name=f"{target_label} forecast (xgboost)",
        forecast=forecast.median_series,
        quantiles=forecast.quantiles_data,
    )
    .plot()
)
fig.update_layout(
    title=f"OpenSTEF {target_label} Forecast vs Actuals ({forecast_target})",
    yaxis_title=f"{target_label} energy (kWh)",
    xaxis_title="Time",
    height=500,
)
fig.show()

#Measure calibration quality https://openstef.github.io/openstef/tutorials/quantile_calibration.html

from pandas import DataFrame

actuals = predict_dataset.data[forecast_target].loc[train_end:].reindex(forecast.data.index).dropna()
forecast_aligned = forecast.data.loc[actuals.index]

expected = [float(q) for q in quantiles]
observed_uncal = [float((actuals <= forecast_aligned[f"quantile_P{int(float(q) * 100)}"]).mean()) for q in quantiles]

calibration_df = DataFrame(
    {
        "quantile": [f"P{int(float(q) * 100)}" for q in quantiles],
        "expected": expected,
        "observed": observed_uncal,
        "error": [o - e for o, e in zip(observed_uncal, expected, strict=True)],
    }
)
print("Calibration before isotonic correction:")
print(calibration_df.to_string(index=False))


from openstef_models.transforms.postprocessing import IsotonicQuantileCalibrator

config_cal = config.model_copy(update={"model_id": "calibrated_gblinear"})
workflow_cal = create_forecasting_workflow(config=config_cal)

# Append isotonic calibration to the existing postprocessing pipeline
workflow_cal.model.postprocessing.transforms.append(
    IsotonicQuantileCalibrator(
        quantiles=quantiles,
        use_local_quantile_estimation=True,
    )
)

workflow_cal.fit(train_dataset)
forecast_cal = workflow_cal.predict(predict_dataset, forecast_start=train_end)

forecast_cal_aligned = forecast_cal.data.loc[actuals.index]

observed_cal = [float((actuals <= forecast_cal_aligned[f"quantile_P{int(float(q) * 100)}"]).mean()) for q in quantiles]

comparison_df = DataFrame(
    {
        "quantile": [f"P{int(float(q) * 100)}" for q in quantiles],
        "expected": expected,
        "observed (before)": observed_uncal,
        "observed (after)": observed_cal,
        "error (before)": [o - e for o, e in zip(observed_uncal, expected, strict=True)],
        "error (after)": [o - e for o, e in zip(observed_cal, expected, strict=True)],
    }
)
print(comparison_df.to_string(index=False))
