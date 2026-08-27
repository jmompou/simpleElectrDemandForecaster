#!/bin/bash

# Obtener la ruta del directorio principal del proyecto
PROJECT_DIR=$(dirname "$(dirname "$(readlink -f "$0")")")

echo "========================================================="
echo "   DESINSTALACIÓN DE TAREAS EN SEGUNDO PLANO (CRON)      "
echo "========================================================="

# Listar el crontab actual
if crontab -l &>/dev/null; then
    # Hacer una copia de seguridad temporal
    crontab -l > /tmp/crontab_backup.txt
    
    # Filtrar las tareas de este proyecto (las que contienen la ruta base)
    crontab -l | grep -v "$PROJECT_DIR" > /tmp/crontab_filtered.txt
    
    # Comprobar si el archivo filtrado tiene contenido real (ignorando líneas vacías)
    if [ -s /tmp/crontab_filtered.txt ] && [ "$(grep -v "^#" /tmp/crontab_filtered.txt | wc -w)" -gt 0 ]; then
        # Hay otras tareas activas, instalar el crontab filtrado
        crontab /tmp/crontab_filtered.txt
        echo "Las tareas automáticas asociadas a $PROJECT_DIR han sido eliminadas."
        echo "Tus otras tareas del crontab se han conservado intactas."
    else
        # El crontab quedó vacío (o solo contenía las tareas de este proyecto)
        crontab -r
        echo "Las tareas automáticas asociadas a $PROJECT_DIR han sido eliminadas."
        echo "El crontab ha quedado completamente vacío."
    fi
    
    # Limpiar archivos temporales
    rm -f /tmp/crontab_backup.txt /tmp/crontab_filtered.txt
else
    echo "No hay tareas programadas (crontab) en el sistema para este usuario."
fi

echo "========================================================="
echo "Toda la actividad en segundo plano (adquisición automática"
echo "de datos y re-entrenamiento) ha sido detenida."
echo "========================================================="
