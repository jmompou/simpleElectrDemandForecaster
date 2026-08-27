# predecir_aleatorio.py

## Propósito
Realiza evaluaciones de calidad del modelo a través de simulaciones multi-horizonte (de 1h a 168h) sobre muestras aleatorias del dataset de entrenamiento. Emplea un enfoque recursivo riguroso para evitar la "fuga de datos", permitiendo estudiar la resiliencia a largo plazo y cómo se acumula el error (deriva) en horizontes de previsión extendidos.

## Algoritmos
- **Muestreo aleatorio**: Selección de N puntos dentro de la serie temporal (garantizando margen suficiente para el horizonte máximo).
- **Simulación Multi-Horizonte Recursiva**: Generación de predicciones sin acceso a valores reales del futuro. Se re-inyectan las propias predicciones pasadas (t-1 y t-24) en el flujo iterativo.
- **Resolución de Fechas Inversa**: Conexión a SQLite local para mapear la demanda a su marca temporal exacta, evitando índices abstractos.

## APIs / Módulos
- **Pandas & NumPy**: Operaciones matriciales y cálculo de estadísticas avanzadas (RMSE, MAPE).
- **LightGBM**: Motor de inferencia del modelo preentrenado (`LightGBM_model.txt`).
- **SQLite3**: Búsqueda del timestamp real asociado al valor analizado.

## Flujo de Procesamiento de Datos
1. **Configuración**: Lee de consola el número `N` de predicciones a generar.
2. **Carga**: Lee el modelo y carga el archivo CSV `.train`. Crea un mapa de fechas desde la base de datos `demanda_energia.db`.
3. **Muestreo**: Elige `N` índices aleatoriamente (respetando los márgenes del horizonte).
4. **Simulación**: Para cada índice, y para cada horizonte (1h, 6h, 12h, 24h, 48h, 72h y 168h), "retrocede" en el tiempo H horas y simula de nuevo iterativamente hasta la hora diana, usando datos limpios de inercia.
5. **Evaluación**: Calcula el error porcentual y el error absoluto.
6. **Agregación**: Se calculan las medias y se aplica RMSE, MAE y MAPE global por horizonte sobre toda la muestra aleatoria.

## Salida
- Muestra detallada en consola de la Marca Temporal de cada muestra, junto con el desglose de su error en los distintos horizontes de predicción.
- Tabla final con el resumen de métricas global (MAE, RMSE, MAPE) desglosado por cada horizonte (de 1h a 168h).
