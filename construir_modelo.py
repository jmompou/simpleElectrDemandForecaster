#!/usr/bin/env python3
"""Generación de datasets de entrenamiento para LightGBM a partir de SQLite."""
import argparse
import pandas as pd
import sqlite3
import datetime
import sys
import pytz
from dateutil.relativedelta import relativedelta

TZ_BERLIN = pytz.timezone('Europe/Berlin')

import os
from dotenv import load_dotenv
load_dotenv()
RUTA_BASE = os.path.dirname(os.path.abspath(__file__))


RUTA_BD = os.path.join(RUTA_BASE, "bases_de_datos/demanda_energia.db")

# Columnas del .train en el orden que espera LightGBM
COLUMNAS_ENTRENAMIENTO = [
    'demanda_target',
    'demanda_t_1',
    'demanda_t_24h',
    'hora_sin',
    'hora_cos',
    'dia_ano_sin',
    'dia_ano_cos',
    'dia_semana',
    'es_festivo',
    'temp_berlin',
    'temp_hamburgo',
    'temp_munich',
    'temp_colonia',
    'temp_frankfurt',
    'temp_stuttgart',
    'temp_dusseldorf',
    'temp_leipzig',
    'temp_dortmund',
    'temp_essen',
]

COLUMNAS_REDONDEO = {
    'hora_sin': 4, 'hora_cos': 4,
    'dia_ano_sin': 4, 'dia_ano_cos': 4,
    'temp_berlin': 1, 'temp_hamburgo': 1, 'temp_munich': 1,
    'temp_colonia': 1, 'temp_frankfurt': 1, 'temp_stuttgart': 1,
    'temp_dusseldorf': 1, 'temp_leipzig': 1, 'temp_dortmund': 1,
    'temp_essen': 1,
}

CIUDADES_TEMP = [
    'temp_berlin', 'temp_hamburgo', 'temp_munich', 'temp_colonia',
    'temp_frankfurt', 'temp_stuttgart', 'temp_dusseldorf',
    'temp_leipzig', 'temp_dortmund', 'temp_essen',
]

def parsear_entrada(valor):
    """
    Intenta interpretar un valor string ingresado por el usuario (CLI) 
    como una marca de tiempo completa (YYYY-MM-DD HH:MM) o como una fecha (YYYY-MM-DD).
    Aplica la zona horaria de Berlín por defecto.
    Retorna el objeto datetime y el tipo de dato ('marca_temporal' o 'date').
    """
    for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            dt = datetime.datetime.strptime(valor, fmt)
            dt = TZ_BERLIN.localize(dt)
            tipo = 'marca_temporal' if ':' in valor else 'date'
            return dt, tipo
        except ValueError:
            continue
    print(f"Error: No se puede interpretar '{valor}'. Usa YYYY-MM-DD o 'YYYY-MM-DD HH:MM'.")
    sys.exit(1)

def parsear_rango(args):
    """
    A partir de los argumentos de línea de comandos (args), calcula y devuelve 
    las fechas exactas de inicio y fin (dt_inicio, dt_fin) para la consulta SQL.
    Maneja lógicas especiales como '--year' (año completo) o '--last-year' (últimos 365 días).
    """
    if args.year:
        dt_inicio = datetime.datetime(args.year, 1, 1, 0, 0, tzinfo=TZ_BERLIN)
        dt_fin = datetime.datetime(args.year, 12, 31, 23, 59, tzinfo=TZ_BERLIN)
        return dt_inicio, dt_fin
        
    if args.recent_days:
        dt_fin = (datetime.datetime.now(TZ_BERLIN) - datetime.timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=0)
        dt_inicio = (dt_fin - datetime.timedelta(days=args.recent_days)).replace(hour=0, minute=0, second=0)
        return dt_inicio, dt_fin
        
    if args.last_year:
        # La API de temperaturas históricas solo sirve datos hasta "ayer".
        # Para evitar colas de NaNs inútiles de "hoy", forzamos el fin de la ventana
        # a ayer a las 23:59:59.
        dt_fin = (datetime.datetime.now(TZ_BERLIN) - datetime.timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=0)
        dt_inicio = (dt_fin - relativedelta(years=1)).replace(hour=0, minute=0, second=0)
        return dt_inicio, dt_fin
    
    dt_from, tipo_from = parsear_entrada(args.fecha_desde)
    
    if args.fecha_hasta:
        dt_to, tipo_to = parsear_entrada(args.fecha_hasta)
        if tipo_to == 'date':
            dt_to = dt_to.replace(hour=23, minute=59)
        return dt_from, dt_to
    else:
        if tipo_from == 'date':
            dt_fin = dt_from.replace(hour=23, minute=59)
        else:
            dt_fin = dt_from
        return dt_from, dt_fin

