#!/bin/bash

# Nombre del archivo de salida
ZIP_NAME="smard-lightgbm-instalacion.zip"

# Obtener la ruta del directorio principal del proyecto (asumiendo que este script está en herramientas/)
PROJECT_DIR=$(dirname "$(dirname "$(readlink -f "$0")")")

cd "$PROJECT_DIR" || exit 1

echo "Preparando la estructura para el despliegue en: $ZIP_NAME"

# Eliminar el zip anterior si existe para evitar duplicados
if [ -f "$ZIP_NAME" ]; then
    rm "$ZIP_NAME"
fi

# Directorios que deben ir vacíos en la instalación limpia
mkdir -p bases_de_datos logs modelos train

# Crear directorio temporal y enlace simbólico para que la raíz en el zip se llame REJ
TMP_DIR=$(mktemp -d)
ln -s "$PROJECT_DIR" "$TMP_DIR/REJ"

cd "$TMP_DIR" || exit 1

# Generar el archivo ZIP incluyendo los archivos fuente, configuraciones y directorios estáticos
zip -r "$PROJECT_DIR/$ZIP_NAME" \
    REJ/.env.example \
    REJ/.gitignore \
    REJ/*.py \
    REJ/*.sh \
    REJ/conf/ \
    REJ/static/ \
    REJ/templates/ \
    REJ/herramientas/ \
    REJ/documentos/ \
    REJ/bases_de_datos/ \
    REJ/logs/ \
    REJ/modelos/ \
    REJ/train/ \
    -x "REJ/*.pyc" \
    -x "REJ/*__pycache__*" \
    -x "REJ/*.DS_Store" \
    -x "REJ/*.db" \
    -x "REJ/*.xlsx" \
    -x "REJ/*.log" \
    -x "REJ/modelos/*" \
    -x "REJ/train/*" \
    -x "REJ/.claude/*" \
    -x "REJ/.claude" \
    -x "REJ/$ZIP_NAME"

# Dado que hemos excluido el contenido de modelos y train, nos aseguramos de que las carpetas en sí sí entren en el zip
zip -g "$PROJECT_DIR/$ZIP_NAME" REJ/bases_de_datos/ REJ/logs/ REJ/modelos/ REJ/train/

cd "$PROJECT_DIR" || exit 1

rm -rf "$TMP_DIR"

echo "¡Listo! El archivo $ZIP_NAME se ha generado en el directorio raíz del proyecto ($PROJECT_DIR)."
