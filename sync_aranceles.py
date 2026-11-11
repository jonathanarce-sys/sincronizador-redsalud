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
    """Garantiza compatibilidad estricta con JSON eliminando cualquier NaN, Inf o Timestamp."""
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
        raise ValueError(f"No se encontró la hoja '{HOJA_DESTINO}'.")

    print(f"Pestaña identificada con éxito: '{ws.title}'")

    patron = os.path.join(CARPETA_RAW, "*")
    archivos = [f for f in glob.glob(patron) if not os.path.basename(f).startswith(".")]
    print(f"Archivos encontrados para ingesta: {[os.path.basename(x) for x in archivos]}")

    if not archivos:
        print("No se encontraron archivos en data/raw para anexar.")
        return

    registros = []
    max_cols = 0

    for f in archivos:
