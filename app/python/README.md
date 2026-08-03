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
