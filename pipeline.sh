#!/bin/bash
# pipeline.sh — Descarga, entrenamiento y predicciones en un solo comando.
#
# Uso:
#   ./pipeline.sh 2023 2024 2025          # años completos
#   ./pipeline.sh --from 2023-01-01 --to 2025-12-31   # rango libre
#   ./pipeline.sh --last-year             # últimos 365 días
#   ./pipeline.sh --recent-days 456 --val-ratio 20    # ventana móvil con early stopping

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$SCRIPT_DIR/.venv/bin/python"
TRAIN_FILE="$SCRIPT_DIR/train/germany-pipeline.train"

if [ -f "$SCRIPT_DIR/.env" ]; then
    source "$SCRIPT_DIR/.env"
fi
LIGHTGBM_CMD="${RUTA_LIGHTGBM:-$(command -v lightgbm || true)}"

log() { echo "[$(date '+%H:%M:%S')] $*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

[ -x "$PYTHON" ] || die "No se encuentra el Python del venv en $PYTHON"
[ -x "$LIGHTGBM_CMD" ] || die "No se encuentra LightGBM en $LIGHTGBM_CMD"

usage() {
    cat <<EOF
pipeline.sh — Descarga, entrenamiento y predicciones en un solo comando.

Uso:
  $0 [AÑOS...] [OPCIONES]

Ejemplos:
  $0 2023 2024 2025
  $0 --from 2023-01-01 --to 2025-12-31
  $0 --last-year
  $0 --recent-days 456 --val-ratio 20 --train-file train/germany-15-meses.train

Opciones:
  --from YYYY-MM-DD     Fecha de inicio
  --to YYYY-MM-DD       Fecha de fin
  --last-year           Usar últimos 365 días
  --recent-days N       Usar últimos N días
  --train-file FILE     Ruta del archivo .train a generar
  --val-ratio N         Porcentaje de datos para validación y early stopping (ej. 20)
  -h, --help            Mostrar esta ayuda
EOF
    exit 0
}

if [[ $# -eq 0 ]]; then
    usage
fi

# --- Parsear argumentos ---
YEARS=()
DATE_FROM=""
DATE_TO=""
LAST_YEAR=false
RECENT_DAYS=""
VAL_RATIO=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --from)   DATE_FROM="$2"; shift 2 ;;
        --to)     DATE_TO="$2";   shift 2 ;;
        --last-year) LAST_YEAR=true; shift ;;
        --recent-days) RECENT_DAYS="$2"; shift 2 ;;
        --train-file) TRAIN_FILE="$2"; shift 2 ;;
        --val-ratio) VAL_RATIO="$2"; shift 2 ;;
        -h|--help) usage ;;
        [0-9][0-9][0-9][0-9]) YEARS+=("$1"); shift ;;
        *) echo "ERROR: Argumento desconocido: $1" >&2; usage ;;
    esac
done

# --- Paso 1: Descarga ---
log "=== PASO 1: Descarga de datos ==="

if [ -n "$RECENT_DAYS" ]; then
    log "Modo --recent-days $RECENT_DAYS"
    "$PYTHON" "$SCRIPT_DIR/adquirir_datos.py" --recent-days "$RECENT_DAYS"
    CONSTRUIR_ARGS="--recent-days $RECENT_DAYS"

elif $LAST_YEAR; then
    log "Modo --last-year"
    "$PYTHON" "$SCRIPT_DIR/adquirir_datos.py" --recent-days 365
    CONSTRUIR_ARGS="--last-year"

elif [ ${#YEARS[@]} -gt 0 ]; then
    for YEAR in "${YEARS[@]}"; do
        log "Descargando año $YEAR..."
        "$PYTHON" "$SCRIPT_DIR/adquirir_datos.py" --year "$YEAR"
    done
    DATE_FROM="${YEARS[0]}-01-01"
    DATE_TO="${YEARS[-1]}-12-31"
    CONSTRUIR_ARGS="-f $DATE_FROM -t $DATE_TO"

elif [ -n "$DATE_FROM" ] && [ -n "$DATE_TO" ]; then
    log "Descargando rango $DATE_FROM → $DATE_TO"
    "$PYTHON" "$SCRIPT_DIR/adquirir_datos.py" -f "$DATE_FROM" -t "$DATE_TO"
    CONSTRUIR_ARGS="-f $DATE_FROM -t $DATE_TO"

else
    echo "ERROR: Indica años (ej: 2023 2024), --from/--to, --last-year o --recent-days" >&2
    usage
fi

# --- Paso 2: Construir dataset de entrenamiento ==="
log "=== PASO 2: Construir dataset de entrenamiento ==="
# shellcheck disable=SC2086

if [ -n "$VAL_RATIO" ]; then
    CONSTRUIR_ARGS="$CONSTRUIR_ARGS --val-ratio $VAL_RATIO"
    ACTUAL_TRAIN="${TRAIN_FILE%.train}_train.train"
    ACTUAL_VALID="${TRAIN_FILE%.train}_valid.valid"
    LGBM_ARGS="data=$ACTUAL_TRAIN valid=$ACTUAL_VALID"
else
    ACTUAL_TRAIN="$TRAIN_FILE"
    LGBM_ARGS="data=$ACTUAL_TRAIN"
fi

"$PYTHON" "$SCRIPT_DIR/construir_modelo.py" $CONSTRUIR_ARGS -o "$TRAIN_FILE"

# --- Paso 3: Entrenar LightGBM ---
log "=== PASO 3: Entrenamiento LightGBM ==="
cd "$SCRIPT_DIR"
"$LIGHTGBM_CMD" config=conf/train.conf $LGBM_ARGS
log "Modelo guardado en modelos/LightGBM_model.txt"

# --- Paso 4: Calcular predicciones pendientes ---
log "=== PASO 4: Predicciones pendientes ==="
"$PYTHON" "$SCRIPT_DIR/adquirir_datos.py" --complete

if [ -f "$ACTUAL_TRAIN" ]; then
    FILAS=$(tail -n +2 "$ACTUAL_TRAIN" | wc -l)
else
    FILAS="?"
fi

log "=== PIPELINE COMPLETADO ==="
log "  Dataset:  $ACTUAL_TRAIN ($FILAS filas de entrenamiento)"
log "  Modelo:   $SCRIPT_DIR/modelos/LightGBM_model.txt"
