# panel_control.py

## Propósito
Este programa es una aplicación web basada en Flask que sirve como panel de control (dashboard) para visualizar la demanda de energía en tiempo real y sus previsiones. Muestra datos históricos recientes y predicciones futuras en una interfaz gráfica. Además, se encarga de lanzar un proceso en segundo plano que actualiza la base de datos de manera continua.

## Algoritmos
- Recuperación de datos desde SQLite (`germany_data`).
- Lógica de combinación de series temporales (historial real + predicciones futuras).
- Sincronización en segundo plano con `threading` y `subprocess`.

## APIs / Módulos
- **Flask**: Para el servidor web y enrutamiento (API REST y renderizado de plantillas).
- **SQLite3**: Para conexión y consulta de la base de datos local `demanda_energia.db`.
- **Pandas**: Para la manipulación y cruce de los datos obtenidos de la BD.
- **predecir_futuro (módulo local)**: Para obtener las predicciones a futuro invocando `get_future_predictions()`.

## Flujo de Procesamiento de Datos
1. **Petición a la API (`/api/demanda`)**: El cliente solicita los datos.
2. **Lectura Histórica**: Extrae de SQLite las horas pasadas (por defecto 24) para la demanda real, previsión oficial y predicción del modelo.
3. **Predicción Futura**: Llama a `get_future_predictions()` para generar datos hacia el futuro (por defecto 12 horas).
4. **Agregación y Unión**: Une las fechas y valores de ambos bloques (pasado y futuro) gestionando valores nulos para el futuro en la serie "real".
5. **Respuesta**: Envía un objeto JSON estructurado con las etiquetas (fechas), la demanda real, predecida y oficial.

## Salida
- Página web interactiva (`index.html`).
- JSON en `/api/demanda` para pintar gráficas (por ej. Chart.js) en la interfaz gráfica.