def generar_nombre_salida(dt_inicio, dt_fin):
    """
    Genera un nombre de archivo por defecto basado en el rango de fechas.
    Ej: 'germany_2023-01-01_2023-12-31.train'
    """
    inicio_str = dt_inicio.strftime('%Y-%m-%d')
    fin_str = dt_fin.strftime('%Y-%m-%d')
    if inicio_str == fin_str:
        return f"germany_{inicio_str}.train"
    else:
        return f"germany_{inicio_str}_{fin_str}.train"

def exportar_entrenamiento(dt_inicio, dt_fin, fichero_salida, mostrar_consola=False):
    """
    Bloque principal ETL (Extract, Transform, Load) del script:
    1. Extract: Consulta la base de datos SQLite para extraer los registros en el rango de fechas.
    2. Transform: Filtra nulos, renombra columnas ('demanda_real' -> 'demanda_target'), 
       aplica redondeos y ordena las columnas para que coincidan exactamente con lo que LightGBM espera.
    3. Load: Escribe el DataFrame final a un archivo .csv/.train.
    """
    inicio_str = dt_inicio.strftime('%Y-%m-%d %H:%M')
    fin_str = dt_fin.strftime('%Y-%m-%d %H:%M')
    
    print(f"Periodo solicitado: {inicio_str} -> {fin_str}")
    
    conn = sqlite3.connect(RUTA_BD, timeout=30.0)
    
    df = pd.read_sql_query('''
        SELECT marca_temporal, demanda_real, demanda_t_1, demanda_t_24h,
               hora_sin, hora_cos, dia_ano_sin, dia_ano_cos,
               dia_semana, es_festivo,
               temp_berlin, temp_hamburgo, temp_munich, temp_colonia,
               temp_frankfurt, temp_stuttgart, temp_dusseldorf,
               temp_leipzig, temp_dortmund, temp_essen
        FROM datos_alemania
        WHERE marca_temporal >= ? AND marca_temporal <= ?
          AND demanda_real IS NOT NULL
        ORDER BY marca_temporal ASC
    ''', conn, params=(inicio_str, fin_str))
    
    conn.close()
    
    if df.empty:
        print("Error: No hay datos en la BD para el rango solicitado.")
        print("       Descárgalos primero con adquirir_datos.py")
        return
    
    df = df.rename(columns={'demanda_real': 'demanda_target'})
    
    nulos_pred = df['demanda_t_1'].isna().sum()
    nulos_temp = df[CIUDADES_TEMP].isna().any(axis=1).sum()
    
    if nulos_pred > 0:
        print(f"  [Aviso] {nulos_pred} registros sin features de predicción (demanda_t_1, etc.). Se excluirán.")
        df = df.dropna(subset=['demanda_t_1', 'demanda_t_24h'])
        
    if df.empty:
        print("  [Error] No quedaron registros útiles tras filtrar valores nulos.")
        return
    
    if nulos_temp > 0:
        print(f"  [Aviso] {nulos_temp} registros con temperaturas nulas. Se mantendrán como NaN para LightGBM.")
    
    df_train = df[COLUMNAS_ENTRENAMIENTO]
    
    df_train = df_train.round(COLUMNAS_REDONDEO)
    
    if args.val_ratio > 0:
        ratio_val = args.val_ratio / 100.0
        split_index = int(len(df_train) * (1.0 - ratio_val))
        df_t = df_train.iloc[:split_index]
        df_v = df_train.iloc[split_index:]
        train_file = fichero_salida.replace('.train', '_train.train')
        valid_file = fichero_salida.replace('.train', '_valid.valid')
        df_t.to_csv(train_file, index=False, header=True)
        df_v.to_csv(valid_file, index=False, header=True)
        print(f"\n--- Resultado ---")
        print(f"  Split Entrenamiento: {train_file} ({len(df_t)} registros)")
        print(f"  Split Validación:    {valid_file} ({len(df_v)} registros)")
    else:
        df_train.to_csv(fichero_salida, index=False, header=True)
        print(f"\n--- Resultado ---")
        print(f"  Fichero generado:    {fichero_salida}")
        print(f"  Registros:           {len(df_train)}")
        
    print(f"  Rango:               {df['marca_temporal'].iloc[0]} -> {df['marca_temporal'].iloc[-1]}")
    print(f"  Columnas:            {len(COLUMNAS_ENTRENAMIENTO)}")
    
    if mostrar_consola:
        print(f"\n--- Contenido completo del fichero ---")
        print(df_train.to_string(index=False))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Exportar datos de datos_alemania a fichero .train para LightGBM.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""Ejemplos de uso:
  # Exportar un año completo
  %(prog)s --year 2023

  # Exportar un rango de fechas
  %(prog)s -f 2023-06-01 -t 2023-06-30

  # Exportar con nombre personalizado
  %(prog)s --year 2023 -o mi_dataset.train

  # Exportar un solo día
  %(prog)s -f 2023-12-25
  
  # Exportar los últimos 365 días (ventana móvil para reentrenar)
  %(prog)s --last-year
  
  # Exportar los últimos 456 días (15 meses)
  %(prog)s --recent-days 456"""
    )
    
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--year", type=int,
                       help="Año completo a exportar (ej. 2023)")
    grupo.add_argument("--last-year", action="store_true",
                       help="Exportar exactamente los últimos 365 días desde el momento actual.")
    grupo.add_argument("--recent-days", type=int,
                       help="Exportar exactamente los últimos N días desde el momento actual.")
    grupo.add_argument("-f", "--from", dest="fecha_desde", type=str,
                       help="Fecha o marca de tiempo de inicio.\n"
                            "  Fecha:   YYYY-MM-DD (exporta el día completo si va solo)\n"
                            "  Hora:    'YYYY-MM-DD HH:MM' (exporta esa hora si va solo)")
    
    parser.add_argument("-t", "--to", dest="fecha_hasta", type=str,
                        help="Fecha o marca de tiempo de fin (mismo formato que -f).\n"
                             "Opcional: si se omite, se usa solo el valor de -f.")
    parser.add_argument("-o", "--output", type=str, default=None,
                        help="Nombre del fichero de salida (por defecto: germany_RANGO.train)")
    parser.add_argument("--val-ratio", type=float, default=0.0,
                        help="Porcentaje de datos para validación (ej. 20 para 20%). Si es >0, divide el dataset.")
    parser.add_argument("-c", "--console", action="store_true",
                        help="Mostrar todos los registros por consola en lugar de omitirlos.")
    
    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)
        
    args = parser.parse_args()
    
    dt_inicio, dt_fin = parsear_rango(args)
    
    fichero_salida = args.output if args.output else generar_nombre_salida(dt_inicio, dt_fin)
    
    exportar_entrenamiento(dt_inicio, dt_fin, fichero_salida, args.console)
