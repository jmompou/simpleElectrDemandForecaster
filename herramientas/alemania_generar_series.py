#!/usr/bin/env python3
"""
Script: alemania_generar_series.py
Descripción: Este script genera conjuntos de datos (datasets) sintéticos pero realistas 
             para simular la demanda de energía eléctrica alemana. Crea curvas climáticas, 
             patrones horarios de consumo, penalizaciones y variables estacionales o 
             cíclicas con resolución programable (ej. minutos, horas) que luego pueden
             ser consumidas por modelos de Machine Learning (como LightGBM).
"""

import argparse
import datetime
import numpy as np
import pandas as pd
import holidays

# =====================================================================
# 0. PARSEO DE ARGUMENTOS
# =====================================================================
parser = argparse.ArgumentParser(
    description="Generador de series temporales de demanda eléctrica (Alemania).",
    formatter_class=argparse.RawTextHelpFormatter,
    epilog="""Ejemplos de uso:
  ./alemania_generar_series.py -h
  
  ./alemania_generar_series.py -i "00:01:00"
  
  ./alemania_generar_series.py -i "02:00:00" -s "2028-06-01 00:00:00" -e "2028-08-01 00:00:00"
  
  ./alemania_generar_series.py -o mi_simulacion.train -c
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
parser.add_argument(
    "-o", "--output",
    type=str,
    default="demanda_germany_produccion.train",
    help="Nombre del fichero de salida (por defecto: demanda_germany_produccion.train)"
)
parser.add_argument(
    "-c", "--console",
    action="store_true",
    help="Mostrar todos los registros por consola en lugar de solo los 3 primeros"
)
args = parser.parse_args()

def parse_interval(interval_str):
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

festivos_de = holidays.DE(years=list(set(fechas.year)))

print(f"Generando {len(fechas)} registros para el periodo solicitado...")
print(f"¿Es año bisiesto?: {pd.Timestamp(f'{año}-01-01').is_leap_year}")

# =====================================================================
# 2. GENERACIÓN DE CURVAS CLIMÁTICAS SIMULADAS (ALEMANIA)
# =====================================================================
hora_fraccional = fechas.hour + fechas.minute / 60.0 + fechas.second / 3600.0
dia_fraccional = (fechas.dayofyear - 1) + (hora_fraccional / 24.0)

es_bisiesto = fechas.is_leap_year
divisores_año = np.where(es_bisiesto, 366, 365)

base_berlin    = 10 - 12 * np.cos(2 * np.pi * (dia_fraccional - 25) / divisores_año)
base_hamburg   = 9  - 10 * np.cos(2 * np.pi * (dia_fraccional - 25) / divisores_año)
base_munich    = 9  - 13 * np.cos(2 * np.pi * (dia_fraccional - 25) / divisores_año)
base_cologne   = 11 - 11 * np.cos(2 * np.pi * (dia_fraccional - 25) / divisores_año)
base_frankfurt = 11 - 12 * np.cos(2 * np.pi * (dia_fraccional - 25) / divisores_año)
base_stuttgart = 10 - 12 * np.cos(2 * np.pi * (dia_fraccional - 25) / divisores_año)
base_dusseldorf= 11 - 10 * np.cos(2 * np.pi * (dia_fraccional - 25) / divisores_año)
base_leipzig   = 10 - 12 * np.cos(2 * np.pi * (dia_fraccional - 25) / divisores_año)
base_dortmund  = 10 - 11 * np.cos(2 * np.pi * (dia_fraccional - 25) / divisores_año)
base_essen     = 10 - 11 * np.cos(2 * np.pi * (dia_fraccional - 25) / divisores_año)

oscilacion_diaria = 4 * np.sin(2 * np.pi * (hora_fraccional - 9) / 24)

np.random.seed(42)
ruido_clima = np.random.normal(0, 1.5, len(fechas))

temp_berlin    = base_berlin    + oscilacion_diaria       + ruido_clima
temp_hamburgo   = base_hamburg   + (oscilacion_diaria*0.8) + ruido_clima
temp_munich    = base_munich    + (oscilacion_diaria*1.2) + ruido_clima
temp_colonia   = base_cologne   + (oscilacion_diaria*0.9) + ruido_clima
temp_frankfurt = base_frankfurt + (oscilacion_diaria*1.1) + ruido_clima
temp_stuttgart = base_stuttgart + (oscilacion_diaria*1.1) + ruido_clima
temp_dusseldorf= base_dusseldorf+ (oscilacion_diaria*0.9) + ruido_clima
temp_leipzig   = base_leipzig   + oscilacion_diaria       + ruido_clima
temp_dortmund  = base_dortmund  + (oscilacion_diaria*0.9) + ruido_clima
temp_essen     = base_essen     + (oscilacion_diaria*0.9) + ruido_clima

# =====================================================================
# 3. CONSTRUCCIÓN DEL DATAFRAME BASE
# =====================================================================
df = pd.DataFrame(
    {
        "marca_temporal": fechas,
        "hora": fechas.hour,
        "dia_semana": fechas.dayofweek + 1,
        "temp_berlin": np.round(temp_berlin, 1),
        "temp_hamburgo": np.round(temp_hamburgo, 1),
        "temp_munich": np.round(temp_munich, 1),
        "temp_colonia": np.round(temp_colonia, 1),
        "temp_frankfurt": np.round(temp_frankfurt, 1),
        "temp_stuttgart": np.round(temp_stuttgart, 1),
        "temp_dusseldorf": np.round(temp_dusseldorf, 1),
        "temp_leipzig": np.round(temp_leipzig, 1),
        "temp_dortmund": np.round(temp_dortmund, 1),
        "temp_essen": np.round(temp_essen, 1),
    }
)

df["es_festivo"] = df["marca_temporal"].dt.date.isin(festivos_de).astype(int)

# =====================================================================
# 4. MODELADO MATEMÁTICO DE LA DEMANDA ALEMANA (VECTORIZADO OPTIMIZADO)
# =====================================================================
patron_horario_array = np.array([
    -4000, -5000, -5500, -5800, -5900, -4500, -2000, 500,
     3000,  4500,  5200,  5500,  5800,  6200,  5000, 3500,
     2800,  2900,  3400,  4800,  6000,  6400,  4000,  500
])

demanda_vectorial = 50000.0 + (patron_horario_array[df["hora"].values] * 2.5)

reduccion_calendario = np.where(
    (df["dia_semana"].values == 7) | (df["es_festivo"].values == 1), 
    15000,  # Fuerte caída
    np.where(df["dia_semana"].values == 6, 9000, 0)
)
demanda_vectorial -= reduccion_calendario

temp_ref = df["temp_frankfurt"].values  # Frankfurt como proxy central

calefaccion = np.maximum(0, 14 - temp_ref) ** 1.8 * 200
climatizacion = np.maximum(0, temp_ref - 22) ** 1.8 * 150

demanda_vectorial += calefaccion + climatizacion
demanda_vectorial += np.random.normal(0, 800, len(fechas))

df["demanda_target"] = demanda_vectorial.astype(int)

# =====================================================================
# 5. CODIFICACIÓN CÍCLICA AVANZADA
# =====================================================================
df["hora_sin"] = np.sin(2 * np.pi * hora_fraccional / 24.0)
df["hora_cos"] = np.cos(2 * np.pi * hora_fraccional / 24.0)

df["dia_ano_sin"] = np.sin(2 * np.pi * dia_fraccional / divisores_año)
df["dia_ano_cos"] = np.cos(2 * np.pi * dia_fraccional / divisores_año)

# =====================================================================
# 6. CREACIÓN DE VARIABLES DE DESFASE
# =====================================================================
df_temporal = df.set_index("marca_temporal")

shifted_t_1 = df_temporal["demanda_target"].shift(periods=1, freq=frecuencia)
df["demanda_t_1"] = df["marca_temporal"].map(shifted_t_1)

shifted_t_24h = df_temporal["demanda_target"].shift(periods=1, freq="D")
df["demanda_t_24h"] = df["marca_temporal"].map(shifted_t_24h)

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
    "temp_berlin",
    "temp_hamburgo",
    "temp_munich",
    "temp_colonia",
    "temp_frankfurt",
    "temp_stuttgart",
    "temp_dusseldorf",
    "temp_leipzig",
    "temp_dortmund",
    "temp_essen",
]

df_final = df[columnas_ordenadas]

df_final = df_final.round({
    "hora_sin": 4, 
    "hora_cos": 4, 
    "dia_ano_sin": 4, 
    "dia_ano_cos": 4
})

nombre_archivo = args.output
df_final.to_csv(nombre_archivo, index=False, header=True)

print(f"\n¡Fichero definitivo '{nombre_archivo}' generado con éxito!")
print(f"Dimensiones de la matriz de entrenamiento: {df_final.shape}")

if args.console:
    print("\n--- Contenido completo del fichero ---")
    print(df_final.to_string(index=False))
else:
    print("\n--- Vista de las primeras 3 líneas del fichero final ---")
    print(df_final.head(3).to_string(index=False))
