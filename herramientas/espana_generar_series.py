#!/usr/bin/env python3
"""
Script: generacion_series.py
Descripción: Este script genera conjuntos de datos (datasets) sintéticos pero realistas 
             para simular la demanda de energía eléctrica española. Crea curvas climáticas, 
             patrones horarios de consumo, penalizaciones y variables estacionales o 
             cíclicas con resolución programable (ej. minutos, horas) que luego pueden
             ser consumidas por modelos de Machine Learning (como LightGBM).
"""

import argparse
import datetime
import numpy as np
import pandas as pd

# =====================================================================
# 0. PARSEO DE ARGUMENTOS
# =====================================================================
parser = argparse.ArgumentParser(
    description="Generador de series temporales de demanda eléctrica.",
    formatter_class=argparse.RawTextHelpFormatter,
    epilog="""Ejemplos de uso:
  ./generacion_series.py -h
  
  ./generacion_series.py -i "00:01:00"
  
  ./generacion_series.py -i "02:00:00" -s "2028-06-01 00:00:00" -e "2028-08-01 00:00:00"
"""
)
parser.add_argument(
    "-i", "--interval", 
    type=str, 
    default="01:00:00", 
    help="Intervalo de generación (ej. '00:01:00' para 1 min, '02:00:00' para 2h)"
)
parser.add_argument(
    "-s", "--start",
    type=str,
    default="2028-01-01 00:00:00",
    help="Instante de inicio de la serie"
)
parser.add_argument(
    "-e", "--end",
    type=str,
    default=None,
    help="Instante de fin de la serie. Por defecto acaba el año de inicio."
)
args = parser.parse_args()

def parse_interval(interval_str):
    """
    Convierte la cadena de texto de entrada del usuario en el formato correcto
    para la función de Timedelta de Pandas.
    """
    parts = interval_str.split(':')
    if len(parts) == 4:
        return f"{int(parts[0])} days {parts[1]}:{parts[2]}:{parts[3]}"
    elif len(parts) == 3:
        return interval_str
    else:
        raise ValueError("Formato de intervalo no válido. Usa HH:MM:SS o DD:HH:MM:SS.")

frecuencia = pd.to_timedelta(parse_interval(args.interval))

# =====================================================================
# 1. CONFIGURACIÓN DEL PERIODO DE GENERACIÓN
# =====================================================================
start_dt = pd.to_datetime(args.start)
año = start_dt.year
end_date = args.end if args.end else f"{año}-12-31 23:59:59"

fechas = pd.date_range(start=args.start, end=end_date, freq=frecuencia)

festivos_fijos = ["01-01", "01-06", "05-01", "08-15", "10-12", "11-01", "12-06", "12-08", "12-25"]

print(f"Generando {len(fechas)} registros para el periodo solicitado...")
print(f"¿Es año bisiesto?: {pd.Timestamp(f'{año}-01-01').is_leap_year}")

# =====================================================================
# 2. GENERACIÓN DE CURVAS CLIMÁTICAS SIMULADAS (SUAVIZADO CONTINUO)
# =====================================================================
# de un minuto a otro o de un día a otro, simulando una curva natural de temperatura
hora_fraccional = fechas.hour + fechas.minute / 60.0 + fechas.second / 3600.0
dia_fraccional = (fechas.dayofyear - 1) + (hora_fraccional / 24.0)

es_bisiesto = fechas.is_leap_year
divisores_año = np.where(es_bisiesto, 366, 365)

# (hace menos calor en los primeros/últimos días del año y más en el centro)
base_madrid = 15 - 11 * np.cos(2 * np.pi * (dia_fraccional - 20) / divisores_año)
base_bcn = 17 - 8 * np.cos(2 * np.pi * (dia_fraccional - 25) / divisores_año)
base_murcia = 19 - 9 * np.cos(2 * np.pi * (dia_fraccional - 22) / divisores_año)

oscilacion_diaria = 5 * np.sin(2 * np.pi * (hora_fraccional - 9) / 24)

np.random.seed(42)
ruido_clima = np.random.normal(0, 2, len(fechas))

temp_madrid = base_madrid + oscilacion_diaria + ruido_clima
temp_bcn = base_bcn + (oscilacion_diaria * 0.7) + ruido_clima
temp_murcia = base_murcia + (oscilacion_diaria * 1.1) + ruido_clima + 2.5

