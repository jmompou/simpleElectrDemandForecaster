#!/bin/bash

# Comprobar si se ha pasado el archivo como argumento
if [ -z "$1" ]; then
  echo "Error: Debes proporcionar el fichero .train como argumento."
  echo "Uso: ./entrenar.sh <fichero.train> [fichero.valid]"
  exit 1
fi

# Cargar variables de entorno si existe .env
if [ -f "$(dirname "$0")/.env" ]; then
  source "$(dirname "$0")/.env"
fi
# Si no está configurado, buscar LightGBM en PATH.
LIGHTGBM_CMD=${RUTA_LIGHTGBM:-$(command -v lightgbm || true)}

if [ -z "$LIGHTGBM_CMD" ]; then
  echo "Error: No se encuentra el ejecutable lightgbm. Configura RUTA_LIGHTGBM en .env."
  exit 1
fi

# Ejecutar el entrenamiento usando el binario de LightGBM sobrescribiendo el parámetro 'data' y 'valid' si existe
if [ -n "$2" ]; then
  "$LIGHTGBM_CMD" config=conf/train.conf data="$1" valid="$2"
else
  "$LIGHTGBM_CMD" config=conf/train.conf data="$1"
fi
