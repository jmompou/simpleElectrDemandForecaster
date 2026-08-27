#!/usr/bin/env python3
"""Predicción autorregresiva secuencial para un tramo de horas consecutivas."""

import pandas as pd
import numpy as np
import lightgbm as lgb
import argparse
import random
import sqlite3


import os
from dotenv import load_dotenv
load_dotenv()
RUTA_BASE = os.path.dirname(os.path.abspath(__file__))


parser = argparse.ArgumentParser(
    description="Predicción autorregresiva de un tramo horario.",
    formatter_class=argparse.RawTextHelpFormatter,
    epilog="""Ejemplos de uso:
  # Predecir 24 horas a partir de un punto aleatorio
  ./predecir_tramo.py
  
  # Predecir 48 horas empezando en el índice 1000
  ./predecir_tramo.py --horas 48 --inicio 1000
"""
)
parser.add_argument("-f", "--file", type=str, default="train/germany-last-year.train", help="Fichero .train a cargar")
parser.add_argument("-H", "--horas", type=int, default=24, help="Número de horas consecutivas a simular")
parser.add_argument("-i", "--inicio", type=int, default=-1, help="Índice inicial de la serie (aleatorio por defecto)")
args = parser.parse_args()

# Carga del modelo y datos
try:
    bst = lgb.Booster(model_file=os.path.join(RUTA_BASE, "modelos/LightGBM_model.txt"))
except Exception as e:
    print(f"Error cargando el modelo: {e}")
    exit(1)

try:
    df_train = pd.read_csv(args.file)
except Exception as e:
    print(f"Error cargando el archivo de datos {args.file}: {e}")
    exit(1)

# Ya no adivinamos el año desde el archivo, usaremos el índice de la fila

total_filas = len(df_train)
horas_pred = args.horas

try:
    conn = sqlite3.connect(os.path.join(RUTA_BASE, "bases_de_datos/demanda_energia.db"))
    df_map = pd.read_sql_query("SELECT marca_temporal, demanda_real FROM datos_alemania WHERE demanda_real IS NOT NULL", conn)
    conn.close()
except Exception as e:
    print(f"Aviso: No se pudo cargar el mapa de fechas de la BD: {e}")
    df_map = pd.DataFrame(columns=['marca_temporal', 'demanda_real'])

# Validamos o generamos el índice inicial
inicio = args.inicio
if inicio < 0 or inicio > (total_filas - horas_pred - 1):
    inicio = random.randint(0, total_filas - horas_pred - 1)

print("\n" + "="*80)
print(f" SIMULACIÓN AUTORREGRESIVA DE {horas_pred} HORAS CONSECUTIVAS (Inicio: Índice {inicio})")
print("="*80)

# Extraemos el tramo que vamos a usar de "realidad"
tramo_real = df_train.iloc[inicio : inicio + horas_pred].copy()

# Orden obligatorio de columnas para el modelo
columnas_features = bst.feature_name()
dias_semana_texto = {1: "Lun", 2: "Mar", 3: "Mié", 4: "Jue", 5: "Vie", 6: "Sáb", 7: "Dom"}

predicciones = []
real_demands = []
errores_absolutos = []
ultima_prediccion_t1 = None

for i in range(horas_pred):
    idx_real = inicio + i
    fila_real = tramo_real.iloc[i].copy()
    
    # Autorregresión: Alimentar el modelo con nuestras propias predicciones
    # Si es la primera hora (i=0), usamos la inercia real (demanda_t_1) porque el modelo arranca ahí.
    # Si i > 0, usamos lo que predijimos en el paso anterior.
    if i > 0:
        fila_real['demanda_t_1'] = ultima_prediccion_t1
        
    # Si el horizonte supera las 24h, t-24h también debe ser una predicción antigua
    if i >= 24:
        fila_real['demanda_t_24h'] = predicciones[i - 24]
        
    # Formatear la entrada para LightGBM
    X_instante = pd.DataFrame([fila_real], columns=df_train.columns)
    X_instante = X_instante[columnas_features]
    
    # Realizar la predicción
    pred_val = bst.predict(X_instante)[0]
    pred_val = int(np.floor(pred_val))
    
    # Guardamos el resultado para el siguiente ciclo
    ultima_prediccion_t1 = pred_val
    predicciones.append(pred_val)
    
    # Evaluación de rendimiento
    demanda_real = int(fila_real['demanda_target'])
    real_demands.append(demanda_real)
    error_abs = abs(demanda_real - pred_val)
    errores_absolutos.append(error_abs)
    
    demanda_target_val = fila_real['demanda_target']
    matches = df_map[np.isclose(df_map['demanda_real'], demanda_target_val, atol=1e-3)]
    if not matches.empty:
        fecha_str = matches.iloc[0]['marca_temporal']
    else:
        fecha_str = f"Índice {idx_real}"
        
    dia_txt = dias_semana_texto.get(int(fila_real['dia_semana']), "???")
    
    ciudades = ['berlin', 'hamburg', 'munich', 'cologne', 'frankfurt', 'stuttgart', 'dusseldorf', 'leipzig', 'dortmund', 'essen']
    temps = [fila_real.get(f'temp_{c}', 0) for c in ciudades]
    t_str = ",".join(f"{t:.1f}" for t in temps)
    
    festivo = "FEST" if fila_real.get('es_festivo', 0) == 1 else "LAB"
    t1 = int(fila_real.get('demanda_t_1', 0))
    t24 = int(fila_real.get('demanda_t_24h', fila_real.get('demanda_t_24', 0)))
    porcentaje_err = (error_abs / demanda_real) * 100
    
    print(f"[{fecha_str}] ({dia_txt} | {festivo}) | Lags(t-1: {t1}, t-24: {t24}) | TºC: ({t_str})")
    print(f"  >>> Real: {demanda_real:5d} MW  |  Pred: {pred_val:5d} MW  |  Err: {error_abs:4d} MW ({porcentaje_err:5.2f}%)")
    print("-" * 80)

print("\n" + "="*80)
print(f"  RESUMEN DE PREDICCIÓN AUTORREGRESIVA DE {horas_pred} HORAS")
print("="*80)
mae = np.mean(errores_absolutos)
max_err = np.max(errores_absolutos)
rmse = np.sqrt(np.mean(np.array(errores_absolutos)**2))
mape = np.mean(np.array(errores_absolutos) / np.array(real_demands)) * 100

print(f"  >>> Error Absoluto Medio (MAE): {mae:.1f} MW")
print(f"  >>> Error Cuadrático Medio (RMSE): {rmse:.1f} MW")
print(f"  >>> Error Porcentual Medio (MAPE): {mape:.2f}%")
print(f"  >>> Error Máximo en el tramo:   {max_err} MW")

if horas_pred > 1:
    pearson_corr = np.corrcoef(real_demands, predicciones)[0, 1]
    print(f"  >>> Correlación de Pearson (R): {pearson_corr:.6f}")
print("\nNota: El modelo simula la evolución futura usando sus propias predicciones")
print("como inercia para los pasos siguientes, asumiendo un escenario meteorológico dado.\n")
