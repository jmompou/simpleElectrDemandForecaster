#!/usr/bin/env python3
import argparse
import sqlite3
import pandas as pd
import datetime
import sys
import os
from dotenv import load_dotenv

try:
    import zoneinfo
    tz_berlin = zoneinfo.ZoneInfo('Europe/Berlin')
except ImportError:
    tz_berlin = datetime.timezone(datetime.timedelta(hours=2))

load_dotenv()
RUTA_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


RUTA_BD = os.path.join(RUTA_BASE, "bases_de_datos/demanda_energia.db")

def parsear_entrada(valor):
    valor = valor.strip()
    
    if ' ' in valor:
        dt = datetime.datetime.strptime(valor, '%Y-%m-%d %H:%M').replace(tzinfo=tz_berlin)
        return dt, 'marca_temporal'
    else:
        dt = datetime.datetime.strptime(valor, '%Y-%m-%d').replace(tzinfo=tz_berlin)
        return dt, 'date'

def parsear_rango(args):
    if getattr(args, 'recent_days', None):
        dt_fin = datetime.datetime.now(tz_berlin).replace(minute=59, second=59, microsecond=0)
        dt_inicio = (dt_fin - datetime.timedelta(days=args.recent_days)).replace(hour=0, minute=0, second=0)
        return dt_inicio, dt_fin
        
    if getattr(args, 'last_year', False):
        dt_fin = datetime.datetime.now(tz_berlin).replace(minute=59, second=59, microsecond=0)
        try:
            from dateutil.relativedelta import relativedelta
            dt_inicio = (dt_fin - relativedelta(years=1)).replace(hour=0, minute=0, second=0)
        except ImportError:
            dt_inicio = (dt_fin - datetime.timedelta(days=365)).replace(hour=0, minute=0, second=0)
        return dt_inicio, dt_fin
        
    if getattr(args, 'year', None):
        dt_inicio = datetime.datetime(args.year, 1, 1, 0, 0, tzinfo=tz_berlin)
        dt_fin = datetime.datetime(args.year, 12, 31, 23, 59, tzinfo=tz_berlin)
        return dt_inicio, dt_fin
    
    if getattr(args, 'fecha_desde', None):
        dt_from, tipo_from = parsear_entrada(args.fecha_desde)
        if getattr(args, 'fecha_hasta', None):
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
            
    return None, None

def main():
    parser = argparse.ArgumentParser(description="Mostrar filas de la base de datos demanda_energia.db para un periodo concreto.")
    parser.add_argument("--year", type=int, help="Año completo a consultar (ej. 2023)")
    parser.add_argument("-f", "--from", dest="fecha_desde", help="Fecha inicial (YYYY-MM-DD o 'YYYY-MM-DD HH:MM')")
    parser.add_argument("-t", "--to", dest="fecha_hasta", help="Fecha final (YYYY-MM-DD o 'YYYY-MM-DD HH:MM')")
    parser.add_argument("--recent-days", type=int, help="Consultar los últimos N días hasta hoy")
    parser.add_argument("--last-year", action="store_true", help="Consultar el último año entero (365 días) hasta hoy")
    parser.add_argument("--cols", type=str, help="Columnas específicas a mostrar separadas por coma (por defecto todas). Ejemplo: marca_temporal,demanda_real,prediccion")
    parser.add_argument("--all", action="store_true", help="Forzar imprimir todas las filas (sin truncado automático de Pandas)")
    
    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)
        
    args = parser.parse_args()

    dt_inicio, dt_fin = parsear_rango(args)

    if not dt_inicio or not dt_fin:
        parser.error("Debes especificar un periodo usando --year, --recent-days, --last-year o -f / -t.")

    inicio_str = dt_inicio.strftime('%Y-%m-%d %H:%M')
    fin_str = dt_fin.strftime('%Y-%m-%d %H:%M')
    
    try:
        conexion = sqlite3.connect(RUTA_BD, timeout=30.0)
    except Exception as e:
        print(f"Error conectando a la base de datos {RUTA_BD}: {e}")
        return
        
    cols = args.cols if args.cols else "*"
    consulta = f"SELECT {cols} FROM datos_alemania WHERE marca_temporal >= ? AND marca_temporal <= ? ORDER BY marca_temporal ASC"
    
    try:
        df = pd.read_sql_query(consulta, conexion, params=(inicio_str, fin_str))
    except Exception as e:
        print(f"Error ejecutando la consulta SQL: {e}")
        conexion.close()
        return
        
    conexion.close()
    
    if df.empty:
        print(f"No hay datos en la base de datos para el periodo solicitado ({inicio_str} -> {fin_str}).")
        return
        
    print(f"\n=== Mostrando datos para el periodo {inicio_str} -> {fin_str} ({len(df)} registros) ===\n")
    if args.all:
        with pd.option_context('display.max_rows', None, 'display.max_columns', None, 'display.width', 1000):
            print(df)
    else:
        with pd.option_context('display.max_columns', None, 'display.width', 1000):
            print(df)
    print("\n")

if __name__ == "__main__":
    main()
