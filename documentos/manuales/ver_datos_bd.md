# ver_datos_bd.py

## Propósito
Herramienta de consola para realizar consultas rápidas de lectura sobre la base de datos SQLite (`demanda_energia.db`). Sirve para visualizar directamente los registros de la tabla `germany_data` filtrando por fechas, años o días recientes. Es muy útil para hacer comprobaciones visuales del estado de los datos (huecos, NaNs, previsiones vs real) desde la terminal sin necesidad de abrir herramientas SQL.

## Algoritmos
- **Parseo Dinámico de Fechas**: Interpreta comandos de entrada difusos (años, "últimos N días" o fechas específicas completas/parciales).
- **Extracción de Tablas**: Lectura de SQLite a DataFrames.

## APIs / Módulos
- **SQLite3**: Para conectar con `demanda_energia.db`.
- **Pandas**: Para cargar el resultado del query (`read_sql_query`) y formatear la salida tabular en consola.
- **Argparse & Sys**: Captura de parámetros (como año, `recent_days`, filtrado de columnas) e impresión de ayudas.
- **Zoneinfo / Datetime**: Manejo seguro de la zona horaria (Europa/Berlín).

## Flujo de Procesamiento de Datos
1. **Procesamiento de Argumentos**: Lee el periodo de tiempo deseado y el conjunto de columnas específicas que el usuario desea ver (o todas por defecto).
2. **Parseo Temporal**: Transforma la solicitud a objetos `datetime` limitando las fronteras entre `dt_inicio` y `dt_fin` en la zona horaria correcta.
3. **Consulta**: Se ejecuta el query `SELECT [cols] FROM germany_data WHERE timestamp >= ? AND timestamp <= ?` usando consultas parametrizadas para evitar inyección y mejorar el formato de las fechas.
4. **Impresión Tabular**: Utiliza los contextos temporales de Pandas (`pd.option_context`) para des-truncar columnas y/o filas e imprimir el DataFrame directamente por terminal.

## Salida
- Tabla ASCII en la consola con las columnas y registros solicitados (y el número total de registros). No modifica datos.
