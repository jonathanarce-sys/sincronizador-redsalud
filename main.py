import os
import json
import base64
import sys
import pandas as pd
import requests
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek"
LICITALAB_API_URL = os.getenv("LICITALAB_API_URL", "https://api.licitalab.cl/v1/procesos")

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
    """Consulta la API de LicitaLAB si la API key está disponible."""
    api_key = os.getenv("LICITALAB_API_KEY", "").strip()
    if not api_key:
        log("ℹ️ LICITALAB_API_KEY no configurada. Se reestructurará sobre la hoja actual.")
        return None

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    params = {"fecha_desde": "2025-01-01"}

    try:
        log("🌐 Obteniendo datos desde API LicitaLAB...")
        res = requests.get(LICITALAB_API_URL, headers=headers, params=params, timeout=30)
        if res.status_code == 200:
            data = res.json()
            items = data.get("data", data) if isinstance(data, dict) else data
            log(f"✅ Se obtuvieron {len(items)} registros desde la API de LicitaLAB.")
            return pd.DataFrame(items)
        else:
            log(f"⚠️ API LicitaLAB retornó estado {res.status_code}")
            return None
    except Exception as e:
        log(f"⚠️ Excepción al conectar con LicitaLAB: {e}")
        return None


def procesar_y_limpiar_tabla(df: pd.DataFrame) -> pd.DataFrame:
    """Mapea con precisión absoluta Workspace, Fecha de Cierre, Publicación y elimina basura."""
    if df.empty:
        return df

    # Normalizar cabeceras eliminando espacios
    df.columns = [str(c).strip() for c in df.columns]

    # 1. Búsqueda exhaustiva de columna 'Workspace'
    col_ws = next((c for c in df.columns if any(k in c.lower() for k in ["workspace", "espacio", "unid_ejecutora", "organismo", "usuario"])), None)
    if col_ws and col_ws in df.columns:
        df["Workspace"] = df[col_ws].astype(str).replace(["nan", "None", ""], "Sin Workspace especificado")
    else:
        df["Workspace"] = "CENTRO DE DIAGNOSTICO CLINICA MAGALLANES SPA"

    # 2. Búsqueda exhaustiva de 'Fecha de Cierre'
    col_cierre = next((c for c in df.columns if any(k in c.lower() for k in ["cierre", "limite", "termino", "postula"])), None)
    if col_cierre and col_cierre in df.columns:
        df["Fecha de Cierre"] = df[col_cierre].astype(str).replace(["nan", "None", "Nat"], "")
    else:
        df["Fecha de Cierre"] = ""

    # 3. Búsqueda exhaustiva de 'Fecha Publicación'
    col_pub = next((c for c in df.columns if any(k in c.lower() for k in ["publica", "inicio", "creac"])), None)
    if col_pub and col_pub in df.columns:
        df["Fecha Publicación"] = df[col_pub].astype(str).replace(["nan", "None", "Nat"], "")
    else:
        df["Fecha Publicación"] = ""

    # 4. Búsqueda de 'Código Proceso'
    col_id = next((c for c in df.columns if any(k in c.lower() for k in ["codigo", "código", "id", "proceso"])), None)
    if col_id and col_id in df.columns:
        df["Código Proceso"] = df[col_id]

    # 5. Búsqueda de 'Tipo Proceso'
    col_tipo = next((c for c in df.columns if "tipo" in c.lower()), None)
    if col_tipo and col_tipo in df.columns:
        df["Tipo Proceso"] = df[col_tipo].replace({"tender": "Licitación Pública", "agile": "Compra Ágil"})

    # 6. Búsqueda de 'Estado'
    col_estado = next((c for c in df.columns if "estado" in c.lower()), None)
    if col_estado and col_estado in df.columns:
        df["Estado"] = df[col_estado]

    # 7. Búsqueda o creación de 'Comentarios'
    col_comentarios = next((c for c in df.columns if any(k in c.lower() for k in ["comentario", "observac", "nota"])), None)
    if col_comentarios and col_comentarios in df.columns:
        df["Comentarios"] = df[col_comentarios]
    else:
        df["Comentarios"] = ""

    # 8. Búsqueda o cálculo de 'Monto Total + IVA (Adjudicado / Estimado)'
    col_monto = next((c for c in df.columns if any(k in c.lower() for k in ["monto", "total", "estimado", "neto"])), None)
    def calc_iva(val):
        try:
            v = float(str(val).replace("$", "").replace(".", "").replace(",", ".").strip())
            return f"$ {int(v * 1.19):,}".replace(",", ".")
        except Exception:
            return "$ 0"

    if col_monto and col_monto in df.columns:
        df["Monto Total + IVA (Adjudicado / Estimado)"] = df[col_monto].apply(calc_iva)

    # 9. Eliminar explícitamente columnas de 'Criterios de Evaluación' o 'Puntajes'
    cols_eliminar = [c for c in df.columns if any(k in c.lower() for k in ["criterio", "evaluac", "puntaje"])]
    df.drop(columns=cols_eliminar, inplace=True, errors="ignore")

    # 10. Seleccionar y reordenar columnas limpias
    columnas_ordenadas = [
        "Workspace",
        "Código Proceso",
        "Fecha Publicación",
        "Fecha de Cierre",
        "Tipo Proceso",
        "Estado",
        "Monto Total + IVA (Adjudicado / Estimado)",
        "Comentarios"
    ]

    cols_finales = [c for c in columnas_ordenadas if c in df.columns] + \
                   [c for c in df.columns if c not in columnas_ordenadas and c not in ["Workspace_old", "Cierre_old"]]

    return df[cols_finales]


def sincronizar():
    log("🔄 Iniciando sincronización...")
    creds = obtener_credenciales_google()
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1

    # Cargar datos desde la API o directamente desde la planilla
    df_raw = obtener_datos_licitalab()
    if df_raw is None or df_raw.empty:
        log("📄 Leyendo datos de la planilla actual...")
        raw_records = sheet.get_all_records()
        df_raw = pd.DataFrame(raw_records)

    log(f"📊 Registros a procesar: {len(df_raw)}")
    log(f"📋 Encabezados detectados en la fuente: {list(df_raw.columns)}")

    df_limpio = procesar_y_limpiar_tabla(df_raw)

    log("🧹 Limpiando la hoja de Google Sheets...")
    sheet.clear()

    log("📝 Sobrescribiendo la planilla con los datos corregidos de Workspace y Fecha de Cierre...")
    valores = [df_limpio.columns.tolist()] + df_limpio.fillna("").astype(str).values.tolist()
    sheet.update(range_name="A1", values=valores)

    log("🚀 ¡Sincronización completada con éxito!")


if __name__ == "__main__":
    sincronizar()
