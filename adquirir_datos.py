#!/usr/bin/env python3
"""Pipeline de ingesta y consolidación de datos de SMARD y Open-Meteo en SQLite."""
import argparse
import requests
import pandas as pd
import datetime
import sqlite3
try:
    import zoneinfo
    tz_berlin = zoneinfo.ZoneInfo('Europe/Berlin')
except ImportError:
    # Sin zoneinfo no podemos calcular el offset real (varía con el horario de verano).
    # Requiere Python 3.9+; en sistemas viejos instalar el paquete 'tzdata'.
    raise RuntimeError(
        "Se requiere zoneinfo (Python 3.9+) o el paquete 'tzdata' para gestionar "
        "correctamente la zona horaria Europe/Berlin y el cambio de hora."
    )
tz_utc = datetime.timezone.utc
import os
import time
import numpy as np
import holidays
import lightgbm as lgb
from dotenv import load_dotenv

load_dotenv()
RUTA_BASE = os.path.dirname(os.path.abspath(__file__))


# CONFIGURACIÓN DE PARÁMETROS (Constantes)

# Ruta de la base de datos
RUTA_BD = os.path.join(RUTA_BASE, "bases_de_datos/demanda_energia.db")

# Parámetros para la API de SMARD
SMARD_API_RETRASO_SEGUNDOS = float(os.getenv("SMARD_API_RETRASO_SEGUNDOS", 0.5))
SMARD_API_RETRASO_REINTENTO_SEGUNDOS = float(os.getenv("SMARD_API_RETRASO_REINTENTO_SEGUNDOS", 1.0))
SMARD_API_MAX_REINTENTOS = int(os.getenv("SMARD_API_MAX_REINTENTOS", 3))

# --- Configuración Open-Meteo API ---
OPEN_METEO_API_RETRASO_SEGUNDOS = float(os.getenv("OPEN_METEO_API_RETRASO_SEGUNDOS", 0.5))
OPEN_METEO_RETRASO_REINTENTO_SEGUNDOS = float(os.getenv("OPEN_METEO_RETRASO_REINTENTO_SEGUNDOS", 1.0))
OPEN_METEO_API_MAX_REINTENTOS = int(os.getenv("OPEN_METEO_API_MAX_REINTENTOS", 3))

# --- Configuración de Detección de Anomalías ---
# Factor de consistencia MAD -> sigma, corregido para muestra finita (n=4..12).
# El detector estacional usa hasta 4 semanas x 3 offsets = 12 puntos, pero a veces
# se recuperan menos por huecos en el histórico. El factor asintótico (1.4826) solo
# es válido para n grande; con menos muestras el MAD crudo subestima la dispersión
# real y hace falta un factor mayor para no disparar falsos positivos.
# Calibrado por simulación Monte Carlo (normal estándar, 8M repeticiones por n).
FACTORES_MAD_ESTACIONAL = {
    4: 2.0178, 5: 1.8036, 6: 1.7635, 7: 1.6867,
    8: 1.6713, 9: 1.6325, 10: 1.6247, 11: 1.6012, 12: 1.5960,
}
N_MIN_MUESTRAS_MAD = min(FACTORES_MAD_ESTACIONAL)
N_MAX_MUESTRAS_MAD = max(FACTORES_MAD_ESTACIONAL)

def factor_mad_estacional(n_muestras):
    """Factor de corrección MAD->sigma para una muestra de tamaño n_muestras."""
    n = max(N_MIN_MUESTRAS_MAD, min(N_MAX_MUESTRAS_MAD, int(n_muestras)))
    return FACTORES_MAD_ESTACIONAL[n]

def init_tabla_lecturas(conn):
    """Crea la tabla datos_alemania si no existe."""
    conn.execute('''
        CREATE TABLE IF NOT EXISTS datos_alemania (
            marca_temporal DATETIME PRIMARY KEY,  -- almacenada en UTC ('%Y-%m-%d %H:%M'); evita colisiones por DST
            demanda_real REAL,
            demanda_prevision REAL,
            prediccion REAL,
            error_absoluto REAL,
            error_porc REAL,
            demanda_t_1 REAL,
            demanda_t_24h REAL,
            hora_sin REAL,
            hora_cos REAL,
            dia_ano_sin REAL,
            dia_ano_cos REAL,
            dia_semana INTEGER,
            es_festivo INTEGER,
            temp_berlin REAL,
            temp_hamburgo REAL,
            temp_munich REAL,
            temp_colonia REAL,
            temp_frankfurt REAL,
            temp_stuttgart REAL,
            temp_dusseldorf REAL,
            temp_leipzig REAL,
            temp_dortmund REAL,
            temp_essen REAL,
            creado_el DATETIME DEFAULT CURRENT_TIMESTAMP,
            smard_consolidado INTEGER DEFAULT 0,
            meteo_consolidado INTEGER DEFAULT 0,
            prediccion_1h REAL,
            prediccion_6h REAL,
            prediccion_12h REAL,
            prediccion_24h REAL,
            prediccion_48h REAL,
            prediccion_72h REAL,
            prediccion_168h REAL
        )
    ''')
    conn.commit()

