#!/usr/bin/env python3
import sqlite3
import pandas as pd
import os

RUTA_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA_BD = os.path.join(RUTA_BASE, "bases_de_datos/demanda_energia.db")
RUTA_EXCEL = os.path.join(RUTA_BASE, "documentos/exportacion_demanda.xlsx")

def exportar_a_excel():
    print(f"Conectando a la base de datos: {RUTA_BD}")
    try:
        conn = sqlite3.connect(RUTA_BD, timeout=30.0)
        
        query = "SELECT * FROM datos_alemania ORDER BY marca_temporal DESC"
        print("Extrayendo datos...")
        df = pd.read_sql_query(query, conn)
        
        conn.close()
        
        print(f"Exportando {len(df)} registros a Excel...")
        
        os.makedirs(os.path.dirname(RUTA_EXCEL), exist_ok=True)
        
        df.to_excel(RUTA_EXCEL, index=False, engine='openpyxl')
        print(f"¡Éxito! Archivo guardado en: {RUTA_EXCEL}")
        
    except Exception as e:
        print(f"Error durante la exportación: {e}")

if __name__ == "__main__":
    exportar_a_excel()
