import os
import json
import base64
import sys
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek"

def log(msg):
    print(msg, flush=True)

def obtener_credenciales_google():
    log("🔑 Cargando credenciales de Google...")
    creds_dict = None
    gcp_b64 = os.getenv("GCP_JSON_BASE64", "").strip()
    
    if gcp_b64:
        missing_padding = len(gcp_b64) % 4
        if missing_padding != 0:
            gcp_b64 += '=' * (4 - missing_padding)
            
        try:
            json_bytes = base64.b64decode(gcp_b64)
            creds_dict = json.loads(json_bytes.decode("utf-8"))
        except Exception:
            try:
                creds_dict = json.loads(gcp_b64, strict=False)
            except Exception as e:
                raise ValueError(f"No se pudo interpretar GCP_JSON_BASE64: {e}")

    if not creds_dict and os.getenv("GOOGLE_CREDENTIALS_JSON"):
        raw_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
        creds_dict = json.loads(raw_json, strict=False)

    if not creds_dict:
        raise ValueError("❌ No se encontraron credenciales en las variables de entorno.")

    if "private_key" in creds_dict:
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    return Credentials.from_service_account_info(creds_dict, scopes=scopes)

def sincronizar():
    log("🔄 Iniciando proceso de sincronización...")
    creds = obtener_credenciales_google()
    client = gspread.authorize(creds)
    
    log(f"📄 Abriendo la Base Maestra en Google Sheets...")
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1

    raw_records = sheet.get_all_records()
    df = pd.DataFrame(raw_records)

    if df.empty:
        log("⚠️ La planilla está vacía o no tiene registros.")
        return

    log(f"📊 Registros leídos de la planilla: {len(df)}")

    # 1. Eliminar columnas 'Criterios de Evaluación' y 'Puntajes'
    cols_eliminar = [c for c in df.columns if "criterio" in c.lower() or "evaluaci" in c.lower() or "puntaje" in c.lower()]
    if cols_eliminar:
        log(f"🗑️ Eliminando columnas antiguas: {cols_eliminar}")
        df = df.drop(columns=cols_eliminar, errors="ignore")

    # 2. Filtrar fechas del 2025 en adelante
    col_inicio = next((c for c in df.columns if "inicio" in c.lower() or "publica" in c.lower() or "creaci" in c.lower()), None)
    if col_inicio:
        df[col_inicio] = pd.to_datetime(df[col_inicio], errors="coerce", dayfirst=True)
        df = df[df[col_inicio].dt.year >= 2025]
        df[col_inicio] = df[col_inicio].dt.strftime("%Y-%m-%d")
        log(f"📅 Registros filtrados (Año 2025+): {len(df)}")

    # 3. Incorporar nuevas columnas requeridas
    if "Comentarios" not in df.columns:
        df["Comentarios"] = ""

    col_monto = next((c for c in df.columns if "monto" in c.lower() or "estimado" in c.lower() or "total" in c.lower()), None)
    def calc_iva(val):
        try:
            v = float(str(val).replace("$", "").replace(".", "").replace(",", ".").strip())
            return f"$ {int(v * 1.19):,}".replace(",", ".")
        except Exception:
            return "$ 0"

    if col_monto:
        df["Monto Total + IVA (Adjudicado / Estimado)"] = df[col_monto].apply(calc_iva)

    # 4. Sobrescribir en Google Sheets
    log("🧹 Reestructurando y limpiando la hoja...")
    sheet.clear()

    log("📝 Escribiendo los datos actualizados y nuevos encabezados...")
    valores = [df.columns.tolist()] + df.fillna("").astype(str).values.tolist()
    sheet.update(range_name="A1", values=valores)

    log("🚀 ¡Sincronización completada con éxito en Google Sheets!")

# Llamada explícita de ejecución
if __name__ == "__main__":
    sincronizar()