def descargar_smard(dt_inicio, dt_fin):
    """
    Descarga datos de SMARD entre dt_inicio y dt_fin (objetos datetime con tz).
    Retorna un DataFrame consolidado con columnas [demanda_real, demanda_prevision].
    """
    print(f"Periodo solicitado: {dt_inicio.strftime('%Y-%m-%d %H:%M')} -> {dt_fin.strftime('%Y-%m-%d %H:%M')}")
    
    indicadores = {
        'demanda_real': '410',
        'demanda_prevision': '411'
    }
    
    region = 'DE'
    resolution = 'hour'
    
    # Convertir los límites a milisegundos UTC para comparar con los marca_temporals del índice
    inicio_ms = int(dt_inicio.timestamp() * 1000)
    fin_ms = int(dt_fin.timestamp() * 1000)
    
    dfs = []
    
    for nombre, filtro in indicadores.items():
        print(f"\n--- Procesando {nombre} (Filtro: {filtro}) ---")
        
        # Obtener el índice de marca_temporals semanales
        index_url = f"https://www.smard.de/app/chart_data/{filtro}/{region}/index_{resolution}.json"
        response = requests.get(index_url, timeout=10)
        if response.status_code != 200:
            print(f"Error descargando el índice para {filtro}.")
            continue
            
        marca_temporals_disponibles = response.json().get('timestamps', [])
        
        # Filtrar los bloques semanales que cubren nuestro rango
        # Cada bloque cubre ~1 semana (168 horas). Necesitamos descargar el bloque
        # que contiene dt_inicio (puede empezar antes) y todos hasta dt_fin.
        marca_temporals_a_descargar = []
        for i, ts in enumerate(marca_temporals_disponibles):
            # El bloque 'ts' cubre desde 'ts' hasta el siguiente marca_temporal (o +7 días)
            ts_siguiente = marca_temporals_disponibles[i + 1] if i + 1 < len(marca_temporals_disponibles) else ts + 7 * 24 * 3600 * 1000
            
            # Si el bloque solapa con nuestro rango, lo descargamos
            if ts_siguiente > inicio_ms and ts <= fin_ms:
                marca_temporals_a_descargar.append(ts)
        
        # Añadir el bloque anterior al inicio para cubrir posibles solapamientos de zona horaria
        if marca_temporals_a_descargar:
            idx_primero = marca_temporals_disponibles.index(marca_temporals_a_descargar[0])
            if idx_primero > 0:
                marca_temporals_a_descargar.insert(0, marca_temporals_disponibles[idx_primero - 1])
                
        print(f"Se descargarán {len(marca_temporals_a_descargar)} bloques semanales.")
        
        # Descargar los datos de cada bloque (saltando los que ya estén completos en BD)
        datos_en_bruto = []
        bloques_saltados = 0
        
        conn_check = sqlite3.connect(RUTA_BD, timeout=30.0)
        
        for ts in marca_temporals_a_descargar:
            # Comprobar si este bloque semanal ya está completo en la BD (en UTC)
            ts_inicio_bloque = pd.to_datetime(ts, unit='ms', utc=True)
            ts_fin_bloque = ts_inicio_bloque + pd.Timedelta(days=7) - pd.Timedelta(hours=1)
            inicio_bloque_str = ts_inicio_bloque.strftime('%Y-%m-%d %H:%M')
            fin_bloque_str = ts_fin_bloque.strftime('%Y-%m-%d %H:%M')
            
            try:
                existentes = conn_check.execute(
                    'SELECT COUNT(*) FROM datos_alemania WHERE marca_temporal >= ? AND marca_temporal <= ? AND smard_consolidado = 1',
                    (inicio_bloque_str, fin_bloque_str)
                ).fetchone()[0]
            except sqlite3.OperationalError:
                existentes = 0
            
            if existentes >= 168:  # Una semana completa = 168 horas
                bloques_saltados += 1
                continue
            

            for intento in range(SMARD_API_MAX_REINTENTOS):
                # Usar el delay normal para el primer intento, y el de retry para los fallos
                time.sleep(SMARD_API_RETRASO_SEGUNDOS if intento == 0 else SMARD_API_RETRASO_REINTENTO_SEGUNDOS)
                
                try:
                    data_url = f"https://www.smard.de/app/chart_data/{filtro}/{region}/{filtro}_{region}_{resolution}_{ts}.json"
                    r = requests.get(data_url, timeout=10)
                    if r.status_code == 200:
                        data = r.json().get('series', [])
                        datos_en_bruto.extend(data)

                        break
                    else:
                        if intento == SMARD_API_MAX_REINTENTOS - 1:
                            print(f"Aviso: Fallo al descargar el bloque {ts} (HTTP {r.status_code})")
                except Exception as e:
                    if intento == SMARD_API_MAX_REINTENTOS - 1:
                        print(f"Aviso: Error de conexión al descargar el bloque {ts}: {e}")
        
        conn_check.close()
        
        if bloques_saltados > 0:
            print(f"  [{bloques_saltados} bloques ya completos en BD, saltados]")
                
        if not datos_en_bruto:
            print(f"No hay datos disponibles para este periodo en {nombre}.")
            continue
            
        df = pd.DataFrame(datos_en_bruto, columns=['marca_temporal', nombre])
        
        df['marca_temporal'] = pd.to_datetime(df['marca_temporal'], unit='ms', utc=True)
        # Se conserva en UTC como clave canónica (evita colisiones/huecos por DST).
        # Las features de calendario/hora se derivan de la hora local más adelante.
        df = df.set_index('marca_temporal')
        df = df[dt_inicio:dt_fin]
        
        # Eliminar duplicados si los hubiera por solapamientos entre bloques
        df = df[~df.index.duplicated(keep='last')]
        
        df = df.sort_index()
        
        dfs.append(df)
        print(f"Procesamiento de {nombre} completado. Registros: {len(df)}")
        
    if len(dfs) == 0:
        print("\n[BD] No hay nuevos datos que consolidar (todos los bloques requeridos ya estaban en la BD).")
        return None
        
    print("\n--- Cruzando y consolidando datos ---")
    df_final = pd.concat(dfs, axis=1)
    
    df_final['smard_consolidado'] = 1
    
    # Detección y filtrado de anomalías (Outliers) en datos históricos usando MAD Estacional
    if 'demanda_real' in df_final.columns:
        anomalies_mask = pd.Series(False, index=df_final.index)
        
        try:
            conn = sqlite3.connect(RUTA_BD, timeout=30.0)
            # Cargar histórico para calcular estacionalidad (4 semanas + margen)
            fecha_min_hist = df_final.index.min() - pd.Timedelta(weeks=5)
            df_bd = pd.read_sql_query(
                "SELECT marca_temporal, demanda_real FROM datos_alemania WHERE marca_temporal >= ? AND demanda_real IS NOT NULL", 
                conn, params=(fecha_min_hist.strftime('%Y-%m-%d %H:%M'),)
            )
            conn.close()
            
            df_bd['marca_temporal'] = pd.to_datetime(df_bd['marca_temporal'], utc=True)
            df_bd = df_bd.set_index('marca_temporal')
            
            # Combinar con los nuevos datos descargados
            df_combined = df_bd.combine_first(df_final[['demanda_real']])
            
            # Matriz temporal de 4 semanas * 3 horas = 12 muestras históricas
            df_shifted = pd.DataFrame(index=df_final.index)
            for w in range(1, 5):
                for offset in [-1, 0, 1]:
                    shift_time = df_final.index - pd.Timedelta(weeks=w) + pd.Timedelta(hours=offset)
                    df_shifted[f'w{w}_h{offset}'] = shift_time.map(df_combined['demanda_real'])
            
            mediana_historica_mad = df_shifted.median(axis=1)
            desviaciones_mad = df_shifted.sub(mediana_historica_mad, axis=0).abs()
            mad_historico_raw = desviaciones_mad.median(axis=1)

            # Requerimos al menos 4 muestras no nulas para validar
            muestras_validas = df_shifted.notna().sum(axis=1)
            factor_por_fila = muestras_validas.map(factor_mad_estacional)
            mad_historico = mad_historico_raw * factor_por_fila

            # MAD mínimo para evitar divisiones por cero
            mad_historico_safe = mad_historico.replace(0, np.nan).fillna(1000)

            z_score_mad = (df_final['demanda_real'] - mediana_historica_mad).abs() / mad_historico_safe

            anomalies_mask |= ((z_score_mad > 3) & (muestras_validas >= 4))
            
        except Exception as e:
            print(f"Aviso: Fallo al calcular MAD estacional vectorizado, omitiendo detección ({e})")
        
        num_anomalies = anomalies_mask.sum()
        if num_anomalies > 0:
            print(f"Aviso: Se han detectado {num_anomalies} valores anómalos en demanda_real (MAD > 3). Iniciando imputación.")
            
            # 0. Desmarcar como consolidados para reintento futuro
            df_final.loc[anomalies_mask, 'smard_consolidado'] = 0
            
            # 1. Imputación por Previsión Oficial
            if 'demanda_prevision' in df_final.columns:
                df_final.loc[anomalies_mask, 'demanda_real'] = df_final.loc[anomalies_mask, 'demanda_prevision']
                
            # 2. Imputación por t-168 (Semana anterior) si sigue nulo (porque no había previsión o era nula)
            nulos_actuales = df_final['demanda_real'].isna()
            if nulos_actuales.any():
                df_final.loc[nulos_actuales, 'demanda_real'] = df_final['demanda_real'].shift(168)[nulos_actuales]
                
            # 3. Imputación por Mediana Horaria Histórica del mismo día de la semana
            nulos_actuales = df_final['demanda_real'].isna()
            if nulos_actuales.any():
                df_final['hora'] = df_final.index.hour
                df_final['dia_semana'] = df_final.index.dayofweek
                mediana_historica = df_final.groupby(['dia_semana', 'hora'])['demanda_real'].transform('median')
                df_final.loc[nulos_actuales, 'demanda_real'] = mediana_historica[nulos_actuales]
                df_final.drop(columns=['hora', 'dia_semana'], inplace=True)
                
            # 4. Fallback final (forward/backward fill) para el inicio de la serie
            df_final['demanda_real'] = df_final['demanda_real'].ffill().bfill()
    
    huecos = df_final.isna().sum().sum()
    if huecos > 0:
        print(f"Aviso: Se han encontrado {huecos} valores nulos. Se guardarán como NULL en BD para LightGBM.")

    print(f"\nDatos consolidados: {df_final.shape[0]} registros horarios.")
    print(f"Inicio de la serie: {df_final.index.min()}")
    print(f"Fin de la serie:    {df_final.index.max()}")
    
    return df_final

