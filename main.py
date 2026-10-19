import os
import json
import base64
import sys
import time
import requests
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek"
LICITALAB_API_KEY = os.getenv("LICITALAB_API_KEY", "llab_live_kxaJvD38lM1h8Qj11SVe6P18cZ-nEp2lMsECS5_THoE").strip()

def log(msg):
    print(msg, flush=True)

def obtener_credenciales_google():
    log("🔑 Cargando credenciales de Google...")
    gcp_secret = os.getenv("GCP_JSON_BASE64", "").strip() or os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip()

    if not gcp_secret:
        raise ValueError("❌ No se encontraron credenciales en las variables de entorno.")

    try:
        creds_dict = json.loads(gcp_secret, strict=False)
    except Exception:
        try:
            missing_padding = len(gcp_secret) % 4
            if missing_padding != 0:
                gcp_secret += '=' * (4 - missing_padding)
            json_bytes = base64.b64decode(gcp_secret)
            creds_dict = json.loads(json_bytes.decode("utf-8"))
        except Exception as e:
            raise ValueError(f"❌ Error al decodificar credenciales: {e}")

    if "private_key" in creds_dict:
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    return Credentials.from_service_account_info(creds_dict, scopes=scopes)

def clasificar_tipo(tipo_raw, code_raw):
    code_upper = str(code_raw).upper()
    tipo_upper = str(tipo_raw).upper()

    if "COT" in code_upper or "AGILE" in tipo_upper or "COMPRA ÁGIL" in tipo_upper:
        return "Compra Ágil"
    elif "CO" in code_upper or "PRIVATE" in tipo_upper:
        return "Licitación Privada"
    return "Licitación Pública"

def formatear_fecha(val_fecha):
    if not val_fecha or str(val_fecha).upper() in ["NONE", "NULL", "NAN", ""]:
        return ""
    val_str = str(val_fecha).strip()
    return val_str.split("T")[0] if "T" in val_str else val_str

def formatear_moneda(val):
    if val is None or val == "" or str(val).upper() == "NONE":
        return "$ 0"
    try:
        monto = int(float(val))
        return f"$ {monto:,}".replace(",", ".")
    except:
        return str(val)

def descargar_oportunidades_licitalab():
    """Descarga los registros en vivo desde LicitaLAB BI API usando las claves mapeadas de la API."""
    url_base = "https://biapi.licitalab.cl/bi/v2/opportunities"
    headers = {
        "x-api-key": LICITALAB_API_KEY,
        "Accept": "application/json"
    }

    log(f"🌐 Consultando API de LicitaLAB BI ({url_base})...")
    
    page = 1
    max_pages = 20
    todos_los_items = []

    while page <= max_pages:
        url = f"{url_base}?page={page}"
        try:
            res = requests.get(url, headers=headers, timeout=30)
            if res.status_code == 200:
                data = res.json()
                items = data.get("data", data) if isinstance(data, dict) else data
                
                if not isinstance(items, list) or len(items) == 0:
                    log(f"Página {page} vacía. Fin de la descarga de datos.")
                    break
                
                todos_los_items.extend(items)
                page += 1
                time.sleep(0.3)
            else:
                log(f"⚠️ API retorno HTTP {res.status_code} en página {page}")
                break
        except Exception as e:
            log(f"⚠️ Error al conectar con LicitaLAB en página {page}: {e}")
            break

    log(f"✅ Se obtuvieron {len(todos_los_items)} oportunidades en vivo desde LicitaLAB.")
    return todos_los_items

