# predecir_tramo.py

## Propósito
Realiza una predicción autorregresiva a ciegas sobre un tramo consecutivo del archivo de entrenamiento. A partir de un punto inicial aleatorio, el modelo predice la hora `t` y luego, desconectándose de la "realidad", inyecta su propia predicción como entrada para predecir `t+1`, repitiendo el proceso. Su objetivo es auditar la resiliencia del modelo, medir el efecto de "deriva" (drift) y detectar un posible sobreajuste (overfitting) o dependencia excesiva del lag `t-1`.

## Algoritmos
- **Simulación Autorregresiva Pura**: Sustitución dinámica de los datos reales de `t-1` y `t-24` por los outputs de las iteraciones anteriores del propio modelo.
- Cálculo de errores globales por tramo (MAE, Máximo).

## APIs / Módulos
- **Pandas & NumPy**: Manejo de los tramos secuenciales, operaciones matemáticas y cálculo de correlaciones.
- **LightGBM**: Para cargar y usar el modelo (`LightGBM_model.txt`).
- **Argparse**: Lectura de parámetros de consola como el horizonte de predicción (horas) y el punto de inicio manual.
- **Random**: Generación de un punto de inicio aleatorio dentro del dataset si no se especifica.

## Flujo de Procesamiento de Datos
1. **Configuración Inicial**: Lee el CSV de entrenamiento y determina el tramo consecutivo a simular (aleatorio o por parámetro `-i`).
2. **Carga y Recorte**: Extrae de los datos un segmento de N filas correspondientes a N horas.
3. **Bucle de Simulación**:
   - En la iteración 0 (hora inicial), se usa el retardo `t-1` real, emulando el momento presente.
   - En iteraciones `> 0`, el campo `demanda_t_1` se sobrescribe con la estimación obtenida en la iteración anterior.
   - En iteraciones `>= 24`, el campo `demanda_t_24h` se sobrescribe con la estimación obtenida 24 horas atrás.
   - LightGBM predice con estas características alteradas.
4. **Evaluación de Deriva**: Se acumulan los resultados y se comparan contra los valores reales ocultos del tramo original para evaluar cuánto se desvió a ciegas.

## Salida
- Representación en consola (ASCII) con la marca temporal exacta (obtenida de la base de datos), comparando la demanda Real vs. Predicha.
- Resumen final estadístico con el Error Absoluto Medio (MAE), Error Cuadrático Medio (RMSE), Error Porcentual Medio (MAPE), Error Máximo y Correlación de Pearson.
