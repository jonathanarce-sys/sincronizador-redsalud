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
BATCH_SIZE = 3000

# Hojas exactas requeridas de DIPRECA
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

    dataframes = []

    for f in archivos:
        nombre_base = os.path.basename(f)
        nombre_lower = nombre_base.lower()

        # Caso DIPRECA Excel: leer únicamente las 3 pestañas solicitadas
        if "dipreca" in nombre_lower and nombre_lower.endswith((".xlsx", ".xls")):
            print(f"Procesando Excel DIPRECA: {nombre_base}")
            xl = pd.ExcelFile(f)
            hojas_disponibles = xl.sheet_names

            for h_req in HOJAS_DIPRECA:
                h_real = next((s for s in hojas_disponibles if s.strip().lower() == h_req.strip().lower()), None)
                if h_real:
                    print(f"  -> Extrayendo hoja: '{h_real}'...")
                    df = pd.read_excel(xl, sheet_name=h_real, dtype=object)
                    df["ORIGEN_CONVENIO"] = f"DIPRECA_{h_real}"
                    dataframes.append(df)
                    print(f"     OK: {len(df)} filas extraídas de '{h_real}'.")
                else:
                    print(f"  -> AVISO: Pestaña '{h_req}' no encontrada.")

        # Demás archivos (ARMADA, Maestro, etc.)
        else:
            print(f"Procesando archivo: {nombre_base}")
            if nombre_lower.endswith(".csv"):
                try:
                    df = pd.read_csv(f, sep=None, engine="python", encoding="utf-8", dtype=object)
                except Exception:
                    df = pd.read_csv(f, sep=None, engine="python", encoding="latin1", dtype=object)
            else:
                df = pd.read_excel(f, dtype=object)

            etiqueta = os.path.splitext(nombre_base)[0]
            df["ORIGEN_CONVENIO"] = etiqueta
            dataframes.append(df)
            print(f"  OK: {len(df)} filas extraídas de '{nombre_base}'.")

    if not dataframes:
        print("No se extrajeron registros.")
        return

    # Unificación y alineación de columnas de todos los orígenes
    df_consolidado = pd.concat(dataframes, ignore_index=True)
    df_consolidado = df_consolidado.fillna("")

    encabezados = [str(c) for c in df_consolidado.columns.tolist()]
    filas_sanitizadas = []
    for fila in df_consolidado.values.tolist():
        filas_sanitizadas.append([limpiar_celda(c) for c in fila])

    matriz_completa = [encabezados] + filas_sanitizadas
    total_filas = len(matriz_completa)
    total_cols = len(encabezados)
    col_fin = gspread.utils.rowcol_to_a1(1, total_cols).replace("1", "")

    # Limpieza total de la pestaña para iniciar desde cero
    print(f"Limpiando hoja '{ws.title}' para carga limpia desde celda A1...")
    ws.clear()

    # Redimensionar la hoja para alojar el consolidado
    if ws.row_count < total_filas:
        ws.add_rows(total_filas - ws.row_count + 100)

    print(f"Insertando {
