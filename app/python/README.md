# Forecast

## Dependencies

Create or update the local virtual environment from `requirements.txt`:

```bash
cd app/python
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Simple Benchmark Backtest

Start local services and Quarkus first, then run:

```bash
../run-forecast.sh
```

The runner has no command-line arguments. Adjust the constants at the top of `main.py` if the local backtest target or date window needs to change.

This runner evaluates energy-only benchmark models. Use `ensemble.py` for the OpenSTEF baseline/ensemble experiment.

## Local Historical Weather

This step uses only the local workbook `data/raw/Historical data Wetter(1).xlsx`. It does not call WeatherAPI or another external weather service.

Generate the weather inspection report:

```bash
cd app/python
source .venv/bin/activate
python weather_features.py inspect --output ../reports/weather-inspection-report.md
```

The command writes Markdown and JSON reports. The loader maps source columns to OpenSTEF-friendly names:

| Source column | Feature | Unit |
|---|---|---|
| `all_sky_global_horizontal_irradiance` | `shortwave_radiation` | `W/m2` |
| `2m_temperature` | `temperature_2m` | `degC` |
| `2m_relative_humidity` | `relative_humidity_2m` | `%` |
| `10m_wind_speed` | `wind_speed_10m` | `m/s` |
| `surface_pressure` | `surface_pressure` | `hPa` |

Weather use is opt-in. `fetch_forecast_dataframe()` and `fetch_forecast_dataset()` keep energy-only behavior unless `include_weather=True` is passed. Weather diagnostics are attached to `DataFrame.attrs["weather_diagnostics"]`.

Known limits:

- The workbook timestamps have no timezone offset. The local loader assumes `Europe/Vienna` and converts to UTC.
- Ambiguous and nonexistent daylight-saving timestamps are reported and excluded. They are not guessed or interpolated.
- The local weather range starts on 2025-06-11. Experiments before that date must either disable weather or handle missing weather diagnostics.

Run Python tests:

```bash
cd app/python
source .venv/bin/activate
python -m unittest discover -s tests
```
