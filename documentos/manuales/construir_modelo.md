# construir_modelo.py

## Propósito
Actúa como un script de exportación ETL (Extract, Transform, Load) que extrae registros desde la tabla local de SQLite `germany_data`, los procesa para garantizar la consistencia en el formato que espera el algoritmo LightGBM, y genera un fichero `.train` (CSV) para entrenamiento o reentrenamiento del modelo predictivo de Alemania.

## Algoritmos
- Filtros de rangos temporales dinámicos (ventana móvil).
- Mapeo y ordenación estructurada de columnas según el orden interno de variables (features) que consume `lgb.Booster`.

## APIs / Módulos
- **SQLite3**: Para conectar a la base de datos `demanda_energia.db`.
- **Pandas**: Para manipulación, filtrado de NaNs, relleno de valores, redondeo numérico y exportación a CSV.
- **Dateutil (relativedelta)**: Para el cálculo dinámico de la ventana de 1 año (12 meses exactos hacia atrás).

## Flujo de Procesamiento de Datos
1. **Parcheo de Argumentos**: Lee la entrada por consola (CLI) para interpretar rangos estáticos, años completos, ventanas dinámicas (`--last-year` o `--recent-days N`) y si se debe realizar una división para validación (`--val-ratio`).
2. **Extracción**: Consulta `germany_data` obteniendo todas las variables (target, predictores temporales, festivos, y 10 temperaturas de ciudades).
3. **Transformación**: 
   - Renombra la columna original `demanda_real` a `demanda_target`.
   - Limpia/elimina registros que no posean las características de lag de demanda (`demanda_t_1` y `demanda_t_24h`).
   - Gestión de nulos (temperaturas faltantes se dejan como NaN o se fuerzan a 15.0 según los flags).
   - Ordena las columnas y aplica precisión decimal específica por columna.
4. **Carga (Load)**: Exporta el dataframe final. Si se pasa el parámetro `--val-ratio`, divide cronológicamente los datos en dos archivos con los sufijos `_train.train` y `_valid.valid`. Si no, exporta un único `.train`.

## Salida
- Uno o dos ficheros listos para entrenar (ej. `germany_15-meses.train` o bien `_train.train` y `_valid.valid`) listos para el entrenamiento y auditoría del sobreajuste.
