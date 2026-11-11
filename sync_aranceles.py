import os
import glob
import json
import base64
import math
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID_MAESTRA = "1qxeY4CQN-g-bHqbfEpr2MjQXzObpNG5fSxThqexbXHo"
HOJA_DESTINO = "RAW_DATA_INGESTA"
CARPETA_RAW = "data/raw"
FILA_INICIO = 19019
BATCH_SIZE = 3000

# Hojas exactas que se procesarán del archivo DIPRECA
HOJAS_DIPRECA = ["2026_Prestaciones", "2026_Paquetes", "2026_HMQ"]

def obtener_cliente_gspread():
    posibles = ["GCP_SA_KEY", "GCP_JSON_BASE64", "GCP_SERVICE_ACCOUNT", "GOOGLE_CREDENTIALS", "GCP_JSON"]
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

def limpiar_celda(v):
    if v is None:
        return ""
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return ""
    if isinstance(v, (pd.Timestamp, pd.DatetimeIndex)):
        return v.strftime("%d-%m-%Y")
    txt = str(v).strip()
    if txt.lower() in ("nan", "nat", "none", "<na>", "inf", "-inf"):
        return ""
    return txt

def sincronizar_aranceles():
    print("Conectando con Google Sheets...")
    client = obtener_cliente_gspread()
    ss = client.open_by_key(SPREADSHEET_ID_MAESTRA)
    
    ws = None
    objetivo = HOJA_DESTINO.strip().lower()
    for w in ss.worksheets():
        if w.title.strip().lower() == objetivo:
            ws = w
            break

    if not ws:
        raise ValueError(f"No se encontro la hoja '{HOJA_DESTINO}'.")

    print(f"Pestaña identificada con exito: '{ws.title}'")

    patron = os.path.join(CARPETA_RAW, "*")
    archivos = [f for f in glob.glob(patron) if not os.path.basename(f).startswith(".")]
    print(f"Archivos encontrados en data/raw: {[os.path.basename(x) for x in archivos]}")

    if not archivos:
        print("No hay archivos en data/raw para procesar.")
        return

    registros = []
    max_cols = 0

    for f in archivos:
        nombre_base = os.path.basename(f)
        nombre_lower = nombre_base.lower()

        # Caso DIPRECA Excel: extrae exclusivamente las 3 hojas solicitadas
        if "dipreca" in nombre_lower and nombre_lower.endswith((".xlsx", ".xls")):
            print(f"Procesando libro Excel de DIPRECA: {nombre_base}")
            xl = pd.ExcelFile(f)
            hojas_disponibles = xl.sheet_names
            print(f"  Pestañas detectadas en el libro: {hojas_disponibles}")

            for h_req in HOJAS_DIPRECA:
                h_real = next((s for s in hojas_disponibles if s.strip().lower() == h_req.strip().lower()), None)
                if h_real:
                    print(f"  -> Extrayendo datos de la pestaña '{h_real}'...")
                    df = pd.read_excel(xl, sheet_name=h_real, dtype=object)
                    
                    for fila in df.values.tolist():
                        fila_limpia = [limpiar_celda(c) for c in fila]
                        registros.append(fila_limpia)
                        max_cols = max(max_cols, len(fila_limpia))
                    print(f"     OK: {len(df)} filas extraídas de {h_real}.")
                else:
                    print(f"  -> AVISO: No se encontro la pestaña '{h_req}' en {nombre_base}.")

        # Para los demás archivos (ARMADA, Maestro Aranceles, etc.)
        else:
            print(f"Procesando insumo: {nombre_base}")
            if nombre_lower.endswith(".csv"):
                try:
                    df = pd.read_csv(f, sep=None, engine="python", encoding="utf-8", dtype=object)
                except Exception:
                    df = pd.read_csv(f, sep=None, engine="python", encoding="latin1", dtype=object)
            else:
                df = pd.read_excel(f, dtype=object)

            for fila in df.values.tolist():
                fila_limpia = [limpiar_celda(c) for c in fila]
                registros.append(fila_limpia)
                max_cols = max(max_cols, len(fila_limpia))
            print(f"  OK: {len(df)} filas extraídas de {nombre_base}.")

    if not registros:
        print("No hay registros para anexar.")
        return

    total_filas = len(registros)
    fila_fin = FILA_INICIO + total_filas - 1
    col_fin = gspread.utils.rowcol_to_a1(1, max_cols).replace("1", "")

    # Expandir filas de la hoja si hace falta
    if ws.row_count < fila_fin:
        filas_agregar = (fila_fin - ws.row_count) + 500
        print(f"Expandiendo hoja en {filas_agregar} filas...")
        ws.add_rows(filas_agregar)

    print(f"Insertando {total_filas} filas por lotes desde la fila {FILA_INICIO}...")

    for i in range(0, total_filas, BATCH_SIZE):
        bloque = registros[i:i + BATCH_SIZE]
        f_inicio = FILA_INICIO + i
        f_termino = f_inicio + len(bloque) - 1
        rango_bloque = f"A{f_inicio}:{col_fin}{f_termino}"
        print(f"  Escribiendo bloque: {rango_bloque} ({len(bloque)} registros)...")
        ws.update(range_name=rango_bloque, values=bloque)

    print(f"Exito: Se anexaron {total_filas} filas respetando las 19018 previas.")

if __name__ == "__main__":
    sincronizar_aranceles()
