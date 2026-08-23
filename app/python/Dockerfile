FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FORECAST_SKIP_VENV=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY python/requirements.txt /app/python/requirements.txt
RUN pip install -r /app/python/requirements.txt

COPY python /app/python
COPY run-all-forecasts.sh /app/run-all-forecasts.sh

RUN mkdir -p /app/reports/forecast-runs

ENTRYPOINT ["/app/run-all-forecasts.sh"]
