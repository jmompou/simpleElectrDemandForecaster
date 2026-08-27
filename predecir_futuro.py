#!/usr/bin/env python3
"""Predicción en tiempo real de la demanda eléctrica futura."""
import pandas as pd
import numpy as np
import lightgbm as lgb
import argparse
import sqlite3
import requests
import datetime
import holidays
import os
import time
import subprocess
import json
import zoneinfo
from dotenv import load_dotenv

load_dotenv()
RUTA_BASE = os.path.dirname(os.path.abspath(__file__))
tz_utc = datetime.timezone.utc
tz_berlin = zoneinfo.ZoneInfo('Europe/Berlin')
OPEN_METEO_API_MAX_REINTENTOS = int(os.getenv("OPEN_METEO_API_MAX_REINTENTOS", 3))


RUTA_BD = os.path.join(RUTA_BASE, "bases_de_datos/demanda_energia.db")
CIUDADES_ALEMANAS = {
    'temp_berlin': (52.5200, 13.4050),
    'temp_hamburgo': (53.5511, 9.9937),
    'temp_munich': (48.1351, 11.5820),
    'temp_colonia': (50.9375, 6.9603),
    'temp_frankfurt': (50.1109, 8.6821),
    'temp_stuttgart': (48.7758, 9.1829),
    'temp_dusseldorf': (51.2277, 6.7735),
    'temp_leipzig': (51.3397, 12.3731),
    'temp_dortmund': (51.5136, 7.4653),
    'temp_essen': (51.4556, 7.0116)
}

def obtener_demanda_ultimas_24h():
    """
    Obtiene las últimas 24 horas de la demanda real desde la base de datos local SQLite.
    Estos datos son necesarios para iniciar la predicción (T-1 y T-24).
    Retorna un DataFrame de Pandas ordenado cronológicamente.
    """
    conn = sqlite3.connect(RUTA_BD, timeout=30.0)
    # Obtener los últimos 24 registros con demanda real válida, ordenados ascendentemente por marca_temporal
    query = '''
    SELECT marca_temporal as timestamp, demanda_real 
    FROM datos_alemania 
    WHERE demanda_real IS NOT NULL 
    ORDER BY marca_temporal DESC 
    LIMIT 24
    '''
    df = pd.read_sql_query(query, conn)
    conn.close()
    if df.empty:
        raise ValueError("No hay datos históricos en la base de datos para arrancar.")
    df = df.sort_values('timestamp').reset_index(drop=True)
    return df

