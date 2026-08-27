# espana_generar_series.py

## Propósito
Este script genera conjuntos de datos (datasets) sintéticos pero estadísticamente realistas que simulan la demanda de energía eléctrica en España. Su objetivo es proporcionar datos de entrenamiento robustos para modelos de Machine Learning (como LightGBM) sin necesidad de tener todo el histórico real, permitiendo probar con distintas resoluciones temporales (ej. minutales u horarias).

## Algoritmos
- **Simulación Meteorológica**: Funciones coseno y seno combinadas con ruido aleatorio para emular la temperatura de 3 ciudades clave (Madrid, Barcelona, Murcia) a lo largo del año.
- **Modelado de Demanda**: Vectores matemáticos para emular patrones horarios de consumo base, efectos de la reducción de demanda en fines de semana y festivos (nacionales), y un sistema de calefacción/climatización basado en diferencias térmicas, sumando un ruido gaussiano.
- **Ingeniería de Características**: Codificación trigonométrica (seno/coseno) de las variables temporales (hora del día y día del año).

## APIs / Módulos
- **Pandas & NumPy**: Para operaciones vectorizadas rápidas y generación de secuencias temporales (`date_range`).
- **Argparse**: Lectura de parámetros como la frecuencia de intervalo (`-i`), la fecha de inicio (`-s`) y fin (`-e`).

## Flujo de Procesamiento de Datos
1. **Configuración de Rango**: Genera un rango de fechas con la granularidad (intervalo) requerida por el usuario.
2. **Generación Climática**: Calcula matemáticamente y simula variaciones de temperatura de las 3 ciudades seleccionadas.
3. **Cálculo de Demanda Métrica**: Determina la demanda base a partir de un perfil horario y le añade penalizaciones (calendario) y aumentos según picos de frío o calor.
4. **Desfases (Lags)**: Crea de forma artificial las columnas predictoras correspondientes a la demanda pasada (`t-1` y `t-24h`), rellenando huecos.
5. **Formateo**: Organiza las columnas exactamente igual que la tabla de la base de datos de entrenamiento (ordenadas para LightGBM) y redondea los senos/cosenos.

## Salida
- Fichero `.train` (CSV) por defecto llamado `demanda_ree_produccion.train`, listo para ser consumido directamente por LightGBM.
