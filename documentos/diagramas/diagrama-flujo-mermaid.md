```mermaid
graph TD
    %% Estilos corporativos y de arquitectura
    classDef cron fill:#ebf8ff,stroke:#bee3f8,stroke-width:2px,color:#2c5282,stroke-dasharray: 5 5;
    classDef database fill:#fefcbf,stroke:#faf089,stroke-width:2px,color:#744210;
    classDef script fill:#f7fafc,stroke:#cbd5e0,stroke-width:2px,color:#2d3748;
    classDef ml fill:#e6fffa,stroke:#b2f5ea,stroke-width:2px,color:#234e52;
    classDef frontend fill:#f0fff4,stroke:#c6f6d5,stroke-width:2px,color:#22543d;

    subgraph "Sistema de Automatización en Segundo Plano (CRON)"
        C1([Minuto 30 de cada hora]):::cron
        C2([Todos los días a las 2:00 AM]):::cron
        C3([Domingos a las 3:00 AM]):::cron
    end

    subgraph "Capa de Ingesta y Datos (ETL)"
        E1["adquirir_datos.py<br>Actualización Incremental Rápida"]:::script
        E2["adquirir_datos.py --recent-days 7<br>Consolidación y Corrección de Huecos"]:::script
        API_SMARD(("API Pública<br>SMARD/REE")):::script
        API_METEO(("API Meteostat<br>Clima 10 Ciudades")):::script
        
        C1 -->|Ejecuta| E1
        C2 -->|Ejecuta| E2
        E1 -->|Consulta Demanda| API_SMARD
        E1 -->|Consulta Clima| API_METEO
        E2 -->|Descarga Demanda| API_SMARD
        E2 -->|Descarga Clima| API_METEO
    end

    DB[("Base de Datos SQLite<br>Única Fuente de la Verdad")]:::database
    API_SMARD -->|Merge e Inserción| DB
    API_METEO -->|Merge e Inserción| DB

    subgraph "Pipeline de Re-entrenamiento Autónomo"
        T1["construir_modelo.py<br>Extracción de Matriz Formateada"]:::script
        T2("germany-last-year.train<br>Matriz de 12 Meses"):::database
        T3["entrenar.sh / LightGBM<br>Entrenamiento C++"]:::ml
        T4("LightGBM_model.txt<br>Pesos Optimizados"):::ml
        
        C3 -->|1. Lanza| T1
        T1 -->|Lee Histórico| DB
        T1 -->|Vuelca| T2
        T2 -->|2. Introduce| T3
        T3 -->|Sobrescribe| T4
    end

    subgraph "Auditoría y Control de Calidad"
        A1["herramientas/prueba_sobreajuste.py<br>Segmentación y Auditoría"]:::script
        T2 -.->|Input Ciego| A1
        A1 -.->|Sugerencia Ajustes| T3
    end

    subgraph "Explotación en Tiempo Real"
        F1["panel_control.py<br>Servidor Web Flask"]:::frontend
        F2["predecir_tramo.py<br>Motor de Inferencia al Vuelo"]:::ml
        F3(["Panel de Control Web<br>Visualización Gráfica"]):::frontend
        
        DB -->|Carga de Series Recientes| F1
        T4 -.->|Lectura de Pesos| F2
        F1 <-->|Consulta Futuro| F2
        F1 -->|Renderizado Web| F3
    end