def insertar_en_bd(datos):
    """Inserta los registros en la tabla datos_alemania de forma dinámica y tolerante a conflictos (UPSERT).
       Acepta un DataFrame o una lista de diccionarios."""
    conn = sqlite3.connect(RUTA_BD, timeout=30.0)
    init_tabla_lecturas(conn)
    
    registros_nuevos = 0
    registros_existentes = 0
    
    if isinstance(datos, pd.DataFrame):
        df_final = datos.copy()
        if df_final.index.name == 'marca_temporal':
            df_final = df_final.reset_index()
        elif 'marca_temporal' not in df_final.columns and isinstance(df_final.index, pd.DatetimeIndex):
            df_final = df_final.reset_index(names='marca_temporal')
            
        if pd.api.types.is_datetime64_any_dtype(df_final['marca_temporal']):
            df_final['marca_temporal'] = df_final['marca_temporal'].dt.strftime('%Y-%m-%d %H:%M')
            
        df_final = df_final.replace({np.nan: None, pd.NaT: None})
        lista_datos = df_final.to_dict('records')
    else:
        lista_datos = datos

    if not lista_datos:
        conn.close()
        return

    columnas = list(lista_datos[0].keys())
    columnas_sql = ", ".join(columnas)
    placeholders = ", ".join(["?"] * len(columnas))
    updates = ", ".join([f"{col} = COALESCE(excluded.{col}, datos_alemania.{col})" for col in columnas if col != 'marca_temporal'])
    
    query = f'''
        INSERT INTO datos_alemania ({columnas_sql})
        VALUES ({placeholders})
        ON CONFLICT(marca_temporal) DO UPDATE SET 
            {updates}
    '''
    
    for row in lista_datos:
        valores = [row.get(col) for col in columnas]
        cursor = conn.execute(query, valores)
        if cursor.rowcount > 0:
            registros_nuevos += 1
        else:
            registros_existentes += 1
    
    conn.commit()
    conn.close()
    
    print(f"\n--- Resultado de inserción en BD ---")
    print(f"[BD] Nuevos registros insertados:  {registros_nuevos}")
    print(f"[BD] Registros ya existentes:      {registros_existentes}")
    print(f"[BD] Total procesados:             {registros_nuevos + registros_existentes}")

# BLOQUE DE PREDICCIÓN: datos_alemania -> datos_alemania

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

def obtener_temperaturas_historicas(fecha_inicio, fecha_fin):
    """Descarga temperaturas históricas de Open-Meteo Archive API para un rango de fechas."""
    print("Descargando temperaturas históricas de Open-Meteo...")
    
    # Cota superior en UTC (coherente con la clave). Open-Meteo Archive va con ~1 día de retardo.
    ayer = pd.Timestamp.now(tz='UTC') - datetime.timedelta(days=1)
    if fecha_fin.tzinfo is None:
        ayer = ayer.tz_localize(None)
    if fecha_fin > ayer:
        fecha_fin = ayer
    
    if fecha_inicio > fecha_fin:
        print("  [Info] El rango solicitado es posterior a los datos disponibles en la Archive API.")
        return pd.DataFrame()
    
    inicio_str = fecha_inicio.strftime('%Y-%m-%d')
    fin_str = fecha_fin.strftime('%Y-%m-%d')
    
    df_temp = pd.DataFrame()
    
    for nombre, (lat, lon) in CIUDADES_ALEMANAS.items():
        time.sleep(OPEN_METEO_API_RETRASO_SEGUNDOS)  # Delay para no saturar Open-Meteo
        url = (
            f"https://archive-api.open-meteo.com/v1/archive?"
            f"latitude={lat}&longitude={lon}&start_date={inicio_str}&end_date={fin_str}"
            f"&hourly=temperature_2m&timezone=GMT"
        )
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                tiempos = data['hourly']['time']
                temps = data['hourly']['temperature_2m']
                serie = pd.Series(temps, index=pd.to_datetime(tiempos))
                df_temp[nombre] = serie
            else:
                print(f"  [!] Error de API para {nombre} ({r.status_code})")
        except Exception as e:
            print(f"  [!] Error de conexión para {nombre}: {e}")
    
    if df_temp.empty:
        print("  [!] No se pudieron obtener temperaturas históricas.")
        return pd.DataFrame()
    

    df_temp.index = df_temp.index.strftime('%Y-%m-%d %H:%M')
    return df_temp

