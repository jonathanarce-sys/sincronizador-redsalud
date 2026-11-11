import os
import glob
import json
import base64
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

# ID extraído directamente de tu URL
SPREADSHEET_ID_MAESTRA = "1qxeY4CQN-g-bHqbfEpr2MjQXzObpNG5fSxThqexbXHo"
HOJA_DESTINO = "RAW_DATA_INGESTA"
CARPETA_RAW = "data/raw"
FILA_INICIO = 19019  # Celda exacta donde se anexa la nueva información sin borrar 1:19018

def obtener_cliente_gspread():
    posibles = [
        "GCP_SA_KEY",
        "GCP_JSON_BASE64",
        "GCP_SERVICE_ACCOUNT",
        "GOOGLE_CREDENTIALS",
        "GCP_JSON"
    ]
    val = None
    for k in posibles:
        if k in os.environ and os.environ[k].strip():
            val = os.environ[k].strip()
            break
            
    if not val:
        raise ValueError("No se encontraron credenciales de Google Cloud en GitHub Secrets.")

    try:
        pad = len(val) % 4
        if pad:
            val += "=" * (4 - pad)
        creds_dict = json.loads(base64.b64decode(val).decode("utf-8"))
    except Exception:
        creds_dict = json.loads(val)

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    return gspread.authorize(Credentials.from_service_account_info(creds_dict, scopes=scopes))

def sincronizar_aranceles():
    print("Conectando con Google Sheets...")
    client = obtener_cliente_gspread()
    ss = client.open_by_key(SPREADSHEET_ID_MAESTRA)
    
    # 1. Búsqueda tolerante de la pestaña (ignora mayúsculas/minúsculas y espacios accidentales)
    hojas_disponibles = [w.title for w in ss.worksheets()]
    print(f"Pestañas encontradas en el documento: {hojas_disponibles}")
    
    ws = None
    objetivo = HOJA_DESTINO.strip().lower()
    for w in ss.worksheets():
        if w.title.strip().lower() == objetivo:
            ws = w
            break

    if not ws:
        raise ValueError(
            f"No se encontró la hoja '{HOJA_DESTINO}'. "
            f"Pestañas detectadas en el archivo: {hojas_disponibles}"
        )

    print(f"Pestaña identificada con éxito: '{ws.title}'")

    # 2. Localizar archivos nuevos en data/raw (ignorando archivos ocultos como .gitkeep)
    patron = os.path.join(CARPETA_RAW, "*")
    archivos = [f for f in glob.glob(patron) if not os.path.basename(f).startswith(".")]
    print(f"Archivos encontrados para ingesta: {[os.path.basename(x) for x in archivos]}")

    if not archivos:
        print("No se encontraron archivos en data/raw para anexar.")
        return

    registros = []
    for f in archivos:
        print(f"Leyendo: {os.path.basename(f)}")
        # Carga tolerante de CSV y Excel
        if f.lower().endswith(".csv"):
            try:
                df = pd.read_csv(f, sep=None, engine="python", encoding="utf-8")
            except Exception:
                df = pd.read_csv(f, sep=None, engine="python", encoding="latin1")
        else:
            df = pd.read_excel(f)

        df = df.fillna("")
        datos = df.values.tolist()
        registros.extend(datos)
        print(f" -> {len(datos)} filas extraídas de {os.path.basename(f)}")

    if not registros:
        print("No hay filas con datos para anexar.")
        return

    # 3. Calcular dimensiones exactas para anexar
    total_filas = len(registros)
    fila_fin = FILA_INICIO + total_filas - 1
    total_cols = len(registros[0])
    col_fin = gspread.utils.rowcol_to_a1(1, total_cols).replace("1", "")

    # Expandir filas de la hoja si hace falta
    if ws.row_count < fila_fin:
        ws.add_rows(fila_fin - ws.row_count + 100)

    # 4. Actualizar únicamente el rango desde FILA_INICIO (A19019 hacia abajo)
    rango_actualizar = f"A{FILA_INICIO}:{col_fin}{fila_fin}"
    print(f"Insertando {total_filas} filas en el rango {rango_actualizar}...")
    
    ws.update(range_name=rango_actualizar, values=registros)
    print(f"Proceso finalizado con éxito. Se anexaron datos de la fila {FILA_INICIO} a la {fila_fin} sin tocar las 19.018 anteriores.")

if __name__ == "__main__":
    sincronizar_aranceles()