def obtener_temperaturas_pronostico(tiempo_inicio, horas_pred):
    """
    Descarga las temperaturas previstas para las próximas N horas usando Open-Meteo.
    Se solicitan para las 10 ciudades clave. Retorna un DataFrame con un índice temporal
    y una columna por cada ciudad.
    """
    # tiempo_inicio llega en UTC "naive" (convención de marca_temporal en la BD).
    # Open-Meteo con timezone=Europe/Berlin devuelve las horas en hora LOCAL de
    # Berlín (también naive), así que la ventana de descarga y el reindexado se
    # hacen en hora local para no desalinear las temperaturas por 1-2h (CET/CEST).
    inicio_local = tiempo_inicio.tz_localize(tz_utc).tz_convert(tz_berlin)
    fin_local = inicio_local + pd.Timedelta(hours=horas_pred)
    fecha_inicio_str = inicio_local.strftime('%Y-%m-%d')
    fecha_fin_str = fin_local.strftime('%Y-%m-%d')



    nombres = list(CIUDADES_ALEMANAS.keys())
    lats = ",".join(str(CIUDADES_ALEMANAS[n][0]) for n in nombres)
    lons = ",".join(str(CIUDADES_ALEMANAS[n][1]) for n in nombres)
    
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lats}&longitude={lons}&hourly=temperature_2m&start_date={fecha_inicio_str}&end_date={fecha_fin_str}&timezone=Europe%2FBerlin"
    
    dfs_pronostico = []
    
    max_retries = OPEN_METEO_API_MAX_REINTENTOS

    success = False
    for attempt in range(max_retries):
        try:
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            data = response.json()
            
            if isinstance(data, list):
                # Si devuelve múltiples ubicaciones, es una lista
                for i, nombre in enumerate(nombres):
                    city_data = data[i]
                    df_temp = pd.DataFrame({
                        "timestamp": pd.to_datetime(city_data["hourly"]["time"]),
                        nombre: city_data["hourly"]["temperature_2m"]
                    })
                    df_temp = df_temp.drop_duplicates(subset=['timestamp'])
                    dfs_pronostico.append(df_temp.set_index("timestamp"))
            else:
                # Fallback por si acaso
                df_temp = pd.DataFrame({
                    "timestamp": pd.to_datetime(data["hourly"]["time"]),
                    nombres[0]: data["hourly"]["temperature_2m"]
                })
                df_temp = df_temp.drop_duplicates(subset=['timestamp'])
                dfs_pronostico.append(df_temp.set_index("timestamp"))
            success = True
            break # Exit the retry loop if successful
            
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2)
            else:
                print(f"  [!] Open-Meteo inaccesible tras {max_retries} intentos: {e}.")
                
    marcas_temporales_necesarias_utc = [tiempo_inicio + pd.Timedelta(hours=i) for i in range(horas_pred)]
    marcas_temporales_necesarias_local = [
        ts.tz_localize(tz_utc).tz_convert(tz_berlin).tz_localize(None) for ts in marcas_temporales_necesarias_utc
    ]

    if not success:
        print("  [!] Open-Meteo inaccesible. Usando fallback con valores nulos (NaN).")
        df_filtrado = pd.DataFrame(np.nan, index=marcas_temporales_necesarias_utc, columns=list(CIUDADES_ALEMANAS.keys()))
        return df_filtrado

    df_todos = pd.concat(dfs_pronostico, axis=1)
    # Reindexar en hora local (coincide con lo que devuelve Open-Meteo) y luego
    # volver a etiquetar el índice en UTC para que sea compatible con current_ts
    # (que las llamadas de este módulo usan en convención UTC).
    df_filtrado = df_todos.reindex(marcas_temporales_necesarias_local)
    df_filtrado.index = marcas_temporales_necesarias_utc
    return df_filtrado

def obtener_predicciones_futuras(horas_pred):
    """
    Bucle principal de predicción autorregresiva para generar previsiones sobre
    fechas futuras. 
    1. Carga el último dato real conocido (la semilla).
    2. Descarga la previsión de temperaturas para el periodo futuro.
    3. Itera 'horas_pred' veces alimentando las predicciones (t-1, t-24) de vuelta
       al modelo de forma recursiva.
    """
    try:
        bst = lgb.Booster(model_file=os.path.join(RUTA_BASE, "modelos/LightGBM_model.txt"))
        columnas_features = bst.feature_name()
    except Exception as e:
        raise RuntimeError(f"Error cargando el modelo: {e}")

    df_lags = obtener_demanda_ultimas_24h()
    ultima_marca_temporal = pd.to_datetime(df_lags.iloc[-1]['timestamp'])
    
    marca_temporal_inicio_pronostico = ultima_marca_temporal + pd.Timedelta(hours=1)
    df_temps = obtener_temperaturas_pronostico(marca_temporal_inicio_pronostico, horas_pred)
    
    festivos_de = holidays.DE(years=[marca_temporal_inicio_pronostico.year, marca_temporal_inicio_pronostico.year + 1])
    
    predicciones = []
    timestamps_futuros = []
    extra_info_list = []
    historial_reciente = list(df_lags['demanda_real'].values)
    
    DIAS = {1: 'Lun', 2: 'Mar', 3: 'Mié', 4: 'Jue', 5: 'Vie', 6: 'Sáb', 7: 'Dom'}
    
    for i in range(horas_pred):
        current_ts = marca_temporal_inicio_pronostico + pd.Timedelta(hours=i)

        t1 = historial_reciente[-1]
        t24 = historial_reciente[-24]

        # current_ts está en UTC "naive" (convención de marca_temporal en la BD).
        # Las features de calendario/hora deben calcularse en hora LOCAL de
        # Berlín, igual que en adquirir_datos.py, porque así fue entrenado el modelo.
        dt_local = current_ts.tz_localize(tz_utc).tz_convert(tz_berlin)
        hora_decimal = dt_local.hour + dt_local.minute / 60.0
        hora_sin = np.sin(2 * np.pi * hora_decimal / 24.0)
        hora_cos = np.cos(2 * np.pi * hora_decimal / 24.0)

        dia_del_ano = dt_local.dayofyear
        dia_fraccional = (dia_del_ano - 1) + (hora_decimal / 24.0)
        es_bisiesto = dt_local.year % 4 == 0 and (dt_local.year % 100 != 0 or dt_local.year % 400 == 0)
        divisores_ano = 366 if es_bisiesto else 365
        dia_ano_sin = np.sin(2 * np.pi * dia_fraccional / divisores_ano)
        dia_ano_cos = np.cos(2 * np.pi * dia_fraccional / divisores_ano)

        dia_semana = dt_local.weekday() + 1
        es_festivo = 1 if dt_local.date() in festivos_de else 0

        fila_temps = df_temps.loc[current_ts]
        diccionario_fila = {
            'demanda_t_1': t1, 'demanda_t_24h': t24,
            'hora_sin': hora_sin, 'hora_cos': hora_cos,
            'dia_ano_sin': dia_ano_sin, 'dia_ano_cos': dia_ano_cos,
            'dia_semana': dia_semana, 'es_festivo': es_festivo
        }
        for col in df_temps.columns:
            diccionario_fila[col] = fila_temps[col]
            
        df_X = pd.DataFrame([diccionario_fila], columns=columnas_features)
        valor_pred = int(np.floor(bst.predict(df_X)[0]))
        
        dia_str = DIAS.get(dia_semana, str(dia_semana))
        lab_str = "FES" if es_festivo else "LAB"
        temps_vals = ",".join([f"{x:.1f}" for x in fila_temps.values])
        cadena_extra = f"({dia_str} | {lab_str}) | Lags(t-1: {int(t1)}, t-24: {int(t24)}) | TºC: ({temps_vals})"
        
        predicciones.append(valor_pred)
        timestamps_futuros.append(current_ts.strftime('%Y-%m-%d %H:%M'))
        extra_info_list.append(cadena_extra)
        historial_reciente.append(valor_pred)
        
    return {"timestamps": timestamps_futuros, "predictions": predicciones, "extra_info": extra_info_list}

