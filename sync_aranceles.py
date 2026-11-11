import os
import glob
import pandas as pd
import openpyxl

ARCHIVO_MAESTRO = "Base_Maestra_Aranceles.xlsx"  # Nombre de tu archivo consolidado existente
HOJA_DESTINO = "Aranceles"                        # Nombre exacto de la pestaña a la que agregas la data
CARPETA_NUEVOS = "data/nuevos_aranceles"          # Carpeta donde subes el nuevo archivo
FILA_INICIO = 19019                               # Celda exacta donde debe comenzar

def anexar_data():
    if not os.path.exists(ARCHIVO_MAESTRO):
        raise FileNotFoundError(f"No se encontró el archivo maestro base: {ARCHIVO_MAESTRO}")

    # 1. Identificar el nuevo archivo subido
    nuevos = glob.glob(os.path.join(CARPETA_NUEVOS, "*.xls*")) + glob.glob(os.path.join(CARPETA_NUEVOS, "*.csv"))
    if not nuevos:
        print("No se encontraron archivos nuevos para anexar.")
        return
    
    archivo_nuevo = nuevos[0]
    print(f"Leyendo nuevo archivo: {archivo_nuevo}")

    # 2. Cargar los datos nuevos (omitiendo cabeceras si solo viene la data)
    try:
        df_nuevo = pd.read_html(archivo_nuevo)[0]
    except Exception:
        if archivo_nuevo.endswith(".csv"):
            df_nuevo = pd.read_csv(archivo_nuevo)
        else:
            df_nuevo = pd.read_excel(archivo_nuevo)

    print(f"Registros nuevos a incorporar: {len(df_nuevo)} filas")

    # 3. Cargar la hoja existente SIN borrar su contenido
    wb = openpyxl.load_workbook(ARCHIVO_MAESTRO)
    if HOJA_DESTINO not in wb.sheetnames:
        ws = wb.create_sheet(HOJA_DESTINO)
    else:
        ws = wb[HOJA_DESTINO]

    # 4. Escribir exactamente a partir de la fila 19019
    fila_actual = FILA_INICIO
    for _, fila in df_nuevo.iterrows():
        for col_idx, valor in enumerate(fila, start=1):
            # Limpiar valores nulos / NaN
            val = "" if pd.isna(valor) else valor
            ws.cell(row=fila_actual, column=col_idx, value=val)
        fila_actual += 1

    wb.save(ARCHIVO_MAESTRO)
    print(f"Éxito: Se anexaron {len(df_nuevo)} filas desde la fila {FILA_INICIO} hasta la {fila_actual - 1}.")

if __name__ == "__main__":
    anexar_data()
