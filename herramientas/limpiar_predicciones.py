import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'bases_de_datos', 'demanda_energia.db')

def limpiar_predicciones():
    print(f"Conectando a la base de datos: {DB_PATH}")
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        cursor = conn.cursor()
        
        query = """
        UPDATE datos_alemania 
        SET prediccion = NULL,
            error_absoluto = NULL,
            error_porc = NULL,
            prediccion_1h = NULL,
            prediccion_6h = NULL,
            prediccion_12h = NULL,
            prediccion_24h = NULL,
            prediccion_48h = NULL,
            prediccion_72h = NULL,
            prediccion_168h = NULL;
        """
        
        cursor.execute(query)
        filas_afectadas = cursor.rowcount
        conn.commit()
        
        print(f"Predicciones eliminadas correctamente. Filas afectadas: {filas_afectadas}")
    except sqlite3.Error as e:
        print(f"Error al limpiar las predicciones: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    limpiar_predicciones()
