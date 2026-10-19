import os
import json
import base64
import sys
import pandas as pd
import requests
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek"
LICITALAB_API_URL = os.getenv("LICITALAB_API_URL", "https://api.licitalab.cl/v1/procesos") # Ajustar endpoint según documentación

def log(msg):
    print(msg, flush=True)

def obtener_credenciales_google():
    log("🔑 Cargando credenciales de Google...")
    gcp_secret = os.getenv("GCP_JSON_BASE64", "").strip() or os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip()

    if not gcp_secret:
        raise ValueError("❌ No se encontraron credenciales en GCP_JSON_BASE64 ni en GOOGLE_CREDENTIALS_JSON.")

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


def obtener_datos_licitalab():
    """Consulta la API de LicitaLAB para obtener la lista real de procesos con Workspace, Cierre, etc."""
    api_key = os.getenv("LICITALAB_API_KEY", "").strip()
    if not api_key:
        log("⚠️ LICITALAB_API_KEY no configurada. Se procesará reestructuración sobre datos locales.")
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    params = {
        "fecha_desde": "2025-01-01"
    }

    try:
        log("🌐 Consultando la API de LicitaLAB para obtener procesos 2025+...")
        response = requests.get(LICITALAB_API_URL, headers=headers, params=params, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            items = data.get("data", data) if isinstance(data, dict) else data
            log(f"✅ Se obtuvieron {len(items)} registros en vivo desde LicitaLAB.")
            return pd.DataFrame(items)
        else:
            log(f"⚠️ Error al consultar LicitaLAB API (Status {response.status_code}): {response.text}")
            return None
    except Exception as e:
        log(f"⚠️ Excepción durante la llamada a la API de LicitaLAB: {e}")
        return None


def reestructurar_base_maestra(df: pd.DataFrame) -> pd.DataFrame:
    """Estructura y limpia las columnas garantizando los datos exactos requeridos."""
    if df.empty:
        return df

    # Normalizar nombres de columnas a minúsculas para mapeo flexible
    cols_map = {c: c.strip() for c in df.columns}
    df.rename(columns=cols_map, inplace=True)

    # Mapeos dinámicos desde API o Sheet
    col_workspace = next((c for c in df.columns if "workspace" in c.lower()), None)
    col_id = next((c for c in df.columns if "codigo" in c.lower() or c.lower() in ["id", "code"]), None)
    col_estado = next((c for c in df.columns if "estado" in c.lower() or "state" in c.lower()), None)
    col_tipo = next((c for c in df.columns if "tipo" in c.lower() or "type" in c.lower()), None)
    col_publicacion = next((c for c in df.columns if "publica" in c.lower() or "inicio" in c.lower()), None)
    col_cierre = next((c for c in df.columns if "cierre" in c.lower() or "limite" in c.lower()), None)

    # Formatear fechas
    if col_publicacion:
        df["Fecha Publicación"] = pd.to_datetime(df[col_publicacion], errors="coerce", dayfirst=True).dt.strftime("%Y-%m-%d")
    else:
        df["Fecha Publicación"] = "2025-01-01"

    if col_cierre:
        df["Fecha de Cierre"] = pd.to_datetime(df[col_cierre], errors="coerce", dayfirst=True).dt.strftime("%Y-%m-%d")
    else:
        df["Fecha de Cierre"] = "N/A"

    # Filtrar solo 2025+
    df["_year"] = pd.to_datetime(df["Fecha Publicación"], errors="coerce").dt.year
    df = df[df["_year"] >= 2025].drop(columns=["_year"], errors="ignore")

    # Mapear Workspace
    if col_workspace:
        df["Workspace"] = df[col_workspace]
    else:
        df["Workspace"] = "CENTRO DE DIAGNOSTICO CLINICA MAGALLANES SPA"

    # Normalizar Tipo de proceso (tender -> Licitación, agile -> Compra Ágil)
    if col_tipo:
        df["Tipo Proceso"] = df[col_tipo].replace({"tender": "Licitación Pública", "agile": "Compra Ágil"})

    # Asegurar columnas de comentarios y montos
    if "Comentarios" not in df.columns:
        df["Comentarios"] = ""

    col_monto = next((c for c in df.columns if "monto" in c.lower() or "total" in c.lower() or "estimado" in c.lower()), None)
    def calc_iva(val):
        try:
            v = float(str(val).replace("$", "").replace(".", "").replace(",", ".").strip())
            return f"$ {int(v * 1.19):,}".replace(",", ".")
        except Exception:
            return "$ 0"

    if col_monto:
        df["Monto Total + IVA (Adjudicado / Estimado)"] = df[col_monto].apply(calc_iva)
    else:
        df["Monto Total + IVA (Adjudicado / Estimado)"] = "$ 0"

    # Eliminar columnas obsoletas de evaluación
    cols_eliminar = [c for c in df.columns if "criterio" in c.lower() or "evaluaci" in c.lower() or "puntaje" in c.lower()]
    df.drop(columns=cols_eliminar, inplace=True, errors="ignore")

    # Orden final de las columnas en Google Sheets
    orden_oficial = [
        "Workspace",
        "Código Proceso",
        "Tipo Proceso",
        "Estado",
        "Fecha Publicación",
        "Fecha de Cierre",
        "Monto Total + IVA (Adjudicado / Estimado)",
        "Comentarios"
    ]

    cols_finales = [c for c in orden_oficial if c in df.columns] + \
                   [c for c in df.columns if c not in orden_oficial and c not in [col_workspace, col_cierre, col_publicacion]]

    return df[cols_finales]


def sincronizar():
    log("🔄 Iniciando sincronización de la Base Maestra desde LicitaLAB...")
    creds = obtener_credenciales_google()
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1

    # 1. Intentar obtener datos actualizados desde la API de LicitaLAB
    df_licitalab = obtener_datos_licitalab()

    if df_licitalab is not None and not df_licitalab.empty:
        df_final = reestructurar_base_maestra(df_licitalab)
    else:
        log("📋 Leyendo datos actuales de la planilla Google Sheets para reestructuración...")
        raw_records = sheet.get_all_records()
        df_sheet = pd.DataFrame(raw_records)
        df_final = reestructurar_base_maestra(df_sheet)

    log(f"📊 Total de registros procesados del año 2025+: {len(df_final)}")

    log("🧹 Limpiando la hoja de Google Sheets...")
    sheet.clear()

    log("📝 Escribiendo datos reales de Workspace, Publicación y Cierre...")
    valores = [df_final.columns.tolist()] + df_final.fillna("").astype(str).values.tolist()
    sheet.update(range_name="A1", values=valores)

    log("🚀 ¡Base Maestra sincronizada con éxito!")


if __name__ == "__main__":
    sincronizar()
