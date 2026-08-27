#!/usr/bin/env python3
"""Evaluación de predicciones multi-horizonte sobre muestras aleatorias del dataset."""

import pandas as pd
import numpy as np
import lightgbm as lgb
import argparse
import random
import os
import sqlite3
from dotenv import load_dotenv

load_dotenv()
RUTA_BASE = os.path.dirname(os.path.abspath(__file__))

parser = argparse.ArgumentParser(
    description="Predictor aleatorio de demanda (Multi-Horizonte y Recursivo).",
    formatter_class=argparse.RawTextHelpFormatter,
    epilog="""Ejemplos de uso:
  # Generar 3 evaluaciones aleatorias (por defecto)
  ./predecir_aleatorio.py
  
  # Generar 10 evaluaciones aleatorias
  ./predecir_aleatorio.py -n 10
"""
)
parser.add_argument("-n", "--number-of-predictions", type=int, default=3, help="Número de muestras aleatorias a evaluar")
parser.add_argument("-f", "--file", type=str, default="train/germany-last-year.train", help="Fichero .train a cargar")
args = parser.parse_args()

model_file = os.path.join(RUTA_BASE, "modelos/LightGBM_model.txt")
try:
    bst = lgb.Booster(model_file=model_file)
except Exception as e:
    print(f"Error cargando el modelo: {e}")
    exit(1)

train_file = args.file
try:
    df_train = pd.read_csv(train_file)
except Exception as e:
    print(f"Error cargando el archivo de datos: {e}")
    exit(1)

try:
    conn = sqlite3.connect(os.path.join(RUTA_BASE, "bases_de_datos/demanda_energia.db"))
    df_map = pd.read_sql_query("SELECT marca_temporal, demanda_real FROM datos_alemania WHERE demanda_real IS NOT NULL", conn)
    conn.close()
except Exception as e:
    print(f"Aviso: No se pudo cargar el mapa de fechas de la BD: {e}")
    df_map = pd.DataFrame(columns=['marca_temporal', 'demanda_real'])

# Función de simulación recursiva
def simulate_horizon(df, bst, target_idx, H):
    """
    Simula una predicción de horizonte 'H' para el índice 'target_idx'.
    Retrocede H-1 pasos (start_idx = target_idx - H + 1) y predice iterativamente 
    hasta el target_idx, usando sus propias predicciones como lags.
    """
    start_idx = target_idx - H + 1
    predicciones = []
    
    col_lag_24 = 'demanda_t_24h' if 'demanda_t_24h' in df.columns else 'demanda_t_24'
    features_modelo = bst.feature_name()
    
    for i in range(start_idx, target_idx + 1):
        fila = df.iloc[i].copy()
        
        # Sobrescribir inercia a muy corto plazo
        if i > start_idx:
            fila['demanda_t_1'] = predicciones[-1]
            
        # Sobrescribir inercia diaria si el horizonte es mayor o igual a 24h
        if len(predicciones) >= 24:
            fila[col_lag_24] = predicciones[-24]
            
        X_instante = pd.DataFrame([fila], columns=df.columns)[features_modelo]
        pred_val = int(np.floor(bst.predict(X_instante)[0]))
        predicciones.append(pred_val)
        
    return predicciones[-1]

N = args.number_of_predictions
horizontes = [1, 6, 12, 24, 48, 72, 168]
max_horizon = max(horizontes)

if len(df_train) <= max_horizon:
    print(f"Error: El dataset es demasiado pequeño ({len(df_train)} filas) para horizontes de {max_horizon}h.")
    exit(1)

indices_aleatorios = random.sample(range(max_horizon, len(df_train)), N)
indices_aleatorios.sort()

print("\n" + "="*80)
print(f"  EVALUACIÓN MULTI-HORIZONTE")
print(f"  Simulación recursiva de {N} muestras para horizontes de 1h a 168h")
print("="*80)

resultados_globales = {h: {'errores_abs': [], 'porcentajes': []} for h in horizontes}

for idx in indices_aleatorios:
    fila_target = df_train.iloc[idx]
    demanda_real = int(fila_target['demanda_target'])
    
    matches = df_map[np.isclose(df_map['demanda_real'], fila_target['demanda_target'], atol=1e-3)]
    if not matches.empty:
        fecha_str = matches.iloc[0]['marca_temporal']
    else:
        fecha_str = f"Índice {idx}"

    dias = {1: "Lun", 2: "Mar", 3: "Mié", 4: "Jue", 5: "Vie", 6: "Sáb", 7: "Dom"}
    dia_texto = dias.get(int(fila_target['dia_semana']), "???")
    festivo = "Sí" if fila_target.get('es_festivo', 0) == 1 else "No"
    
    print(f"\n[{fecha_str}] | Día: {dia_texto} | Festivo: {festivo}")
    print(f"   >>> DEMANDA REAL: {demanda_real} MW")
    print(f"   -------------------------------------------------")
    
    for h in horizontes:
        pred_val = simulate_horizon(df_train, bst, idx, h)
        error = abs(demanda_real - pred_val)
        porcentaje = (error / demanda_real) * 100 if demanda_real > 0 else 0
        
        resultados_globales[h]['errores_abs'].append(error)
        resultados_globales[h]['porcentajes'].append(porcentaje)
        
        print(f"   Horizonte {h:3d}h -> PRED: {pred_val} MW | Error: {error:4d} MW ({porcentaje:5.2f}%)")

print("\n" + "="*80)
print("  RESUMEN DE MÉTRICAS (PROMEDIOS DE LA MUESTRA)")
print("="*80)

for h in horizontes:
    mae = np.mean(resultados_globales[h]['errores_abs'])
    rmse = np.sqrt(np.mean(np.array(resultados_globales[h]['errores_abs'])**2))
    mape = np.mean(resultados_globales[h]['porcentajes'])
    print(f"  >>> Horizonte {h:3d}h | MAE: {mae:7.1f} MW | RMSE: {rmse:7.1f} MW | MAPE: {mape:5.2f}%")

print("\n" + "="*80 + "\n")