# =====================================================================
# 3. CONSTRUCCIÓN DEL DATAFRAME BASE
# =====================================================================
df = pd.DataFrame(
    {
        "marca_temporal": fechas,
        "hora": fechas.hour,  # Usado más abajo como índice para el patrón horario
        "dia_semana": fechas.dayofweek + 1,
        "temp_madrid": np.round(temp_madrid, 1),
        "temp_bcn": np.round(temp_bcn, 1),
        "temp_murcia": np.round(temp_murcia, 1),
    }
)

df["es_festivo"] = df["marca_temporal"].dt.strftime("%m-%d").isin(festivos_fijos).astype(int)

# =====================================================================
# 4. MODELADO MATEMÁTICO DE LA DEMANDA (VECTORIZADO OPTIMIZADO)
# =====================================================================
patron_horario_array = np.array([
    -4000, -5000, -5500, -5800, -5900, -4500, -2000, 500,
     3000,  4500,  5200,  5500,  5800,  6200,  5000, 3500,
     2800,  2900,  3400,  4800,  6000,  6400,  4000,  500
])

demanda_vectorial = 24000.0 + patron_horario_array[df["hora"].values]

reduccion_calendario = np.where(
    (df["dia_semana"].values == 7) | (df["es_festivo"].values == 1), 
    6500,  # Fuerte caída los domingos o festivos
    np.where(df["dia_semana"].values == 6, 4000, 0) # Caída menor los sábados
)
demanda_vectorial -= reduccion_calendario

# o si hace mucho calor (aires acondicionados). Si la temperatura es moderada, no sube.
temp_ref = (df["temp_madrid"].values + df["temp_murcia"].values) / 2.0

calefaccion = np.maximum(0, 12 - temp_ref) ** 1.8 * 250
climatizacion = np.maximum(0, temp_ref - 25) ** 1.8 * 380

demanda_vectorial += calefaccion + climatizacion
demanda_vectorial += np.random.normal(0, 400, len(fechas))

df["demanda_target"] = demanda_vectorial.astype(int)

# =====================================================================
# 5. CODIFICACIÓN CÍCLICA AVANZADA (Para que el modelo aprenda ciclos)
# =====================================================================
df["hora_sin"] = np.sin(2 * np.pi * hora_fraccional / 24.0)
df["hora_cos"] = np.cos(2 * np.pi * hora_fraccional / 24.0)

df["dia_ano_sin"] = np.sin(2 * np.pi * dia_fraccional / divisores_año)
df["dia_ano_cos"] = np.cos(2 * np.pi * dia_fraccional / divisores_año)

# =====================================================================
# 6. CREACIÓN DE VARIABLES DE DESFASE (Lags Temporales Corregidos)
# =====================================================================
df_temporal = df.set_index("marca_temporal")

# t-1 es el valor de la demanda corrido hacia adelante un paso de "frecuencia" (ej. un minuto, dos horas)
shifted_t_1 = df_temporal["demanda_target"].shift(periods=1, freq=frecuencia)
df["demanda_t_1"] = df["marca_temporal"].map(shifted_t_1)

# t-24h representa exactamente la misma hora pero un día calendario entero ("D") antes
shifted_t_24h = df_temporal["demanda_target"].shift(periods=1, freq="D")
df["demanda_t_24h"] = df["marca_temporal"].map(shifted_t_24h)

# usando Int64 que permite NaNs nativamente
df["demanda_t_1"] = df["demanda_t_1"].astype('Int64')
df["demanda_t_24h"] = df["demanda_t_24h"].astype('Int64')

# =====================================================================
# 7. FORMATEO Y EXPORTACIÓN AL ESTÁNDAR LIGHTGBM
# =====================================================================
columnas_ordenadas = [
    "demanda_target",
    "demanda_t_1",
    "demanda_t_24h",
    "hora_sin",
    "hora_cos",
    "dia_ano_sin",
    "dia_ano_cos",
    "dia_semana",
    "es_festivo",
    "temp_madrid",
    "temp_bcn",
    "temp_murcia",
]

df_final = df[columnas_ordenadas]

df_final = df_final.round({
    "hora_sin": 4, 
    "hora_cos": 4, 
    "dia_ano_sin": 4, 
    "dia_ano_cos": 4
})

nombre_archivo = "demanda_ree_produccion.train"
df_final.to_csv(nombre_archivo, index=False, header=True)

print(f"\n¡Fichero definitivo '{nombre_archivo}' generado con éxito!")
print(f"Dimensiones de la matriz de entrenamiento: {df_final.shape}")

print("\n--- Vista de las primeras 3 líneas del fichero final ---")
print(df_final.head(3).to_string(index=False))