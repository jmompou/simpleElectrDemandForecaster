# Short-Term Electricity Demand Forecasting Using Low-Cost Signals and Gradient Boosting

Hourly electricity demand forecasting system for the German power market based on LightGBM and publicly accessible, open-data sources (SMARD, Open-Meteo/ERA5, and national holidays). The project implements an automated pipeline for continuous data ingestion, weekly model retraining, multi-step autoregressive inference (1 to 168 hours), and an operational control dashboard.

## Overview

The goal of this system is to evaluate the predictive accuracy and operational feasibility of Short-Term Load Forecasting (STLF) models trained strictly on open and free data streams, removing any dependency on private telemetry, grid balance contracts, or paid market metrics.

Key pipeline capabilities:
* Automated hourly ingestion and retries from public APIs.
* Data cleaning, quality checks, deduplication, and seasonal anomaly filtering via unbiased MAD.
* Tabular feature engineering (autoregressive lags, cyclical encodings, and geographically distributed urban temperatures).
* Scheduled retraining with early stopping over a 24-month chronological window.
* Recursive multi-step autoregressive inference from 1 to 168 hours ahead.
* Interactive Flask web dashboard for real-time monitoring and forward projections.

## Feature Set and Data Sources

The model processes 18 input features derived from three open-access sources:

1. Electricity demand: SMARD public API (Bundesnetzagentur). Indicator 410 (actual consumption) and Indicator 411 (official TSO day-ahead forecast).
2. Meteorology: Open-Meteo Archive API (ERA5 reanalysis) and Forecast API. 2-meter air temperature across the 10 most populated German cities: Berlin, Hamburg, Munich, Cologne, Frankfurt, Stuttgart, Dusseldorf, Leipzig, Dortmund, and Essen.
3. Calendar and public holidays: Python holidays package for nationwide German federal holidays (Bundesfeiertage).

Model features:
* demanda_t_1: Real power demand at t - 1 h (immediate inertia).
* demanda_t_24h: Real power demand at t - 24 h (daily pattern).
* hora_sin, hora_cos: Cyclical trigonometric encoding of the hour of the day (period 24).
* dia_ano_sin, dia_ano_cos: Cyclical trigonometric encoding of the day of the year (period 365/366).
* dia_semana: Categorical weekday index (1 to 7).
* es_festivo: Binary national holiday indicator (0 or 1).
* temp_berlin to temp_essen: 10 hourly temperature features by city.

## Pipeline Architecture

The system runs on Linux managed by crontab scheduling:

* Layer 1. Ingestion: hourly retrieval at minutes 10 and 40 (`adquirir_datos.py`), daily reconsolidation at 1:00 AM for retrospective upstream revisions, and deep weekly self-healing sweeps for missing records.
* Layer 2. Autonomous Retraining: weekly cron execution on Sundays at 3:00 AM (`pipeline.sh`). It queries a 730-day (24-month) rolling window from the local SQLite database, applies a strict 50/50 chronological split (12 months train / 12 months validation to eliminate seasonal bias), and trains the ensemble via LightGBM C++ binary with early stopping.
* Layer 3. Real-Time Deployment: multi-horizon forward forecast generator (`predecir_futuro.py`) and Flask web server (`panel_control.py`) rendering actual load curves, model forecasts, and projected trajectories.

## Results and Performance

Metrics evaluated in a live operational setting over the prospective validation window (July 4 to July 12, 2026, 208 hourly timestamps):

* One-step evaluation (h = 1, nowcasting): MAE of 717.13 MW, RMSE of 997.86 MW, MAPE of 1.50% (n = 195).
* Day-ahead evaluation (h = 24, recursive autoregression): MAE of 1733.44 MW, RMSE of 2268.53 MW, MAPE of 3.45% (n = 175).
* Official SMARD benchmark forecast (day-ahead): MAE of 1893.08 MW, RMSE of 2382.23 MW, MAPE of 4.03% (on the 175 shared timestamps; 4.06% over all 208 timestamps).
* Daily seasonal naive (lag-24h): MAE of 4174.31 MW, MAPE of 8.66%.

Error progression across recursive forecast horizons:
* h = 1 h: MAPE 1.50% (MAE 717.1 MW, n = 195)
* h = 6 h: MAPE 2.83% (MAE 1386.6 MW, n = 191)
* h = 12 h: MAPE 3.00% (MAE 1479.1 MW, n = 185)
* h = 24 h: MAPE 3.45% (MAE 1733.4 MW, n = 175)
* h = 48 h: MAPE 4.34% (MAE 2196.3 MW, n = 152)
* h = 72 h: MAPE 4.10% (MAE 2030.7 MW, n = 135)
* h = 168 h: MAPE 5.31% (MAE 2274.1 MW, n = 41)

Error growth is sub-linear: deterioration is concentrated between h = 1 and h = 24, reaching a plateau around 4.1-4.3% between 24 and 72 hours due to the anchoring effect of exogenous weather and calendar signals.

Feature importance (relative gain):
* demanda_t_1: 76.43%
* demanda_t_24h: 11.13%
* hora_cos: 3.73%
* dia_semana: 3.71%
* hora_sin: 3.08%
* dia_ano_cos: 1.05%
* Remaining features (temperatures, es_festivo, dia_ano_sin): 0.87%

## Repository Structure

* adquirir_datos.py: Hourly data ingestion and self-healing from SMARD and Open-Meteo into SQLite.
* construir_modelo.py: Feature extraction and dataset construction for train/valid splits.
* predecir_futuro.py: Multi-horizon recursive autoregressive inference engine.
* predecir_tramo.py: Simulation utility for tracking autoregressive drift across custom slices.
* panel_control.py: Flask web server and dashboard logic.
* pipeline.sh: Shell orchestrator for the weekly automated retraining cycle.
* entrenar.sh: Standalone script for LightGBM C++ training invocation.
* conf/train.conf: LightGBM training hyperparameter configuration.
* conf/crontab.txt: Crontab scheduled job definitions.
* herramientas/prueba_sobreajuste.py: Diagnostics tool for loss curves and overfitting detection.
* herramientas/exportar_excel.py: Export utility from SQLite to Excel spreadsheets.

## Requirements and Setup

Main dependencies:
* Python 3.10 or higher
* lightgbm (CLI binary or library)
* sqlite3
* pandas
* requests
* holidays
* Flask

Manual pipeline execution example:

```bash
# Ingest and update recent data
python3 adquirir_datos.py

# Build dataset with chronological split (50% train / 50% valid over 730 days)
python3 construir_modelo.py -recent-days 730 -val-ratio 50 -output train/germany-24-meses

# Train model using LightGBM CLI
lightgbm config=conf/train.conf data=train/germany-24-meses_train.train valid=train/germany-24-meses_valid.valid output_model=modelos/LightGBM_model.txt

# Run recursive inference for 24 hours ahead
python3 predecir_futuro.py -horizon 24

# Launch Flask monitoring dashboard
python3 panel_control.py