def procesar_predicciones_pendientes():
    """Genera predicciones para los registros de datos_alemania donde falte la predicción o haya nulos (si complete=True)."""
    conn = sqlite3.connect(RUTA_BD, timeout=30.0)
    
    # Auto-healing: invalida predicciones si los datos reales (t-1/t-24) acaban de llegar, forzando un recálculo limpio.
    conn.execute('''
        UPDATE datos_alemania 
        SET prediccion = NULL, demanda_t_1 = NULL, demanda_t_24h = NULL 
        WHERE (demanda_t_1 = demanda_real AND EXISTS (
                SELECT 1 FROM datos_alemania g2 
                WHERE g2.marca_temporal = strftime('%Y-%m-%d %H:%M', datetime(datos_alemania.marca_temporal, '-1 hour'))
              ))
           OR (demanda_t_24h = demanda_real AND EXISTS (
                SELECT 1 FROM datos_alemania g2 
                WHERE g2.marca_temporal = strftime('%Y-%m-%d %H:%M', datetime(datos_alemania.marca_temporal, '-24 hours'))
              ))
           OR EXISTS (
                SELECT 1 FROM datos_alemania g2 
                WHERE g2.marca_temporal = strftime('%Y-%m-%d %H:%M', datetime(datos_alemania.marca_temporal, '-1 hour'))
                  AND g2.demanda_real IS NOT NULL 
                  AND ABS(datos_alemania.demanda_t_1 - g2.demanda_real) > 0.001
              )
           OR EXISTS (
                SELECT 1 FROM datos_alemania g2 
                WHERE g2.marca_temporal = strftime('%Y-%m-%d %H:%M', datetime(datos_alemania.marca_temporal, '-24 hours'))
                  AND g2.demanda_real IS NOT NULL 
                  AND ABS(datos_alemania.demanda_t_24h - g2.demanda_real) > 0.001
              )
    ''')
    conn.commit()
    
    # Buscar marca_temporals pendientes de procesar (predicción faltante o temperaturas nulas)
    pendientes = pd.read_sql_query('''
        SELECT marca_temporal, demanda_real
        FROM datos_alemania
        WHERE (prediccion IS NULL OR meteo_consolidado = 0)
          AND demanda_real IS NOT NULL
        ORDER BY marca_temporal ASC
    ''', conn)
    
    if pendientes.empty:
        print("\n[Predict] No hay registros pendientes de procesar.")
        conn.close()
        return
    
    print(f"\n--- Procesando {len(pendientes)} registros pendientes ---")
    
    todas_lecturas = pd.read_sql_query(
        'SELECT marca_temporal, demanda_real FROM datos_alemania ORDER BY marca_temporal ASC', conn
    )
    todas_lecturas = todas_lecturas.set_index('marca_temporal')
    demanda_serie = todas_lecturas['demanda_real']
    
    fecha_min = datetime.datetime.strptime(pendientes['marca_temporal'].iloc[0], '%Y-%m-%d %H:%M')
    fecha_max = datetime.datetime.strptime(pendientes['marca_temporal'].iloc[-1], '%Y-%m-%d %H:%M')
    # Ampliamos 1 día por margen
    fecha_min_fetch = fecha_min - datetime.timedelta(days=1)
    fecha_max_fetch = fecha_max + datetime.timedelta(days=1)
    
    df_temps = obtener_temperaturas_historicas(fecha_min_fetch, fecha_max_fetch)
    
    model_path = os.path.join(RUTA_BASE, "modelos/LightGBM_model.txt")
    tiene_modelo = os.path.exists(model_path)
    if tiene_modelo:
        bst = lgb.Booster(model_file=model_path)
        feature_names = bst.feature_name()
    else:
        print(f"  [Aviso] No se encuentra el modelo {model_path}. Solo se calcularán features.")
        bst = None
        feature_names = None
    
    años = set()
    for ts_str in pendientes['marca_temporal']:
        # ts_str está en UTC; el festivo se decide por la fecha LOCAL de Berlín
        dt_local = (datetime.datetime.strptime(ts_str, '%Y-%m-%d %H:%M')
                    .replace(tzinfo=tz_utc).astimezone(tz_berlin))
        años.add(dt_local.year)
    festivos_de = holidays.DE(years=list(años))
    
    insertados = 0
    errores = 0
    
    for _, row in pendientes.iterrows():
        ts_str = row['marca_temporal']
        demanda_real = row['demanda_real']
        
        try:
            dt_utc = datetime.datetime.strptime(ts_str, '%Y-%m-%d %H:%M').replace(tzinfo=tz_utc)

            # Retardos: t-1 y t-24 en UTC (correcto siempre; UTC no tiene cambio de hora)
            dt_menos_1 = (dt_utc - datetime.timedelta(hours=1)).strftime('%Y-%m-%d %H:%M')
            dt_menos_24 = (dt_utc - datetime.timedelta(hours=24)).strftime('%Y-%m-%d %H:%M')
            
            demanda_t_1 = demanda_serie.get(dt_menos_1, np.nan)
            demanda_t_24h = demanda_serie.get(dt_menos_24, np.nan)
            
            # Features de calendario/hora: en hora LOCAL de Berlín (la demanda sigue el reloj de pared)
            dt_local = dt_utc.astimezone(tz_berlin)
            hora_decimal = dt_local.hour + dt_local.minute / 60.0
            hora_sin = np.sin(2 * np.pi * hora_decimal / 24.0)
            hora_cos = np.cos(2 * np.pi * hora_decimal / 24.0)
            
            dia_del_ano = dt_local.timetuple().tm_yday
            dia_fraccional = (dia_del_ano - 1) + (hora_decimal / 24.0)
            es_bisiesto = dt_local.year % 4 == 0 and (dt_local.year % 100 != 0 or dt_local.year % 400 == 0)
            divisores_ano = 366 if es_bisiesto else 365
            dia_ano_sin = np.sin(2 * np.pi * dia_fraccional / divisores_ano)
            dia_ano_cos = np.cos(2 * np.pi * dia_fraccional / divisores_ano)
            
            dia_semana = dt_local.weekday() + 1
            es_festivo = 1 if dt_local.date() in festivos_de else 0
            
            temps = {}
            for ciudad in CIUDADES_ALEMANAS.keys():
                if ts_str in df_temps.index and ciudad in df_temps.columns:
                    temps[ciudad] = df_temps.loc[ts_str, ciudad]
                else:
                    temps[ciudad] = np.nan  # fallback a NaN para insertar NULL en BD
            
            diccionario_caracteristicas = {
                'demanda_t_1': demanda_t_1,
                'demanda_t_24h': demanda_t_24h,
                'hora_sin': hora_sin,
                'hora_cos': hora_cos,
                'dia_ano_sin': dia_ano_sin,
                'dia_ano_cos': dia_ano_cos,
                'dia_semana': dia_semana,
                'es_festivo': es_festivo,
            }
            diccionario_caracteristicas.update(temps)
            
            if tiene_modelo:
                features_h = pd.DataFrame([diccionario_caracteristicas])
                features_h = features_h[feature_names]
                prediccion = bst.predict(features_h)[0]
                diferencia = prediccion - demanda_real
                porcentaje = (diferencia / demanda_real) * 100 if demanda_real else 0
                pred_val = int(prediccion)
                dif_val = int(diferencia)
                porc_val = round(porcentaje, 2)
            else:
                pred_val = None
                dif_val = None
                porc_val = None
            
            conn.execute('''
                UPDATE datos_alemania SET
                    meteo_consolidado = 1,
                    prediccion = ?, error_absoluto = ?, error_porc = ?,
                    demanda_t_1 = ?, demanda_t_24h = ?,
                    hora_sin = ?, hora_cos = ?,
                    dia_ano_sin = ?, dia_ano_cos = ?,
                    dia_semana = ?, es_festivo = ?,
                    temp_berlin = ?, temp_hamburgo = ?,
                    temp_munich = ?, temp_colonia = ?,
                    temp_frankfurt = ?, temp_stuttgart = ?,
                    temp_dusseldorf = ?, temp_leipzig = ?,
                    temp_dortmund = ?, temp_essen = ?
                WHERE marca_temporal = ?
            ''', (
                pred_val, dif_val, porc_val,
                demanda_t_1, demanda_t_24h,
                hora_sin, hora_cos,
                dia_ano_sin, dia_ano_cos,
                dia_semana, es_festivo,
                temps['temp_berlin'], temps['temp_hamburgo'],
                temps['temp_munich'], temps['temp_colonia'],
                temps['temp_frankfurt'], temps['temp_stuttgart'],
                temps['temp_dusseldorf'], temps['temp_leipzig'],
                temps['temp_dortmund'], temps['temp_essen'],
                ts_str
            ))
            insertados += 1
            
        except Exception as e:
            print(f"  [!] Error procesando {ts_str}: {e}")
            errores += 1
    
    conn.commit()
    conn.close()
    
    print(f"\n--- Resultado de predicciones ---")
    print(f"[Predict] Predicciones generadas:  {insertados}")
    if errores > 0:
        print(f"[Predict] Errores:                 {errores}")

def parsear_entrada(valor):
    """Parsea un valor de entrada como fecha (YYYY-MM-DD) o marca de tiempo (YYYY-MM-DD HH:MM)."""
    valor = valor.strip()
    
    # Intentar como marca de tiempo completa
    if ' ' in valor:
        dt = datetime.datetime.strptime(valor, '%Y-%m-%d %H:%M').replace(tzinfo=tz_berlin)
        return dt, 'marca_temporal'
    else:
        dt = datetime.datetime.strptime(valor, '%Y-%m-%d').replace(tzinfo=tz_berlin)
        return dt, 'date'

