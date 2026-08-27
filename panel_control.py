#!/usr/bin/env python3
"""Dashboard en tiempo real para visualización de predicciones de demanda eléctrica."""
from flask import Flask, render_template, jsonify, request
import sqlite3
import pandas as pd
import argparse
from predecir_futuro import obtener_predicciones_futuras

import os
from dotenv import load_dotenv
load_dotenv()
RUTA_BASE = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, 
            static_folder=os.path.join(RUTA_BASE, 'static'),
            static_url_path='/static',
            template_folder=os.path.join(RUTA_BASE, 'templates'))

RUTA_BD = os.path.join(RUTA_BASE, "bases_de_datos/demanda_energia.db")

PAST_HOURS = int(os.getenv("PAST_HOURS", 24))
FUTURE_HOURS = int(os.getenv("FUTURE_HOURS", 12))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/demanda')
def get_demanda():
    try:
        past_hours_req = int(request.args.get('past', PAST_HOURS))
        future_hours_req = int(request.args.get('future', FUTURE_HOURS))
        
        conn = sqlite3.connect(RUTA_BD, timeout=30.0)
        c = conn.cursor()
        
        # Encontrar el "ahora" (último registro con demanda_real)
        c.execute("SELECT MAX(marca_temporal) FROM datos_alemania WHERE demanda_real IS NOT NULL")
        now_ts = c.fetchone()[0]
        
        if not now_ts:
            return jsonify({'error': 'No hay datos reales en la BD'}), 500
            
        # Consultar todo el rango (pasado y futuro)
        query_all = f'''
        SELECT marca_temporal, demanda_real, prediccion, prediccion_1h, prediccion_6h, prediccion_12h, prediccion_24h, prediccion_48h, prediccion_72h, prediccion_168h, demanda_prevision
        FROM datos_alemania 
        WHERE marca_temporal >= datetime('{now_ts}', '-{past_hours_req} hours')
          AND marca_temporal <= datetime('{now_ts}', '+{future_hours_req} hours')
        ORDER BY marca_temporal ASC
        '''
        df_all = pd.read_sql_query(query_all, conn)
        
        all_marca_temporals = df_all['marca_temporal'].tolist()
        real_values = [val if pd.notnull(val) else None for val in df_all['demanda_real']]
        official_line = [val if pd.notnull(val) else None for val in df_all['demanda_prevision']]
        
        horizontes = ['1h', '6h', '12h', '24h', '48h', '72h', '168h']
        pred_lines = {}
        for h in horizontes:
            col = f'prediccion_{h}'
            if col in df_all.columns:
                pred_lines[h] = [val if pd.notnull(val) else None for val in df_all[col]]
            else:
                pred_lines[h] = [None] * len(df_all)
                
        # Fallback para 1h si no existe
        if not any(v is not None for v in pred_lines['1h']):
            pred_lines['1h'] = [val if pd.notnull(val) else None for val in df_all['prediccion']]
            
        # Obtener la Trayectoria Actual (modelo en tiempo real)
        future_data = obtener_predicciones_futuras(future_hours_req)
        future_dict = dict(zip(future_data['timestamps'], future_data['predictions']))
        
        # Inyectar el último dato de la demanda real para conectar visualmente la línea en el gráfico
        ultimo_valor_real = df_all.loc[df_all['marca_temporal'] == now_ts, 'demanda_real'].values[0]
        if pd.notnull(ultimo_valor_real):
            future_dict[now_ts] = float(ultimo_valor_real)
            
        current_trajectory = [future_dict.get(ts) for ts in all_marca_temporals]

        # Determinar estado de las APIs (Semáforos)
        c.execute("SELECT MAX(marca_temporal) FROM datos_alemania WHERE demanda_real IS NOT NULL")
        smard_last = c.fetchone()[0]
        
        c.execute("SELECT MAX(marca_temporal) FROM datos_alemania WHERE temp_berlin IS NOT NULL")
        meteo_last = c.fetchone()[0]
        
        from datetime import datetime, timedelta
        ahora = datetime.utcnow()
        
        import pytz
        tz_utc = pytz.UTC
        tz_berlin = pytz.timezone('Europe/Berlin')

        def to_local_str(ts_str):
            if not ts_str: return "N/A"
            try:
                dt_utc = datetime.strptime(ts_str, "%Y-%m-%d %H:%M").replace(tzinfo=tz_utc)
                return dt_utc.astimezone(tz_berlin).strftime("%Y-%m-%d %H:%M")
            except:
                return ts_str

        # Helper function to check status based on 2 hour threshold
        def get_status(last_ts_str):
            if not last_ts_str:
                return "red", "N/A"
            try:
                last_dt = datetime.strptime(last_ts_str, "%Y-%m-%d %H:%M")
                if ahora - last_dt > timedelta(hours=3):
                    return "red", to_local_str(last_ts_str)
                return "green", to_local_str(last_ts_str)
            except:
                return "red", to_local_str(last_ts_str)

        smard_color, smard_time = get_status(smard_last)
        meteo_color, meteo_time = get_status(meteo_last)

        labels_local = [to_local_str(ts) for ts in all_marca_temporals]

        response = jsonify({
            'labels': labels_local,
            'real': real_values,
            'predicted': pred_lines,
            'official': official_line,
            'current_trajectory': current_trajectory,
            'now_index': sum(1 for v in real_values if v is not None) - 1,
            'api_status': {
                'smard': {'status': smard_color, 'time': smard_time},
                'meteo': {'status': meteo_color, 'time': meteo_time}
            }
        })
        conn.close()
        return response
    except Exception as e:
        return jsonify({'error': str(e)}), 500



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Dashboard en tiempo real")
    parser.add_argument("--from-days", type=int, help="Días de historial a mostrar")
    parser.add_argument("--from-hours", type=int, help="Horas de historial a mostrar")
    parser.add_argument("--to-days", type=int, help="Días de previsión a mostrar")
    parser.add_argument("--to-hours", type=int, help="Horas de previsión a mostrar")
    args = parser.parse_args()
    
    if args.from_days:
        PAST_HOURS = args.from_days * 24
    elif args.from_hours:
        PAST_HOURS = args.from_hours
        
    if args.to_days:
        FUTURE_HOURS = args.to_days * 24
    elif args.to_hours:
        FUTURE_HOURS = args.to_hours


    app.run(host='0.0.0.0', port=5000, debug=True)

