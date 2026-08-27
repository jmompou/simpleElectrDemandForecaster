# Diccionario de Datos: Tabla `datos_alemania`

Este documento describe la estructura y significado de todos los campos que componen la tabla principal `datos_alemania` almacenada en la base de datos SQLite (`bases_de_datos/demanda_energia.db`).

La tabla centraliza tanto la información histórica de consumos, las predicciones del modelo en tiempo real y diferido, como las características ambientales y cronológicas (features) que alimentan al modelo de Inteligencia Artificial (LightGBM).

## Identificadores y Control
- **`marca_temporal` (DATETIME - PRIMARY KEY)**: Instante de tiempo al que hace referencia el registro. Se almacena **siempre en UTC** con formato `%Y-%m-%d %H:%M` para evitar problemas con el horario de verano (DST) o cambios de zona horaria.
- **`creado_el` (DATETIME)**: Fecha y hora exacta (timestamp automático) en la que el registro fue insertado físicamente por primera vez en la base de datos.
- **`smard_consolidado` (INTEGER)**: Bandera (flag) booleana (0 o 1). Indica si el dato de demanda es definitivo y consolidado (descargado de archivos históricos masivos de SMARD) en lugar de ser un valor parcial de ingesta en tiempo real.
- **`meteo_consolidado` (INTEGER)**: Bandera booleana (0 o 1). Indica si el registro tiene todas sus características meteorológicas y predictivas validadas y procesadas por el modelo local.

## Valores Energéticos (Megavatios - MW)
- **`demanda_real` (REAL)**: Consumo eléctrico real registrado oficialmente para esa hora. Actúa como nuestra variable objetivo ("target" o "Y").
- **`demanda_prevision` (REAL)**: Previsión de demanda oficial provista anticipadamente por la agencia gubernamental (SMARD). Sirve como *benchmark* (línea base) para comparar la calidad de nuestro modelo.
- **`prediccion` (REAL)**: Valor de demanda inferido en tiempo real por el modelo `LightGBM` (para `t=0`). 
- **`error_absoluto` (REAL)**: Diferencia bruta en MW entre la `demanda_real` y la `prediccion` (`prediccion - demanda_real`).
- **`error_porc` (REAL)**: Diferencia en porcentaje (%) que desvía la predicción de la demanda real.

## Variables Autorregresivas (Lags)
Estos campos introducen memoria y contexto temporal al modelo informándole de lo que pasaba en el sistema eléctrico en momentos inmediatamente anteriores al que queremos predecir.

- **`demanda_t_1` (REAL)**: Demanda real medida hace exactamente 1 hora (`t-1`).
- **`demanda_t_24h` (REAL)**: Demanda real medida hace exactamente 24 horas (`t-24`), captura el patrón diario.

## Características Cronológicas Cíclicas (Time Features)
Las redes y algoritmos de Machine Learning no entienden los "días" o "meses" de forma secuencial bruta (porque el día 31 no está "más lejos" del 1 que el 30). Se usan transformaciones de senos y cosenos para emular la naturaleza circular de un reloj o de las estaciones climáticas.

- **`hora_sin` (REAL)** / **`hora_cos` (REAL)**: Representación trigonométrica de la hora del día (0-23) para que el modelo entienda que las 23:00 está igual de cerca de las 00:00 que de las 22:00.
- **`dia_ano_sin` (REAL)** / **`dia_ano_cos` (REAL)**: Representación trigonométrica del día del año (1-365 o 366). Capta los ciclos de estacionalidad anual (verano vs invierno).
- **`dia_semana` (INTEGER)**: Día de la semana (1 = Lunes, 7 = Domingo).
- **`es_festivo` (INTEGER)**: Bandera booleana (0 o 1) generada usando el calendario oficial alemán. Avisa al modelo de alteraciones severas de la demanda por vacaciones.

## Variables Meteorológicas (Open-Meteo)
Temperaturas ambientales en grados Celsius (°C) a 2 metros de altura sobre el suelo de las principales urbes alemanas. La calefacción y el aire acondicionado impactan fuertemente en el modelo.

- **`temp_berlin` (REAL)**
- **`temp_hamburgo` (REAL)**
- **`temp_munich` (REAL)**
- **`temp_colonia` (REAL)**
- **`temp_frankfurt` (REAL)**
- **`temp_stuttgart` (REAL)**
- **`temp_dusseldorf` (REAL)**
- **`temp_leipzig` (REAL)**
- **`temp_dortmund` (REAL)**
- **`temp_essen` (REAL)**

## Predicciones a Futuro (Multi-Horizonte)
A diferencia del campo `prediccion` (que es el pronóstico a corto plazo que se retroalimenta), estos campos se llenan calculando trayectorias predictivas a ciegas (el modelo predice y se traga sus propias predicciones como `t-1` para seguir adivinando más lejos).

- **`prediccion_1h` a `prediccion_168h` (REAL)**: Demanda esperada calculada para horizontes proyectados de 1, 6, 12, 24, 48, 72 horas y hasta 1 semana (168 horas) en el futuro.