def parsear_rango(args):
    """Devuelve (dt_inicio, dt_fin) a partir de los argumentos."""
    if getattr(args, 'recent_days', None):
        dt_fin = datetime.datetime.now(tz_berlin).replace(minute=59, second=59, microsecond=0)
        dt_inicio = (dt_fin - datetime.timedelta(days=args.recent_days)).replace(hour=0, minute=0, second=0)
        return dt_inicio, dt_fin
        
    if args.year:
        dt_inicio = datetime.datetime(args.year, 1, 1, 0, 0, tzinfo=tz_berlin)
        dt_fin = datetime.datetime(args.year, 12, 31, 23, 59, tzinfo=tz_berlin)
        return dt_inicio, dt_fin
    
    # Modo -f / -t
    dt_from, tipo_from = parsear_entrada(args.fecha_desde)
    
    if args.fecha_hasta:
        dt_to, tipo_to = parsear_entrada(args.fecha_hasta)
        # Si es una fecha sin hora, expandir hasta el final del día
        if tipo_to == 'date':
            dt_to = dt_to.replace(hour=23, minute=59)
        return dt_from, dt_to
    else:
        # Solo se ha pasado -f: un solo instante o un día completo
        if tipo_from == 'date':
            dt_fin = dt_from.replace(hour=23, minute=59)
        else:
            dt_fin = dt_from  # Una sola hora
        return dt_from, dt_fin

def obtener_temperaturas_actuales():
    temps_dict_modelo = {ciudad: np.nan for ciudad in CIUDADES_ALEMANAS.keys()} 
    temps_dict_bd = {ciudad: np.nan for ciudad in CIUDADES_ALEMANAS.keys()}
    
    nombres = list(CIUDADES_ALEMANAS.keys())
    lats = ",".join(str(CIUDADES_ALEMANAS[n][0]) for n in nombres)
    lons = ",".join(str(CIUDADES_ALEMANAS[n][1]) for n in nombres)
    
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lats}&longitude={lons}&current=temperature_2m&timezone=Europe%2FBerlin"
    
    for intento in range(OPEN_METEO_API_MAX_REINTENTOS):
        time.sleep(OPEN_METEO_RETRASO_REINTENTO_SEGUNDOS)
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                
                # Open-Meteo array format for multiple coordinates
                if isinstance(data, list):
                    for i, nombre in enumerate(nombres):
                        if 'current' in data[i] and 'temperature_2m' in data[i]['current']:
                            valor = data[i]['current']['temperature_2m']
                            temps_dict_modelo[nombre] = valor
                            temps_dict_bd[nombre] = valor
                else:
                    # Fallback just in case it returns a single object
                    if 'current' in data and 'temperature_2m' in data['current']:
                        valor = data['current']['temperature_2m']
                        for nombre in nombres:
                            temps_dict_modelo[nombre] = valor
                            temps_dict_bd[nombre] = valor
                            
                break
            else:
                if intento == OPEN_METEO_API_MAX_REINTENTOS - 1:
                    print(f"  [!] Error al descargar temperaturas actuales: HTTP {r.status_code}")
        except Exception as e:
            if intento == OPEN_METEO_API_MAX_REINTENTOS - 1:
                print(f"  [!] Error de conexión al descargar temperaturas actuales: {e}")
                
    return temps_dict_modelo, temps_dict_bd

def obtener_demandas_reales():
    """
    Descarga el valor de la demanda eléctrica real (indicador 410) emitido en tiempo real
    por la API de SMARD. Retorna la demanda target (t), los lags t-1 y t-24 consultando 
    la base de datos local de forma segura mediante fechas para evitar off-by-one errors.
    """
    try:
        index_url = "https://www.smard.de/app/chart_data/410/DE/index_hour.json"
        response = requests.get(index_url, timeout=10)
        response.raise_for_status()
        marca_temporals = response.json().get('timestamps', [])
        if not marca_temporals:
            now = pd.Timestamp.now(tz='UTC')
            return None, None, None, now.strftime('%Y-%m-%d %H:%M'), now
        
        def get_series(ts):
            data_url = f"https://www.smard.de/app/chart_data/410/DE/410_DE_hour_{ts}.json"
            r = requests.get(data_url, timeout=10)
            if r.status_code == 200:
                return r.json().get('series', [])
            return []
            
        latest_ts = marca_temporals[-1]
        series_current = get_series(latest_ts)
        
        demanda_objetivo = None
        ts_ms_target = None
        idx_target = -1
        week_idx = -1
        
        for i in range(len(series_current)-1, -1, -1):
            if series_current[i][1] is not None:
                demanda_objetivo = series_current[i][1]
                ts_ms_target = series_current[i][0]
                idx_target = i
                break
                
        # Si no hay datos en el fichero de la semana actual (ej. acaba de empezar)
        if demanda_objetivo is None and len(marca_temporals) >= 2:
            week_idx = -2
            series_current = get_series(marca_temporals[-2])
            for i in range(len(series_current)-1, -1, -1):
                if series_current[i][1] is not None:
                    demanda_objetivo = series_current[i][1]
                    ts_ms_target = series_current[i][0]
                    idx_target = i
                    break
                    
        if demanda_objetivo is None:
            now = pd.Timestamp.now(tz='UTC')
            return None, None, None, now.strftime('%Y-%m-%d %H:%M'), now
            
        def get_historical_val(offset):
            target_idx = idx_target - offset
            if target_idx >= 0:
                return series_current[target_idx][1]
            else:
                prev_week_idx = week_idx - 1
                if abs(prev_week_idx) <= len(marca_temporals):
                    series_prev = get_series(marca_temporals[prev_week_idx])
                    if series_prev:
                        return series_prev[len(series_prev) + target_idx][1]
            return None
            
        # Clave canónica en UTC; los lags se calculan en UTC (sin problemas de DST)
        target_dt = pd.to_datetime(ts_ms_target, unit='ms', utc=True)
        marca_temporal_str = target_dt.strftime('%Y-%m-%d %H:%M')
        
        dt_menos_1 = (target_dt - datetime.timedelta(hours=1)).strftime('%Y-%m-%d %H:%M')
        dt_menos_24 = (target_dt - datetime.timedelta(hours=24)).strftime('%Y-%m-%d %H:%M')
        
        demanda_t1 = None
        demanda_t24 = None
        
        try:
            conn = sqlite3.connect(RUTA_BD, timeout=30.0)
            cursor = conn.cursor()
            
            cursor.execute("SELECT demanda_real FROM datos_alemania WHERE marca_temporal = ?", (dt_menos_1,))
            row1 = cursor.fetchone()
            if row1 and row1[0] is not None:
                demanda_t1 = row1[0]
                
            cursor.execute("SELECT demanda_real FROM datos_alemania WHERE marca_temporal = ?", (dt_menos_24,))
            row24 = cursor.fetchone()
            if row24 and row24[0] is not None:
                demanda_t24 = row24[0]
                
            conn.close()
        except Exception as e:
            print(f"Error consultando lags en BD: {e}")
            
        if demanda_t1 is None: 
            demanda_t1 = get_historical_val(1)
        if demanda_t24 is None: 
            demanda_t24 = get_historical_val(24)
            
        # Validación de Anomalías en Tiempo Real con MAD Estacional (12 muestras)
        if demanda_objetivo is not None:
            try:
                conn = sqlite3.connect(RUTA_BD, timeout=30.0)
                cursor = conn.cursor()
                
                # Construir generador dinámico de marcas de tiempo (4 semanas, offsets -1, 0, +1 h)
                dt_list = []
                for w in range(1, 5):
                    for offset in [-1, 0, 1]:
                        dt_list.append((target_dt - datetime.timedelta(weeks=w) + datetime.timedelta(hours=offset)).strftime('%Y-%m-%d %H:%M'))
                
                placeholders = ','.join(['?'] * len(dt_list))
                cursor.execute(
                    f"SELECT demanda_real FROM datos_alemania WHERE marca_temporal IN ({placeholders}) AND demanda_real IS NOT NULL", 
                    tuple(dt_list)
                )
                rows_multi = cursor.fetchall()
                if len(rows_multi) >= 4: # Mínima muestra representativa
                    valores_multi = [r[0] for r in rows_multi]
                    mediana_multi = np.median(valores_multi)
                    desviaciones = [abs(v - mediana_multi) for v in valores_multi]
                    mad_multi_raw = np.median(desviaciones)
                    mad_multi = mad_multi_raw * factor_mad_estacional(len(valores_multi))
                    mad_multi = mad_multi if mad_multi > 0 else 1000.0 # MAD de seguridad
                    
                    if abs(demanda_objetivo - mediana_multi) / mad_multi > 3:
                        print(f"Aviso: Dato real {demanda_objetivo} MW es anomalía estacional (MAD > 3, muestra={len(valores_multi)}). Iniciando imputación en caliente.")
                        demanda_objetivo = None # Forzar bloque de imputación
                        
                if demanda_objetivo is None:
                    # Imputación 1: Previsión Oficial
                    cursor.execute("SELECT demanda_prevision FROM datos_alemania WHERE marca_temporal = ?", (marca_temporal_str,))
                    row_prev = cursor.fetchone()
                    if row_prev and row_prev[0] is not None:
                        demanda_objetivo = row_prev[0]
                        print(f"  -> Imputado usando demanda_prevision: {demanda_objetivo} MW")
                    else:
                        # Imputación 2: t-168
                        dt_menos_168 = (target_dt - datetime.timedelta(hours=168)).strftime('%Y-%m-%d %H:%M')
                        cursor.execute("SELECT demanda_real FROM datos_alemania WHERE marca_temporal = ?", (dt_menos_168,))
                        row_168 = cursor.fetchone()
                        if row_168 and row_168[0] is not None:
                            demanda_objetivo = row_168[0]
                            print(f"  -> Imputado usando t-168: {demanda_objetivo} MW")
                        else:
                            # Imputación 3: Mediana 24h
                            demanda_objetivo = mediana_24h if 'mediana_24h' in locals() else None
                            print(f"  -> Imputado usando mediana móvil: {demanda_objetivo} MW")
                conn.close()
            except Exception as e:
                print(f"Error comprobando estadísticas para validación: {e}")
            
        return demanda_objetivo, demanda_t1, demanda_t24, marca_temporal_str, target_dt.to_pydatetime()
        
    except Exception as e:
        print(f"Error descargando demanda real de SMARD: {e}")
        
    now = pd.Timestamp.now(tz='UTC')
    return None, None, None, now.strftime('%Y-%m-%d %H:%M'), now  # Fallback en caso de error


