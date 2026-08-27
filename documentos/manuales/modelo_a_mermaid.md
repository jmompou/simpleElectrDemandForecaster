# modelo_a_mermaid.py

## Propósito
Herramienta de depuración y visualización que toma un modelo entrenado de LightGBM y convierte uno de sus árboles de decisión en un diagrama visual o estructurado. Permite entender las reglas lógicas y las divisiones internas que utiliza el modelo para tomar decisiones.

## Algoritmos
- **Parseo Recursivo de Árboles (DFS)**: Recorre la estructura en árbol JSON exportada por LightGBM desde la raíz hasta las hojas (profundidad primero).
- **Generación de Gráficos (Transpilador)**: Traduce los nodos, reglas y hojas a la sintaxis declarativa de diagramas de Mermaid o a un formato de texto ASCII (para visualizar por terminal).

## APIs / Módulos
- **LightGBM**: Para cargar el modelo binario/texto (`bst.dump_model()`) y extraer su topología de árboles.
- **JSON**: Para interactuar con el formato estructurado del modelo de LightGBM.
- **Argparse**: Opciones de CLI para seleccionar el índice del árbol (`-t`), su profundidad máxima (`-d`) y el formato de salida (ASCII vs Mermaid).

## Flujo de Procesamiento de Datos
1. **Extracción**: Carga el fichero del modelo (`LightGBM_model.txt`) y usa la API de LightGBM para volcarlo a un diccionario JSON.
2. **Navegación**: Según el índice de árbol solicitado, navega por el diccionario `tree_info`.
3. **Traducción**:
   - Para **Mermaid**: Genera nodos de estilo condicional (`{condición}`) y flechas direccionales (`-->|Sí|`), y dibuja con bordes redondeados las hojas finales con el valor predecido en MW.
   - Para **ASCII**: Usa caracteres Unicode especiales para dibujar el árbol directamente en la consola (`├──`, `└──`).

## Salida
- Texto plano que puede copiarse y pegarse en un intérprete de Markdown (Mermaid).
- Gráfico imprimido en la terminal (modo ASCII).
