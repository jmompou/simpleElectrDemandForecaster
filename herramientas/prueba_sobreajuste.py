#!/usr/bin/env python3
import sys
import os
import subprocess
import re
import shutil

import argparse

def main():
    parser = argparse.ArgumentParser(description="Prueba de sobreajuste para modelo LightGBM.")
    parser.add_argument("train_file", help="Ruta al fichero .train original")
    parser.add_argument("--val-ratio", type=float, default=20.0, help="Porcentaje de datos para validacion (ej. 20 para 20 por ciento). Por defecto: 20 por ciento.")
    
    args = parser.parse_args()
    input_train_file = args.train_file
    
    if not os.path.exists(input_train_file):
        print(f"Error: No se encuentra el archivo {input_train_file}")
        sys.exit(1)

    if not input_train_file.endswith('.train') and not input_train_file.endswith('.csv'):
        print(f"Error: Se esperaba un archivo de datos (.train o .csv), pero se proporcionó '{input_train_file}'. Asegúrate de no estar pasando el archivo del modelo compilado.")
        sys.exit(1)

    print("=== Paso 1: Segmentar los datos en el disco ===")
    base_name = os.path.basename(input_train_file).replace('.train', '')
    train_split_file = f"train/{base_name}_train_split.train"
    valid_split_file = f"train/{base_name}_valid_split.valid"

    with open(input_train_file, 'r') as f:
        lines = f.readlines()

    if len(lines) == 0:
        print("El archivo está vacío.")
        sys.exit(1)

    header = lines[0]
    data_lines = lines[1:]
    total_data = len(data_lines)
    
    # Calcular split basado en el parámetro
    ratio_val = args.val_ratio / 100.0
    split_index = int(total_data * (1.0 - ratio_val))
    
    train_lines = data_lines[:split_index]
    valid_lines = data_lines[split_index:]

    with open(train_split_file, 'w') as f:
        f.write(header)
        f.writelines(train_lines)

    with open(valid_split_file, 'w') as f:
        f.write(header)
        f.writelines(valid_lines)

    train_pct = (1.0 - ratio_val) * 100
    val_pct = ratio_val * 100
    print(f"Datos segmentados cronológicamente:")
    print(f" - Entrenamiento ({train_pct:.1f}%): {train_split_file} ({len(train_lines)} registros)")
    print(f" - Validación ({val_pct:.1f}%): {valid_split_file} ({len(valid_lines)} registros)\n")

    print("=== Paso 2: Configurar train.conf para la auditoría ===")
    base_conf = "conf/train.conf"
    audit_conf = "conf/overfitting_train.conf"
    
    if not os.path.exists(base_conf):
        print(f"Error: No se encuentra el archivo de configuración {base_conf}")
        sys.exit(1)

    with open(base_conf, 'r') as f:
        conf_content = f.read()

    conf_content = re.sub(r'^data\s*=.*', f'data = {train_split_file}', conf_content, flags=re.MULTILINE)
    
    if 'valid =' in conf_content or 'valid_data =' in conf_content:
        conf_content = re.sub(r'^#?\s*valid(_data)?\s*=.*', f'valid = {valid_split_file}', conf_content, flags=re.MULTILINE)
    else:
        conf_content += f"\nvalid = {valid_split_file}\n"
    
    conf_content = re.sub(r'^metric_freq\s*=.*', 'metric_freq = 50', conf_content, flags=re.MULTILINE)
    conf_content = re.sub(r'^is_training_metric\s*=.*', 'is_training_metric = true', conf_content, flags=re.MULTILINE)
    
    conf_content = re.sub(r'^output_model\s*=.*', 'output_model = modelos/LightGBM_model_overfitting_test.txt', conf_content, flags=re.MULTILINE)

    with open(audit_conf, 'w') as f:
        f.write(conf_content)

    print(f"Configuración de auditoría guardada en {audit_conf}\n")

    print("=== Paso 3: Interpretar la salida de la terminal ===")
    print("Ejecutando entrenamiento... (esto puede tardar unos minutos)\n")

    ruta_lightgbm = os.getenv("RUTA_LIGHTGBM") or shutil.which("lightgbm")
    if not ruta_lightgbm:
        print("Error: No se encuentra el ejecutable lightgbm. Configura RUTA_LIGHTGBM en .env.")
        sys.exit(1)
    cmd = [ruta_lightgbm, f"config={audit_conf}"]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    min_valid_loss = float('inf')
    best_iteration = 0
    overfitting_detected = False
    consecutive_increases = 0

    train_regex = re.compile(r'Iteration:(\d+),\s*training\s*l2\s*:\s*([\d\.e\+\-]+)')
    valid_regex = re.compile(r'Iteration:(\d+),\s*valid_1\s*l2\s*:\s*([\d\.e\+\-]+)')

    current_iteration = 0

    for line in process.stdout:
        if "No further splits with positive gain" in line or "seconds elapsed, finished iteration" in line:
            continue
        
        print(line.strip())
        
        match_train = train_regex.search(line)
        if match_train:
            current_iteration = int(match_train.group(1))
            continue
            
        match_valid = valid_regex.search(line)
        if match_valid:
            iteration = int(match_valid.group(1))
            valid_loss = float(match_valid.group(2))

            if iteration == current_iteration:
                if valid_loss < min_valid_loss:
                    min_valid_loss = valid_loss
                    best_iteration = iteration
                    consecutive_increases = 0
                else:
                    consecutive_increases += 1

                if consecutive_increases >= 2 and not overfitting_detected:
                    overfitting_detected = True
                    print(f"\n[!] ALERTA: valid_1's l2 empieza a subir de nuevo.")
                    print(f"[!] CONFIRMADO: Overfitting activo. Tu mínimo de validación fue en el árbol ~{best_iteration}.\n")

    process.wait()

    print("\n=== CONCLUSIÓN Y POSIBLES MEJORAS ===")
    if overfitting_detected:
        print(f"La auditoría CONFIRMA que estás sobreajustando los datos. El mínimo global de validación se alcanzó en el árbol {best_iteration}.")
    else:
        print("La auditoría NO muestra señales claras de overfitting, o no se entrenó lo suficiente para observarlo.")

    print("\nSi detectas que estás sobreajustando los datos, tienes tres palancas de ingeniería directa en tu train.conf para embridar el algoritmo sin alterar la estructura de tus scripts:")
    print("\n1. Activar early_stopping_round: Añade la línea `early_stopping_round = 50`. Si el error de validación pasa 50 árboles seguidos sin mejorar, LightGBM detendrá el entrenamiento en seco de forma automática y guardará los pesos del árbol óptimo (p. ej., en la iteración 1,200), ignorando el resto de árboles sobreajustados.")
    print("\n2. Aumentar min_data_in_leaf: Actualmente lo tienes fijado en 500 (o 40 en tu conf actual). Si detectas overfitting, elévalo a 800 o 1000. Esto obligará a que los nodos finales requieran más volumen de datos para tomar una decisión, destruyendo las micro-reglas memorizadas.")
    print("\n3. Reducir feature_fraction: Cambia `feature_fraction = 1.0` por `0.8`. Al hacerlo, cada árbol individual tendrá prohibido ver el 20% de las columnas de forma aleatoria en cada iteración. Si el modelo dependía de forma enfermiza del lag t-1 para memorizar, esta restricción le obligará a buscar patrones alternativos en el clima o las variables cíclicas, aumentando drásticamente su robustez general.")

if __name__ == "__main__":
    main()
