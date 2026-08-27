#!/usr/bin/env python3
"""
Script de migración para rellenar huecos (datos faltantes de SMARD y Open-Meteo)
en la base de datos actual a partir de los registros de la base de datos antigua.
Solo rellena valores nulos (NULL) y añade filas que no existan.
"""
import sqlite3
import os
import sys

# Rutas de las bases de datos
RUTA_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA_BD_ACTUAL = os.path.join(RUTA_BASE, "bases_de_datos/demanda_energia.db")
RUTA_BD_ANTIGUA = os.path.join(RUTA_BASE, "bases_de_datos/demanda_energia_old.db")

def main():
    if not os.path.exists(RUTA_BD_ANTIGUA):
        print(f"Error: No se encuentra la base de datos antigua en {RUTA_BD_ANTIGUA}")
        sys.exit(1)
        
    if not os.path.exists(RUTA_BD_ACTUAL):
        print(f"Error: No se encuentra la base de datos actual en {RUTA_BD_ACTUAL}")
        sys.exit(1)

    print(f"Abriendo BD antigua: {RUTA_BD_ANTIGUA}")
    conn_old = sqlite3.connect(RUTA_BD_ANTIGUA, timeout=30.0)
    conn_old.row_factory = sqlite3.Row
    
    print(f"Abriendo BD actual:  {RUTA_BD_ACTUAL}")
    conn_new = sqlite3.connect(RUTA_BD_ACTUAL, timeout=30.0)
    
    # Obtener nombres de columnas de la BD antigua
    c_old = conn_old.cursor()
    try:
        c_old.execute("SELECT * FROM datos_alemania LIMIT 1")
    except sqlite3.OperationalError:
        print("Error: La tabla 'datos_alemania' no existe en la BD antigua.")
        sys.exit(1)
        
    columnas_old = [description[0] for description in c_old.description]
    
    # Obtener nombres de columnas de la BD actual
    c_new = conn_new.cursor()
    try:
        c_new.execute("SELECT * FROM datos_alemania LIMIT 1")
    except sqlite3.OperationalError:
        print("Error: La tabla 'datos_alemania' no existe en la BD actual.")
        sys.exit(1)
        
    columnas_new = [description[0] for description in c_new.description]
    
    # Solo podemos migrar las columnas que existen en ambas bases de datos
    columnas_comunes = [col for col in columnas_old if col in columnas_new]
    
    if 'marca_temporal' not in columnas_comunes:
        print("Error crítico: 'marca_temporal' no está en las columnas comunes.")
        sys.exit(1)

    print(f"Columnas a migrar ({len(columnas_comunes)}): {', '.join(columnas_comunes)}")
    
    # Construir query de UPSERT
    # El COALESCE prioriza el dato de la BD ACTUAL (datos_alemania.col). Si es NULL, usa el de la BD ANTIGUA (excluded.col)
    cols_sql = ", ".join(columnas_comunes)
    placeholders = ", ".join(["?"] * len(columnas_comunes))
    updates = ", ".join([f"{col} = COALESCE(datos_alemania.{col}, excluded.{col})" for col in columnas_comunes if col != 'marca_temporal'])
    
    query_upsert = f'''
        INSERT INTO datos_alemania ({cols_sql})
        VALUES ({placeholders})
        ON CONFLICT(marca_temporal) DO UPDATE SET 
            {updates}
    '''
    
    print("\nIniciando volcado de datos...")
    
    # Procesar en bloques para no saturar memoria
    OFFSET = 0
    LIMIT = 10000
    total_migrados = 0
    
    while True:
        c_old.execute(f"SELECT {cols_sql} FROM datos_alemania ORDER BY marca_temporal LIMIT ? OFFSET ?", (LIMIT, OFFSET))
        filas = c_old.fetchall()
        
        if not filas:
            break
            
        # Convertir a lista de tuplas para execute_many
        datos_insertar = [tuple(fila) for fila in filas]
        
        c_new.executemany(query_upsert, datos_insertar)
        conn_new.commit()
        
        total_migrados += len(filas)
        print(f"Procesados {total_migrados} registros...")
        OFFSET += LIMIT

    conn_old.close()
    
    print("\n--- Estado final de nulos en BD actual ---")
    columnas_api = [
        'demanda_real', 'demanda_prevision', 
        'temp_berlin', 'temp_hamburgo', 'temp_munich', 'temp_colonia',
        'temp_frankfurt', 'temp_stuttgart', 'temp_dusseldorf',
        'temp_leipzig', 'temp_dortmund', 'temp_essen'
    ]
    
    for col in columnas_api:
        if col in columnas_new:
            c_new.execute(f"SELECT COUNT(*) FROM datos_alemania WHERE {col} IS NULL")
            nulos = c_new.fetchone()[0]
            print(f"  {col:<20}: {nulos} nulos")
            
    conn_new.close()
    
    print("\n¡Migración completada con éxito!")
    print(f"Se procesaron {total_migrados} registros en total desde la BD antigua y se rellenaron los huecos (NULLs) de la actual.")

if __name__ == "__main__":
    main()
