#!/usr/bin/env python3
import json
import lightgbm as lgb
import argparse
import sys

import os
from dotenv import load_dotenv
load_dotenv()
RUTA_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse_node(node, lines, nombre_caracteristicas, current_depth=0, max_depth=None):
    """
    Parsea recursivamente los nodos del árbol de LightGBM para construir las conexiones de Mermaid.
    """
    if max_depth is not None and current_depth >= max_depth and 'split_index' in node:
        node_id = f"T{node['split_index']}_{current_depth}"
        lines.append(f'    {node_id}(["...<br><i>(Rama truncada)</i>"])')
        return node_id

    if 'leaf_index' in node:
        leaf_id = f"L{node['leaf_index']}"
        leaf_value = round(node['leaf_value'], 2)
        lines.append(f'    {leaf_id}(["Hoja {node["leaf_index"]}<br><b>{leaf_value} MW</b>"])')
        return leaf_id

    node_id = f"N{node['split_index']}"
    
    feature_idx = node['split_feature']
    nombre_caracteristica = nombre_caracteristicas[feature_idx] if nombre_caracteristicas and feature_idx < len(nombre_caracteristicas) else f"Column_{feature_idx}"
    
    threshold = round(node['threshold'], 4)
    
    lines.append(f'    {node_id}{{"{nombre_caracteristica}<br>&le; {threshold}"}}')

    left_child = parse_node(node['left_child'], lines, nombre_caracteristicas, current_depth + 1, max_depth)
    lines.append(f'    {node_id} -->|Sí| {left_child}')

    right_child = parse_node(node['right_child'], lines, nombre_caracteristicas, current_depth + 1, max_depth)
    lines.append(f'    {node_id} -->|No| {right_child}')

    return node_id

def lgb_to_mermaid(model_file, tree_index=0, max_depth=None, wrap_markdown=False):
    bst = lgb.Booster(model_file=model_file)
    model_json = bst.dump_model()
    
    if tree_index >= len(model_json['tree_info']):
        raise ValueError(f"El modelo solo contiene {len(model_json['tree_info'])} árboles. El índice {tree_index} no existe.")

    tree_structure = model_json['tree_info'][tree_index]['tree_structure']

    mermaid_lines = []
    if wrap_markdown:
        mermaid_lines.append("```mermaid")
        
    mermaid_lines.extend([
        "graph LR",
        "    %% Definición de estilos de nodos",
        "    classDef default fill:#f7fafc,stroke:#cbd5e0,stroke-width:1px,color:#2d3748;",
        "    classDef leaf fill:#e6fffa,stroke:#b2f5ea,stroke-width:2px,color:#234e52;"
    ])

    nombre_caracteristicas = bst.feature_name()
    parse_node(tree_structure, mermaid_lines, nombre_caracteristicas, 0, max_depth)

    mermaid_lines.append("    class L* leaf;")
    if wrap_markdown:
        mermaid_lines.append("```")

    return "\n".join(mermaid_lines)

def parse_node_ascii(node, nombre_caracteristicas, prefix="", is_last=True, current_depth=0, max_depth=None):
    """
    Imprime el árbol de LightGBM en formato ASCII directamente en la consola.
    """
    branch = "\\-- " if is_last else "|-- "
    
    if max_depth is not None and current_depth >= max_depth and 'split_index' in node:
        print(f"{prefix}{branch}[...] (Truncado)")
        return

    if 'leaf_index' in node:
        val = round(node['leaf_value'], 2)
        print(f"{prefix}{branch}🍃 Hoja {node['leaf_index']}: {val} MW")
        return

    feature_idx = node['split_feature']
    feat = nombre_caracteristicas[feature_idx] if nombre_caracteristicas and feature_idx < len(nombre_caracteristicas) else f"Col_{feature_idx}"
    thresh = round(node['threshold'], 4)
    print(f"{prefix}{branch}🔹 {feat} <= {thresh}")
    
    new_prefix = prefix + ("    " if is_last else "│   ")
    
    parse_node_ascii(node['left_child'], nombre_caracteristicas, new_prefix, False, current_depth + 1, max_depth)
    parse_node_ascii(node['right_child'], nombre_caracteristicas, new_prefix, True, current_depth + 1, max_depth)

def lgb_to_ascii(model_file, tree_index=0, max_depth=None):
    bst = lgb.Booster(model_file=model_file)
    model_json = bst.dump_model()
    
    if tree_index >= len(model_json['tree_info']):
        raise ValueError(f"El modelo solo contiene {len(model_json['tree_info'])} árboles.")

    tree_structure = model_json['tree_info'][tree_index]['tree_structure']
    nombre_caracteristicas = bst.feature_name()
    
    print(f"\n🌳 ÁRBOL DE DECISIÓN {tree_index} 🌳\n")
    parse_node_ascii(tree_structure, nombre_caracteristicas, "", True, 0, max_depth)
    print("\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Conversor de árboles de LightGBM a diagramas.")
    parser.add_argument("-m", "--model", type=str, default=os.path.join(RUTA_BASE, "modelos/LightGBM_model.txt"), help="Ruta al archivo del modelo LightGBM")
    parser.add_argument("-t", "--tree", type=int, default=0, help="Índice del árbol que se desea visualizar (Por defecto: 0, el primer árbol)")
    parser.add_argument("-d", "--depth", type=int, default=3, help="Profundidad máxima a renderizar para evitar que el gráfico sea gigante (Por defecto: 3)")
    parser.add_argument("--ascii", action="store_true", help="Imprimir el árbol en formato ASCII nativo para la consola en lugar de generar código Mermaid")
    parser.add_argument("--md", action="store_true", help="Envolver la salida en un bloque de código Markdown (```mermaid)")
    parser.add_argument("-o", "--output", type=str, default=None, help="Archivo de salida (opcional). Si no se especifica, se imprime por consola.")
    args = parser.parse_args()

    try:
        original_stdout = sys.stdout
        if args.output:
            sys.stdout = open(args.output, 'w')
            
        if args.ascii:
            lgb_to_ascii(args.model, args.tree, args.depth)
        else:
            codigo_mermaid = lgb_to_mermaid(args.model, args.tree, args.depth, args.md)
            print(f"\n%% CÓDIGO MERMAID GENERADO PARA EL ÁRBOL {args.tree} %%\n")
            print(codigo_mermaid)
            
        if args.output:
            sys.stdout.close()
            sys.stdout = original_stdout
            print(f"Resultado guardado exitosamente en: {args.output}")
            
    except Exception as e:
        if args.output and not sys.stdout.closed:
            sys.stdout.close()
            sys.stdout = original_stdout
        print(f"Error en la conversión: {e}")
