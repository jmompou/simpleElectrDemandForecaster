# prueba_sobreajuste.py

## Propósito
Herramienta automatizada para auditar y diagnosticar si el modelo actual está sufriendo de *overfitting* (sobreajuste), es decir, memorizando el entrenamiento pero perdiendo capacidad de generalizar con datos nuevos.

## Algoritmos
- **Segmentación Temporal Dinámica**: Divide un dataset monolítico de entrenamiento en dos partes de manera cronológica de acuerdo al porcentaje especificado con `--val-ratio`.
- **Análisis de Logs (Regex)**: Inicia un proceso hijo del compilador C++ de LightGBM e intercepta y analiza su salida en tiempo real.
- **Lógica de Detección de Deriva (Early Stopping Emulado)**: Supervisa si la métrica de validación de LightGBM sube repetidamente mientras la métrica de entrenamiento baja.

## APIs / Módulos
- **OS / Shutil / Subprocess**: Interacción a bajo nivel con el sistema para mover archivos y lanzar el binario de LightGBM configurado mediante `RUTA_LIGHTGBM` o disponible en `PATH`.
- **Re (Expresiones Regulares)**: Para leer las métricas L2 por cada iteración del output estándar del entrenamiento de LightGBM.
- **Argparse**: Manipulación de argumentos de entrada (como el archivo de entrenamiento y el `--val-ratio`).

## Flujo de Procesamiento de Datos
1. **Segmentación**: Corta un dataset `.train` introducido por el usuario en dos (entrenamiento y validación).
2. **Configuración Virtual**: Modifica temporalmente una copia del archivo de configuración de LightGBM (`train.conf` a `overfitting_train.conf`) para inyectarle el archivo de validación y una ruta de modelo alternativa, evitando pisar el entorno de producción.
3. **Ejecución y Escucha**: Lanza LightGBM. Mientras entrena, un bucle lee la terminal y compara `training l2` vs `valid_1 l2`.
4. **Veredicto**: Al final, evalúa si la curva de error de validación subió tras un mínimo global y lanza una conclusión.

## Salida
- Muestra los logs en tiempo real.
- Proporciona un veredicto claro sobre el sobreajuste.
- Ofrece consejos técnicos estructurados para mitigarlo (cambiar parámetros como `early_stopping_round`, `min_data_in_leaf`, `feature_fraction`).