def procesar_items_api(items):
    """Procesa los ítems JSON extrayendo WORKSPACE_TITLE, CLOSING_DATE, ORGANISM, etc."""
    filas = []
    
    for item in items:
        # 1. Workspace real
        workspace = str(item.get("WORKSPACE_TITLE") or item.get("workspace_title") or item.get("WORKSPACE") or "CENTRO DE DIAGNOSTICO CLINICA MAGALLANES SPA").strip()
        
        # 2. Código Proceso
        codigo = str(item.get("OPPORTUNITY_CODE") or item.get("opportunity_code") or "").strip()
        
        # 3. Fecha Publicación
        fecha_pub = formatear_fecha(item.get("PUBLISH_DATE") or item.get("CREATED_AT") or item.get("created_at"))
        
        # 4. Fecha de Cierre real
        fecha_cierre = formatear_fecha(item.get("CLOSING_DATE") or item.get("closing_date") or item.get("EXPIRATION_DATE"))
        
        # 5. Tipo Proceso
        tipo_orig = str(item.get("OPPORTUNITY_TYPE") or item.get("opportunity_type") or "").strip()
        tipo = clasificar_tipo(tipo_orig, codigo)
        
        # 6. Institución Compradora real
        comprador = str(item.get("ORGANISM") or item.get("organism") or item.get("BUYER_NAME") or "").strip()
        
        # 7. Nombre Proceso
        nombre = str(item.get("OPPORTUNITY_NAME") or item.get("opportunity_name") or "").strip()
        
        # 8. Prestación
        prestacion = str(item.get("ORGANISM_CATEGORY") or item.get("B_LINE_TITLE") or "").strip(" []'\"")
        
        # 9. Montos
        monto_neto = item.get("APPLIED_AMOUNT") or item.get("AVAILABLE_AMOUNT")
        monto_total_iva = formatear_moneda(monto_neto)
        
        # 10. Estado
        estado = str(item.get("OPPORTUNITY_STATUS") or item.get("MANAGED_STATUS_NAME") or "").strip()
        
        # 11. Comentarios
        comentarios = str(item.get("COMMENTS") or item.get("comments") or "").strip(" []'\"")

        filas.append([
            workspace,          # Columna A: Workspace
            codigo,             # Columna B: Código Proceso
            fecha_pub,          # Columna C: Fecha Publicación
            fecha_cierre,       # Columna D: Fecha de Cierre
            tipo,               # Columna E: Tipo Proceso
            comprador,          # Columna F: Institución Compradora
            nombre,             # Columna G: Nombre Proceso
            prestacion,         # Columna H: Prestación (Categoría RedSalud)
            monto_total_iva,    # Columna I: Monto Total + IVA
            estado,             # Columna J: Estado de la Oferta
            comentarios         # Columna K: Comentarios
        ])

    df = pd.DataFrame(filas, columns=[
        "Workspace", "Código Proceso", "Fecha Publicación", "Fecha de Cierre",
        "Tipo Proceso", "Institución Compradora", "Nombre Proceso",
        "Prestación (Categoría RedSalud)", "Monto Total + IVA (Adjudicado / Estimado)",
        "Estado de la Oferta", "Comentarios"
    ])

    # Filtrar solo del año 2025 en adelante
    if "Fecha Publicación" in df.columns:
        df["_year"] = pd.to_datetime(df["Fecha Publicación"], errors="coerce").dt.year
        df = df[df["_year"] >= 2025].drop(columns=["_year"], errors="ignore")

    return df

def sincronizar():
    log("🔄 Iniciando sincronización de Base Maestra desde LicitaLAB BI API...")
    creds = obtener_credenciales_google()
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1

    # 1. Obtener los ítems en vivo desde la API de LicitaLAB BI
    items_api = descargar_oportunidades_licitalab()

    if items_api:
        df_final = procesar_items_api(items_api)
        log(f"📊 Registros procesados (Año 2025+): {len(df_final)}")

        log("🧹 Limpiando la planilla Google Sheets...")
        sheet.clear()

        log("📝 Escribiendo datos reales de Workspace, Fecha de Cierre e Institución Compradora...")
        valores = [df_final.columns.tolist()] + df_final.fillna("").astype(str).values.tolist()
        sheet.update(range_name="A1", values=valores)

        log("🚀 ¡Sincronización completada con éxito en Google Sheets!")
    else:
        log("⚠️ No se pudieron obtener datos desde la API. Revisa la conectividad.")

if __name__ == "__main__":
    sincronizar()