def predecir_futuro_cli(horas_pred):
    try:
        data = obtener_predicciones_futuras(horas_pred)
    except Exception as e:
        print(e)
        return
        
    # Extraemos solo para visual
    df_lags = obtener_demanda_ultimas_24h()
    ultima_marca_temporal = pd.to_datetime(df_lags.iloc[-1]['timestamp'])
    ultima_demanda_conocida = int(df_lags.iloc[-1]['demanda_real'])
    
    print(f"Conectando con base de datos para obtener el último estado real...")
    print(f"Último dato real conocido: {ultima_marca_temporal.strftime('%Y-%m-%d %H:%M')} -> {ultima_demanda_conocida} MW")
    print(f"Descargando previsión meteorológica para las próximas {horas_pred} horas...")
    
    print(f"\nPREDICCIÓN EN TIEMPO REAL: PRÓXIMAS {horas_pred} HORAS (FUTURO)")
    
    # Emular el loop visual anterior
    predicciones = data['predictions']
    ts_list = data['timestamps']
    extra_info_list = data.get('extra_info', [""] * horas_pred)
    for i in range(horas_pred):
        valor_pred = predicciones[i]
        ts_str = ts_list[i]
        cadena_extra = extra_info_list[i]
        if cadena_extra:
            print(f"[{ts_str}] {cadena_extra}")
        else:
            print(f"[{ts_str}]")
        print(f"  >>> Predicción: {valor_pred:5d} MW")
        print()
        
    print("\nFIN DE LA PREDICCIÓN")
    print(f"  Previsión media en el periodo: {np.mean(predicciones):.1f} MW")
    print(f"  Pico máximo esperado:          {np.max(predicciones)} MW")
    print("\n¡Recuerda! Estos valores son el FUTURO REAL y están calculados usando")
    print("los pronósticos meteorológicos de Open-Meteo. No hay datos 'reales' con")
    print("los que compararlos hasta que transcurra el día.\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Predecir las próximas N horas en tiempo real.")
    parser.add_argument("-H", "--horas", type=int, default=24, help="Número de horas futuras a predecir")
    args = parser.parse_args()
    predecir_futuro_cli(args.horas)
