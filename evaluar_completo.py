#!/usr/bin/env python3
"""
Evaluación multi-horizonte completa.
Periodo: 2023-01-01 → 2026-06-30
Horizontes: h ∈ {1, 6, 12, 24, 48, 72, 168}
Salida: evaluacion_completa.csv  +  evaluacion_resumen.csv
"""

import pandas as pd
import numpy as np
import lightgbm as lgb
import sqlite3
import os
import time

RUTA_BASE   = os.path.dirname(os.path.abspath(__file__))
MODEL_FILE  = os.path.join(RUTA_BASE, 'modelos/LightGBM_model.txt')
DB_FILE     = os.path.join(RUTA_BASE, 'bases_de_datos/demanda_energia.db')
OUTPUT_CSV  = os.path.join(RUTA_BASE, 'evaluacion_completa.csv')
RESUMEN_CSV = os.path.join(RUTA_BASE, 'evaluacion_resumen.csv')

HORIZONTES = [1, 6, 12, 24, 48, 72, 168]

def main():
    # ── 1. Modelo ────────────────────────────────────────────────
    print("Cargando modelo...")
    bst      = lgb.Booster(model_file=MODEL_FILE)
    features = bst.feature_name()
    lag1_idx  = features.index('demanda_t_1')
    lag24_idx = features.index('demanda_t_24h')

    # ── 2. Datos de la BD ────────────────────────────────────────
    print("Extrayendo datos (2023-01-01 → 2026-06-30)...")
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    df = pd.read_sql_query('''
        SELECT marca_temporal,
               demanda_real      AS demanda_target,
               demanda_t_1, demanda_t_24h,
               hora_sin, hora_cos, dia_ano_sin, dia_ano_cos,
               dia_semana, es_festivo,
               temp_berlin, temp_hamburgo, temp_munich, temp_colonia,
               temp_frankfurt, temp_stuttgart, temp_dusseldorf,
               temp_leipzig, temp_dortmund, temp_essen
        FROM datos_alemania
        WHERE marca_temporal >= '2023-01-01 00:00'
          AND marca_temporal <= '2026-06-30 23:59'
          AND demanda_real   IS NOT NULL
          AND demanda_t_1    IS NOT NULL
          AND demanda_t_24h  IS NOT NULL
        ORDER BY marca_temporal ASC
    ''', conn)
    conn.close()

    n = len(df)
    print(f"Observaciones: {n:,}")

    y      = df['demanda_target'].values
    df_arr = df[features].values.astype(np.float64)

    # ── 3. Evaluación por horizonte ──────────────────────────────
    out = pd.DataFrame({
        'marca_temporal': df['marca_temporal'].values,
        'demanda_real':   y,
    })

    summary = []

    for H in HORIZONTES:
        t0    = time.time()
        n_seq = n - H + 1       # secuencias completas disponibles
        print(f"\nh = {H:3d}h  ({n_seq:,} secuencias) ...", end='', flush=True)

        # pred_buf[j, s] = predicción en el paso s de la secuencia j
        pred_buf = np.empty((n_seq, H), dtype=np.float64)

        for s in range(H):
            rows  = np.arange(n_seq) + s
            batch = df_arr[rows].copy()

            # Autorregresión: reemplazar lags con predicciones propias
            if s > 0:
                batch[:, lag1_idx]  = pred_buf[:, s - 1]
            if s >= 24:
                batch[:, lag24_idx] = pred_buf[:, s - 24]

            pred_buf[:, s] = bst.predict(batch)

        final_preds = pred_buf[:, H - 1]

        # Alinear al índice original (primeras H-1 filas no tienen predicción completa)
        col = np.full(n, np.nan)
        col[H - 1:] = final_preds

        err     = np.abs(y - col)
        err_pct = err / y * 100

        out[f'pred_h{H}']    = col
        out[f'err_abs_h{H}'] = np.where(np.isnan(col), np.nan, err)
        out[f'err_pct_h{H}'] = np.where(np.isnan(col), np.nan, err_pct)

        valid = ~np.isnan(col)
        mae   = float(np.mean(err[valid]))
        mape  = float(np.mean(err_pct[valid]))
        elapsed = time.time() - t0

        print(f"  MAE = {mae:,.1f} MW | MAPE = {mape:.3f}%  [{elapsed:.1f}s]")
        summary.append({'horizonte_h': H, 'n_obs': int(valid.sum()),
                        'MAE_MW': round(mae, 1), 'MAPE_pct': round(mape, 3)})

    # ── 4. Guardar ───────────────────────────────────────────────
    print(f"\nGuardando {OUTPUT_CSV} ...")
    out.to_csv(OUTPUT_CSV, index=False)

    df_sum = pd.DataFrame(summary)
    df_sum.to_csv(RESUMEN_CSV, index=False)

    # ── 5. Resumen en pantalla ───────────────────────────────────
    print("\n" + "=" * 58)
    print(f"  {'h':>5} | {'n_obs':>7} | {'MAE (MW)':>11} | {'MAPE (%)':>10}")
    print("-" * 58)
    for r in summary:
        print(f"  {r['horizonte_h']:>4}h | {r['n_obs']:>7,} | "
              f"{r['MAE_MW']:>11,.1f} | {r['MAPE_pct']:>10.3f}")
    print("=" * 58)
    print(f"\nFicheros generados:")
    print(f"  {OUTPUT_CSV}  ({n:,} filas)")
    print(f"  {RESUMEN_CSV}")

if __name__ == '__main__':
    main()