def ejecutar_modo_cron(train_file=None):
    """
    Función principal ejecutada periódicamente por el sistema (ej. cada 5 min).
    1. Obtiene el último dato de demanda real disponible.
    2. Carga las variables temporales cíclicas (seno/coseno del día/hora) y festivos.
    3. Descarga la temperatura actual usando la API (o el sistema de salvavidas).
    4. Carga el modelo LightGBM guardado localmente e infiere el valor esperado.
    5. Inserta un nuevo registro consolidado en la tabla `datos_alemania` de SQLite,
       incluyendo el cálculo de error para auditorías posteriores.
    """
    import os

    bst = lgb.Booster(model_file=os.path.join(RUTA_BASE, "modelos/LightGBM_model.txt"))
    
    # Obtener el dato real que acaba de ocurrir (t), su t-1, su t-24 y su marca temporal exacta
    demanda_real_target, demanda_t_1, demanda_t_24h, marca_temporal_str, ahora = obtener_demandas_reales()
    
    # Calcular las variables cíclicas para la hora actual.
    # 'ahora' viene en UTC (clave canónica); las features siguen el reloj de pared local.
    ahora_local = ahora.astimezone(tz_berlin)
    hora_decimal = ahora_local.hour + ahora_local.minute / 60.0
    hora_sin = np.sin(2 * np.pi * hora_decimal / 24.0)
    hora_cos = np.cos(2 * np.pi * hora_decimal / 24.0)
    
    dia_del_año = ahora_local.timetuple().tm_yday
    dia_fraccional = (dia_del_año - 1) + (hora_decimal / 24.0)
    es_bisiesto = ahora_local.year % 4 == 0 and (ahora_local.year % 100 != 0 or ahora_local.year % 400 == 0)
    divisores_año = 366 if es_bisiesto else 365
    dia_ano_sin = np.sin(2 * np.pi * dia_fraccional / divisores_año)
    dia_ano_cos = np.cos(2 * np.pi * dia_fraccional / divisores_año)
    
    dia_semana = ahora_local.weekday() + 1
    
    festivos_de = holidays.DE(years=[ahora_local.year])
    es_festivo = 1 if ahora_local.date() in festivos_de else 0
    
    temps_modelo, temps_bd = obtener_temperaturas_actuales()
    
    # COMPOSICIÓN DEL VECTOR DE ENTRADA ACTUALIZADO
    # Debe respetar estrictamente el orden de columnas del archivo .train
    diccionario_caracteristicas = {
        'demanda_t_1': demanda_t_1,
        'demanda_t_24h': demanda_t_24h,
        'hora_sin': hora_sin,
        'hora_cos': hora_cos,
        'dia_ano_sin': dia_ano_sin,
        'dia_ano_cos': dia_ano_cos,
        'dia_semana': dia_semana,
        'es_festivo': es_festivo,
    }
    
    # Añadimos las temperaturas al diccionario de características (con valores provisionales si la API falló)
    diccionario_caracteristicas.update(temps_modelo)
    
    features_h = pd.DataFrame([diccionario_caracteristicas])
    
    features_h = features_h[bst.feature_name()]
    
    prediccion_hora_h = bst.predict(features_h)[0]
    if demanda_real_target is not None:
        diferencia = prediccion_hora_h - demanda_real_target
        porcentaje = (diferencia / demanda_real_target) * 100 if demanda_real_target else 0
    else:
        diferencia = None
        porcentaje = None
    
    print("-" * 50)
    print("Características (Features) pasadas al modelo:")
    for feature in bst.feature_name():
        val = features_h[feature].iloc[0]
        if isinstance(val, float):
            print(f"  {feature:<15}: {val:.4f}")
        else:
            print(f"  {feature:<15}: {val}")
            
    print("-" * 50)
    print(f"Marca temporal analizada:       {marca_temporal_str}")
    print(f"Valor real medido:              {demanda_real_target if demanda_real_target is not None else 'N/A'} MW")
    print(f"Predicción generada:            {int(prediccion_hora_h)} MW")
    print(f"Diferencia absoluta:            {int(diferencia) if diferencia is not None else 'N/A'} MW")
    print(f"Diferencia porcentual:          {porcentaje if porcentaje is not None else 'N/A'}")
    print("-" * 50)
    
    try:
        conn = sqlite3.connect(RUTA_BD, timeout=30.0)
        c = conn.cursor()
        
        init_tabla_lecturas(conn)
        
        # Obtener la previsión oficial de SMARD (indicador 411) para la hora actual y el futuro
        demanda_prevision = None
        future_previsions = {}
        try:
            idx_url = "https://www.smard.de/app/chart_data/411/DE/index_hour.json"
            r_idx = requests.get(idx_url, timeout=10)
            if r_idx.status_code == 200:
                ts_list = r_idx.json().get('timestamps', [])
                if ts_list:
                    # Revisamos los dos últimos archivos por si acabamos de cambiar de semana
                    for ts_id in ts_list[-2:]:
                        r_data = requests.get(f"https://www.smard.de/app/chart_data/411/DE/411_DE_hour_{ts_id}.json", timeout=10)
                        if r_data.status_code == 200:
                            for entry in r_data.json().get('series', []):
                                if entry[1] is None:
                                    continue
                                ts_entry = pd.to_datetime(entry[0], unit='ms', utc=True).strftime('%Y-%m-%d %H:%M')
                                if ts_entry == marca_temporal_str:
                                    demanda_prevision = entry[1]
                                elif ts_entry > marca_temporal_str:
                                    future_previsions[ts_entry] = entry[1]
        except Exception as e:
            print(f"[Error] Fallo al descargar previsión oficial: {e}")

        # Insertar registro actual en BD
        row_data = {
            'marca_temporal': marca_temporal_str,
            'demanda_real': demanda_real_target,
            'demanda_prevision': demanda_prevision,
            'prediccion': int(prediccion_hora_h),
            'error_absoluto': int(diferencia) if diferencia is not None else None,
            'error_porc': round(porcentaje, 2) if porcentaje is not None else None,
        }
        row_data.update(diccionario_caracteristicas)
        row_data.update(temps_bd)
        
        insertar_en_bd([row_data])
        
        if future_previsions:
            lista_futuro = [{'marca_temporal': ts, 'demanda_prevision': val} for ts, val in future_previsions.items()]
            insertar_en_bd(lista_futuro)
    except Exception as e:
        print(f"[Error BD] No se pudo guardar en SQLite: {e}")
        
    try:
        from predecir_futuro import obtener_predicciones_futuras
        print("\n[Predict] Calculando predicciones a futuro (multi-horizonte)...")
        
        # Obtener previsiones para las próximas 168 horas
        future_data = obtener_predicciones_futuras(168)
        ts_list = future_data['timestamps']
        preds_list = future_data['predictions']
        
        horizontes = [1, 6, 12, 24, 48, 72, 168]
        
        conn = sqlite3.connect(RUTA_BD, timeout=30.0)
        c = conn.cursor()
        
        for h in horizontes:
            # El índice en la lista es h-1 (ej. 1h está en el índice 0)
            idx = h - 1
            if idx < len(ts_list):
                ts_futuro = ts_list[idx]
                pred_val = int(preds_list[idx])
                col_name = f"prediccion_{h}h"
                
                # Insertar o actualizar la fila correspondiente a ese instante futuro
                query = f'''
                    INSERT INTO datos_alemania (marca_temporal, {col_name})
                    VALUES (?, ?)
                    ON CONFLICT(marca_temporal) DO UPDATE SET
                        {col_name} = excluded.{col_name}
                '''
                c.execute(query, (ts_futuro, pred_val))
                
        conn.commit()
        conn.close()
        print("[BD] Predicciones a múltiples horizontes guardadas correctamente.")
    except Exception as e:
        print(f"[Error Predict] Fallo al generar/guardar previsiones a futuro: {e}")
    
    if train_file:
        print("\n--- Actualización del dataset de entrenamiento ---")
        
        new_row_dict = {'demanda_objetivo': demanda_real_target}
        new_row_dict.update(diccionario_caracteristicas)
        df_new = pd.DataFrame([new_row_dict])
        
        df_new = df_new.round({
            "hora_sin": 4, "hora_cos": 4, 
            "dia_ano_sin": 4, "dia_ano_cos": 4,
            "temp_berlin": 1, "temp_hamburgo": 1, "temp_munich": 1,
            "temp_colonia": 1, "temp_frankfurt": 1, "temp_stuttgart": 1,
            "temp_dusseldorf": 1, "temp_leipzig": 1, "temp_dortmund": 1,
            "temp_essen": 1
        })
        
        append_row = True
        if os.path.exists(train_file):
            try:
                # Leemos la última línea para ver si ya hemos metido estos datos
                with open(train_file, 'r') as f:
                    lines = f.readlines()
                    if len(lines) > 1:
                        last_line = lines[-1].strip().split(',')
                        # Si demanda_objetivo y demanda_t_1 son iguales, asumimos que es el mismo registro
                        if len(last_line) >= 2 and demanda_real_target is not None and demanda_t_1 is not None:
                            if float(last_line[0]) == float(demanda_real_target) and float(last_line[1]) == float(demanda_t_1):
                                append_row = False
            except Exception as e:
                print(f"Aviso: No se pudo verificar el fichero .train: {e}")
                
        if append_row:
            df_new.to_csv(train_file, mode='a', header=not os.path.exists(train_file), index=False)
            print(f"[OK] Nueva fila añadida a {train_file}")
        else:
            print(f"[Aviso] La fila parece estar ya presente en {train_file} (mismo t y t-1). Omitiendo.")


