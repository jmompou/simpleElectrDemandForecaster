#!/bin/bash

# Script de prueba para realizar predicciones con LightGBM usando predict.conf
# Cargar variables de entorno si existe .env
if [ -f "$(dirname "$0")/.env" ]; then
  source "$(dirname "$0")/.env"
fi
# Si RUTA_LIGHTGBM no está definida, usar valor por defecto
LIGHTGBM_CMD=${RUTA_LIGHTGBM:-$(command -v lightgbm || true)}

if [ -z "$LIGHTGBM_CMD" ]; then
  echo "Error: No se encuentra el ejecutable lightgbm. Configura RUTA_LIGHTGBM en .env."
  exit 1
fi

# Ejecuta el binario usando la configuración predict.conf
$LIGHTGBM_CMD config=conf/predict.conf

echo "Predicción terminada. Los resultados se han guardado en LightGBM_predict_result.txt"
