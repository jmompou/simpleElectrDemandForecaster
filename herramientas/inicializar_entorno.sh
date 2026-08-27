#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

# Asegurar que la estructura del proyecto es válida.
if [ ! -f "$PROJECT_DIR/adquirir_datos.py" ] || [ ! -d "$PROJECT_DIR/herramientas" ]; then
    echo "========================================================="
    echo " ERROR: RUTA DE EJECUCIÓN INCORRECTA"
    echo "========================================================="
    echo "Parece que estás intentando ejecutar este script desde un"
    echo "directorio equivocado (actualmente estás en: $(pwd))."
    echo ""
    echo "Para que las rutas relativas funcionen correctamente,"
    echo "DEBES posicionarte en la carpeta raíz del proyecto."
    echo ""
    echo "Pasos a seguir:"
    echo "  1. Navega a la raíz del proyecto."
    echo "  2. Vuelve a lanzar el script:      ./herramientas/inicializar_entorno.sh"
    echo "========================================================="
    exit 1
fi

echo "========================================================="
echo "   INICIALIZACIÓN DEL ENTORNO DE PREDICCIÓN DE ENERGÍA   "
echo "========================================================="

echo "[0/5] Guardando ruta base en .env..."
RUTA_BASE=$(pwd)
if [ -z "${RUTA_LIGHTGBM:-}" ]; then
    RUTA_LIGHTGBM="$(command -v lightgbm || true)"
fi
echo "RUTA_BASE=${RUTA_BASE}" > .env
echo "RUTA_LIGHTGBM=${RUTA_LIGHTGBM}" >> .env
echo "  -> RUTA_BASE guardada como: ${RUTA_BASE}"

# Comprobar disponibilidad de LightGBM
echo ""
echo "[0.5/5] Comprobando disponibilidad del binario LightGBM..."
if [ -z "$RUTA_LIGHTGBM" ] || [ ! -x "$RUTA_LIGHTGBM" ]; then
    echo "========================================================="
    echo " ERROR: BINARIO DE LIGHTGBM NO ENCONTRADO"
    echo "========================================================="
    echo "El motor de inferencia y entrenamiento requiere el binario"
    echo "compilado de LightGBM (CLI), disponible en PATH o configurado en .env."
    echo ""
    echo "Pasos para instalarlo en esta máquina:"
    echo "  1. Consulta la documentación de LightGBM para instalar su CLI."
    echo "  2. Añade su ruta a RUTA_LIGHTGBM en .env, si no está en PATH."
    echo ""
    echo "Una vez finalizada la compilación, vuelve a la carpeta"
    echo "del proyecto y ejecuta de nuevo este instalador."
    echo "========================================================="
    exit 1
fi
echo "  -> Binario encontrado en $RUTA_LIGHTGBM"

# 1. Regenerar el entorno virtual
echo ""
echo "[1/5] Regenerando el entorno virtual (.venv)..."
if [ -d ".venv" ]; then
    echo "  -> Eliminando el entorno virtual antiguo..."
    rm -rf .venv
fi

echo "  -> Creando nuevo entorno virtual..."
python3 -m venv .venv
source .venv/bin/activate

echo "  -> Instalando dependencias (pandas, numpy, lightgbm, requests, holidays, python-dotenv, pytz, flask, dateutil)..."
pip install --upgrade pip > /dev/null 2>&1
pip install pandas numpy lightgbm requests holidays python-dotenv pytz flask python-dateutil > /dev/null 2>&1
echo "  -> Dependencias instaladas correctamente."

# 2. Comprobar base de datos
echo ""
echo "[2/5] Comprobando la base de datos..."
if [ -f "bases_de_datos/demanda_energia.db" ]; then
    echo "  -> Se ha detectado una base de datos preexistente (procedente del ZIP)."
    echo "  -> Se conservarán los datos históricos (desde 2023)."
else
    echo "  -> No existía base de datos, se creará una nueva."
fi

# 3. Descargar/Actualizar datos de demanda y meteorología
echo ""
echo "[3/5] Actualizando datos faltantes o descargando el último año..."
echo "  -> El script omitirá automáticamente las semanas que ya estén completas en la BD."
./.venv/bin/python adquirir_datos.py --recent-days 365

# 4. Entrenar el modelo
echo ""
echo "[4/5] Extrayendo datos de entrenamiento y entrenando el modelo..."
mkdir -p train logs modelos

# Reparar índices categóricos en los archivos conf por si el ZIP contiene versiones antiguas
echo "  -> Verificando configuración de LightGBM..."
sed -i 's/categorical_feature = 7,8/categorical_feature = 6,7/g' conf/*.conf 2>/dev/null || true

echo "  -> Generando archivo de entrenamiento y validación (20%)..."
./.venv/bin/python construir_modelo.py --last-year -o train/inicial.train --val-ratio 20

echo "  -> Entrenando modelo LightGBM con validación (early stopping)..."
./entrenar.sh train/inicial_train.train train/inicial_valid.valid
echo "  -> Entrenamiento completado. Modelo guardado en modelos/LightGBM_model.txt"

# 5. Configurar el cron
echo ""
echo "[5/5] Configurando tareas en segundo plano (Cron)..."
if [ -f "conf/crontab.txt" ]; then
    echo "  -> Sustituyendo rutas relativas en conf/crontab.txt por ${RUTA_BASE}..."
    # Reemplazamos la marca {{RUTA_BASE}} por la ruta real usando sed y lo guardamos en un archivo temporal
    sed "s|{{RUTA_BASE}}|${RUTA_BASE}|g" conf/crontab.txt > conf/crontab_generado.txt
    
    echo "  -> Instalando crontab desde conf/crontab_generado.txt..."
    crontab conf/crontab_generado.txt
    echo "  -> Tareas de cron instaladas."
    
    # Limpieza
    rm conf/crontab_generado.txt
else
    echo "  -> Aviso: No se encontró conf/crontab.txt para configurar cron."
fi

echo ""
echo "========================================================="
echo "   INICIALIZACIÓN COMPLETADA CON ÉXITO                   "
echo "========================================================="
echo "El entorno está listo. Puedes iniciar el servidor web con:"
echo "  ./.venv/bin/python panel_control.py"
echo ""