def resumen_bd():
    """Muestra un resumen del estado de la tabla datos_alemania."""
    try:
        conn = sqlite3.connect(RUTA_BD, timeout=30.0)
        c = conn.cursor()
        
        total = c.execute('SELECT COUNT(*) FROM datos_alemania').fetchone()[0]
        sin_prediccion = c.execute('SELECT COUNT(*) FROM datos_alemania WHERE prediccion IS NULL').fetchone()[0]
        sin_temp = c.execute('SELECT COUNT(*) FROM datos_alemania WHERE temp_berlin IS NULL').fetchone()[0]
        sin_prevision = c.execute('SELECT COUNT(*) FROM datos_alemania WHERE demanda_prevision IS NULL').fetchone()[0]
        
        rango = c.execute('SELECT MIN(marca_temporal), MAX(marca_temporal) FROM datos_alemania').fetchone()
        
        conn.close()
        
        print("\n" + "=" * 50)
        print("RESUMEN DE LA BASE DE DATOS (datos_alemania)")
        print("=" * 50)
        print(f"  Registros totales:         {total}")
        if rango[0]:
            print(f"  Rango temporal:            {rango[0]} -> {rango[1]}")
        
        nulos_total = sin_prediccion + sin_temp + sin_prevision
        if nulos_total == 0:
            print(f"  Estado:                    ✓ Completa (sin nulos)")
        else:
            if sin_prediccion > 0:
                print(f"  Sin predicción:            {sin_prediccion}")
            if sin_temp > 0:
                print(f"  Sin temperaturas:          {sin_temp}")
            if sin_prevision > 0:
                print(f"  Sin previsión oficial:     {sin_prevision}")
        print("=" * 50)
    except Exception as e:
        print(f"\n[Aviso] No se pudo consultar la BD: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Descargar datos de demanda de SMARD (Alemania) e insertar en BD.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""Ejemplos de uso:
  # Descargar un año completo
  %(prog)s --year 2023

  # Descargar un rango de fechas
  %(prog)s -f 2023-06-01 -t 2023-06-30

  # Descargar un rango de marcas de tiempo
  %(prog)s -f "2023-12-25 08:00" -t "2023-12-25 20:00"

  # Descargar un solo día (24h)
  %(prog)s -f 2023-12-25

  # Descargar una sola marca de tiempo
  %(prog)s -f "2023-12-25 14:00"

  # Descargar y exportar también a CSV
  %(prog)s --year 2023 --csv

    # Rellenar y completar datos faltantes en la BD (auto-healing)
  %(prog)s --complete
  
  # Modo tiempo real (sin parámetros, opcionalmente con -tr para volcar a dataset de entrenamiento)
  %(prog)s
  %(prog)s -tr dataset.train"""
    )
    
    grupo = parser.add_mutually_exclusive_group(required=False)
    grupo.add_argument("--year", type=int, 
                       help="Año completo a descargar (ej. 2023)")
    grupo.add_argument("-f", "--from", dest="fecha_desde", type=str,
                       help="Fecha o marca de tiempo de inicio.\n"
                            "  Fecha:   YYYY-MM-DD (descarga el día completo si va solo)\n"
                            "  Hora:    'YYYY-MM-DD HH:MM' (descarga esa hora si va solo)")
    grupo.add_argument("--complete", action="store_true", 
                       help="Completar datos faltantes en la BD (rellenar temperaturas nulas y calcular predicciones pendientes).")
    
    parser.add_argument("-t", "--to", dest="fecha_hasta", type=str,
                        help="Fecha o marca de tiempo de fin (mismo formato que -f).\n"
                             "Opcional: si se omite, se usa solo el valor de -f.")
    parser.add_argument("--recent-days", type=int, metavar="N",
                        help="Descargar los últimos N días hasta hoy para rellenar posibles huecos.")
    parser.add_argument("--csv", action="store_true", 
                        help="Exportar también a fichero CSV además de insertar en BD.")
    parser.add_argument("-tr", "--train-file", type=str, default=None, 
                        help="[Modo cron] Ruta al fichero .train al que añadir los datos nuevos.")
    
    args = parser.parse_args()
    
    # Si no se indica ningún modo, ejecutamos como el antiguo cron_predict
    if not (args.year or args.fecha_desde or getattr(args, 'complete', False) or getattr(args, 'recent_days', False)):
        print("Ejecutando en modo cron (tiempo real)...")
        ejecutar_modo_cron(train_file=args.train_file)
        resumen_bd()
        exit(0)
    
    # Modo --complete: solo procesar pendientes, no descargar
    if getattr(args, 'complete', False):
        columnas_api = [
            'demanda_real', 'demanda_prevision', 
            'temp_berlin', 'temp_hamburgo', 'temp_munich', 'temp_colonia', 
            'temp_frankfurt', 'temp_stuttgart', 'temp_dusseldorf', 
            'temp_leipzig', 'temp_dortmund', 'temp_essen'
        ]
        
        try:
            conn = sqlite3.connect(RUTA_BD, timeout=30.0)
            nulos_antes = {col: conn.execute(f"SELECT COUNT(*) FROM datos_alemania WHERE {col} IS NULL").fetchone()[0] for col in columnas_api}
            conn.close()
        except sqlite3.OperationalError:
            nulos_antes = {col: 0 for col in columnas_api}
            
        procesar_predicciones_pendientes()
        
        try:
            conn = sqlite3.connect(RUTA_BD, timeout=30.0)
            nulos_despues = {col: conn.execute(f"SELECT COUNT(*) FROM datos_alemania WHERE {col} IS NULL").fetchone()[0] for col in columnas_api}
            conn.close()
        except sqlite3.OperationalError:
            nulos_despues = {col: 0 for col in columnas_api}
            
        print("\n=== RESUMEN DE AUTO-HEALING (API) ===")
        print(f"{'Columna':<20} | {'Nulos Antes':<12} | {'Nulos Después':<13} | {'Mejora':<10}")
        print("-" * 64)
        for col in columnas_api:
            mejora = nulos_antes[col] - nulos_despues[col]
            signo = "+" if mejora > 0 else ""
            print(f"{col:<20} | {nulos_antes[col]:<12} | {nulos_despues[col]:<13} | {signo}{mejora:<9}")
        print("================================================================\n")
        
        resumen_bd()
        exit(0)
    
    dt_inicio, dt_fin = parsear_rango(args)
    
    # --- Pre-check: ¿ya tenemos estos datos en la BD? ---
    # marca_temporal se almacena en UTC, así que comparamos en UTC.
    inicio_str = dt_inicio.astimezone(tz_utc).strftime('%Y-%m-%d %H:%M')
    fin_str = dt_fin.astimezone(tz_utc).strftime('%Y-%m-%d %H:%M')
    
    # Calcular cuántas horas cubre el rango solicitado
    horas_esperadas = int((dt_fin - dt_inicio).total_seconds() / 3600) + 1
    
    try:
        conn = sqlite3.connect(RUTA_BD, timeout=30.0)
        c = conn.cursor()
        
        existentes = c.execute(
            'SELECT COUNT(*) FROM datos_alemania WHERE marca_temporal >= ? AND marca_temporal <= ?',
            (inicio_str, fin_str)
        ).fetchone()[0]
        
        completos = c.execute(
            'SELECT COUNT(*) FROM datos_alemania WHERE marca_temporal >= ? AND marca_temporal <= ? AND prediccion IS NOT NULL AND meteo_consolidado = 1',
            (inicio_str, fin_str)
        ).fetchone()[0]
        
        conn.close()
        
        if completos >= horas_esperadas:
            print(f"[OK] El rango {inicio_str} -> {fin_str} ya está completo en la BD ({completos} registros).")
            print("     No es necesario consultar las APIs.")
            resumen_bd()
            exit(0)
        elif existentes > 0:
            faltantes = horas_esperadas - existentes
            incompletos = existentes - completos
            print(f"[Info] Rango {inicio_str} -> {fin_str}: {existentes}/{horas_esperadas} registros ya en BD ({incompletos} incompletos, {faltantes} por descargar).")
        else:
            print(f"[Info] Rango {inicio_str} -> {fin_str}: sin datos previos. Descargando {horas_esperadas} horas...")
    except Exception:
        pass  # Si la BD no existe aún, seguimos adelante
    
    df_final = descargar_smard(dt_inicio, dt_fin)
    
    if df_final is not None and not df_final.empty:
        insertar_en_bd(df_final)
        
        if args.csv:
            inicio_str = dt_inicio.strftime('%Y-%m-%d')
            fin_str = dt_fin.strftime('%Y-%m-%d')
            if inicio_str == fin_str:
                nombre_csv = f"smard_demanda_{inicio_str}.csv"
            else:
                nombre_csv = f"smard_demanda_{inicio_str}_{fin_str}.csv"
            
            df_final.to_csv(nombre_csv, index=True)
            print(f"\n[CSV] Datos exportados a {nombre_csv}")
            
    # Siempre procesamos predicciones pendientes al final por si hay huecos que rellenar
    procesar_predicciones_pendientes()
    
    resumen_bd()
