# adquirir_datos.py

## Propósito
Descarga datos de consumo real de energía (indicador 410) y previsiones oficiales (indicador 411) desde la API pública de SMARD para Alemania. Los consolida, calcula variables cíclicas y las incrusta junto a temperaturas históricas en una base de datos local SQLite, aplicando además un modelo LightGBM para inferir predicciones de consumo. Soporta inserción histórica (por fecha) y modo demonio/cron para ingesta en tiempo real (auto-sanación y fallback de datos nulos).

## Algoritmos
- **Conciliación Temporal**: Descarga por bloques semanales de la API y cruce con indexación en DataFrames.
- **Auto-Healing**: Invalida predicciones anteriores que usaron valores "fallback" si la demanda real para esa hora ya ha sido registrada en pasadas posteriores.
- **Ingeniería de Características**: Cálculo de valores cíclicos de la hora (`hora_sin`, `hora_cos`) y del día del año (`dia_ano_sin`, `dia_ano_cos`).
- **Inferencia (Machine Learning)**: Uso de un modelo `LightGBM` preentrenado (`LightGBM_model.txt`) para inferir el consumo energético y calcular errores (absolutos y porcentuales).

## APIs / Módulos
- **API SMARD (smard.de)**: Para los datos de consumo real y oficial alemán.
- **Open-Meteo API (Current / Archive)**: Para descargar las temperaturas de las principales ciudades alemanas.
- **LightGBM**: Para cargar el modelo y predecir.
- **Pandas & NumPy**: Procesamiento y cálculos trigonométricos.
- **Holidays**: Determinación de días festivos en Alemania (`holidays.DE`).

## Flujo de Procesamiento de Datos
1. **Descarga de Datos (Histórico / Actual)**: Extrae datos en bruto desde SMARD según el filtro temporal. 
2. **Obtención de Temperaturas**: Consulta las temperaturas pasadas (Archive API) o actuales de 10 ciudades en Alemania. Si falla la API, aplica un valor conocido ("salvavidas") de la BD.
3. **Transformación**: Se combinan en un DataFrame, respetando los valores nulos (NaNs) de forma nativa para evitar distorsiones o 'data leakage'. 
4. **Cálculo de Retardos (Lags) y Cíclicas**: Busca en la BD la demanda en t-1 y t-24 y genera variables temporales y de festividad.
5. **Predicción y Guardado**: Pasa las features generadas a LightGBM, obtiene el valor inferido y guarda/actualiza los registros completos en SQLite `germany_data`.

## Salida
- Inserción o actualización en la tabla SQLite `germany_data` (sin duplicados, con cláusula `ON CONFLICT DO UPDATE`).
- Logs y estadísticas por consola sobre el error absoluto/porcentual y el número de registros guardados.
