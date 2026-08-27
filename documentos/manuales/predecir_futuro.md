# predecir_futuro.py

## Propósito
Realiza predicciones en tiempo real para las próximas N horas usando el modelo LightGBM. Se nutre de la última demanda registrada en SQLite como punto de partida y de las predicciones meteorológicas a futuro de Open-Meteo, generando así previsiones sobre fechas venideras donde todavía no existe un dato "real" con el que comparar.

## Algoritmos
- **Predicción Autorregresiva**: El modelo infiere la hora `t`. El resultado de esa hora se retroalimenta al vector de características como `t-1` para predecir `t+1`, de forma iterativa durante todo el horizonte temporal especificado (por defecto 24 horas).
- Cálculo de variables cíclicas para las horas/días futuros.

## APIs / Módulos
- **Open-Meteo Forecast API**: Para descargar el pronóstico de temperaturas para las horas venideras en 10 ciudades alemanas.
- **LightGBM**: Motor de inferencia del modelo preentrenado.
- **SQLite3**: Extracción del punto de partida inicial (últimas 24h de demanda real registradas localmente).
- **Holidays & Pandas & NumPy**: Transformaciones de fechas futuras, cálculos trigonométricos e interpolación de series temporales.

## Flujo de Procesamiento de Datos
1. **Semilla Inicial**: Consulta en la base de datos `demanda_energia.db` las últimas 24 horas conocidas para usar el último dato como inercia.
2. **Descarga Meteorológica**: Conecta a Open-Meteo para obtener las temperaturas previstas para el número de horas solicitadas (`horas_pred`).
3. **Iteración Autorregresiva**: 
   - Para cada hora futura, se generan las variables de calendario (día, hora cíclica, festivo).
   - Se toman las previsiones meteorológicas y los lags autorregresivos (usando los registros históricos o las propias predicciones del ciclo anterior).
   - El modelo emite el pronóstico, que se guarda y se usa para alimentar los siguientes ciclos.
4. **Formato**: Agrupa los datos inferidos en una estructura temporal (timestamps, predicciones).

## Salida
- Puede devolver un diccionario (si se importa como módulo desde `panel_control.py`) con timestamps, predicciones y extra info.
- Si se ejecuta por consola (CLI), imprime una visualización ASCII tipo gráfico de barras mostrando la predicción hora a hora para el tramo futuro y estadísticas finales (media, pico).
