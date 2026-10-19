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
    """Consulta la API de LicitaLAB con la API Key guardada en GitHub Secrets."""
    api_key = os.getenv("LICITALAB_API_KEY", "").strip()
    if not api_key:
        log("ℹ️ LICITALAB_API_KEY no configurada en Secrets. Procesando hoja actual...")
        return None

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    params = {"fecha_desde": "2025-01-01"}

    try:
        log("🌐 Conectando con API de LicitaLAB...")
        res = requests.get(LICITALAB_API_URL, headers=headers, params=params, timeout=30)
        if res.status_code == 200:
            data = res.json()
            items = data.get("data", data) if isinstance(data, dict) else data
            log(f"✅ Exito: {len(items)} registros recibidos desde LicitaLAB API.")
            return pd.DataFrame(items)
        else:
            log(f"⚠️ La API de LicitaLAB devolvió código {res.status_code}: {res.text}")
            return None
    except Exception as e:
        log(f"⚠️ No se pudo conectar a la API de LicitaLAB: {e}")
        return None


def procesar_y_corregir_tabla(df: pd.DataFrame) -> pd.DataFrame:
    """Mapea con precisión absoluta los campos de LicitaLAB evitando valores genéricos."""
    if df.empty:
        return df

    # Imprimir columnas detectadas en la consola para depuración
    log(f"🔍 Columnas detectadas en los datos recibidos: {list(df.columns)}")

    # 1. Recuperar o Mapear Workspace
    col_ws = next((c for c in df.columns if any(k in c.lower() for k in ["workspace", "espacio", "organismo", "unidad", "comprador"])), None)
    
    if col_ws and col_ws in df.columns:
        df["Workspace"] = df[col_ws].astype(str)
        # Si tiene "General RedSalud", intentar rescatar el Organismo o Unidad
        col_org = next((c for c in df.columns if any(k in c.lower() for k in ["organismo", "institucion", "compradora"])), None)
        if col_org and col_org in df.columns:
            df["Workspace"] = df.apply(
                lambda r: r[col_org] if str(r["Workspace"]).strip() in ["General RedSalud", "nan", "None", ""] else r["Workspace"],
                axis=1
            )
    else:
        df["Workspace"] = "CENTRO DE DIAGNOSTICO CLINICA MAGALLANES SPA"

    # 2. Recuperar o Mapear Fecha de Cierre
    col_cierre = next((c for c in df.columns if any(k in c.lower() for k in ["cierre", "limite", "termino", "postula", "final"])), None)
    if col_cierre and col_cierre in df.columns:
        df["Fecha de Cierre"] = df[col_cierre].astype(str).replace(["nan", "None", "Nat"], "")
    else:
        df["Fecha de Cierre"] = ""

    # 3. Recuperar Fecha Publicación
    col_pub = next((c for c in df.columns if any(k in c.lower() for k in ["publica", "inicio", "creac"])), None)
    if col_pub and col_pub in df.columns:
        df["Fecha Publicación"] = df[col_pub].astype(str).replace(["nan", "None", "Nat"], "")

    # 4. Código Proceso
    col_id = next((c for c in df.columns if any(k in c.lower() for k in ["codigo", "código", "id", "proceso"])), None)
    if col_id and col_id in df.columns:
        df["Código Proceso"] = df[col_id]

    # 5. Tipo Proceso
    col_tipo = next((c for c in df.columns if "tipo" in c.lower()), None)
    if col_tipo and col_tipo in df.columns:
        df["Tipo Proceso"] = df[col_tipo].replace({"tender": "Licitación Pública", "agile": "Compra Ágil"})

    # 6. Comentarios
    if "Comentarios" not in df.columns:
        df["Comentarios"] = ""

    # 7. Monto Total + IVA
    col_monto = next((c for c in df.columns if any(k in c.lower() for k in ["monto", "total", "estimado", "neto"])), None)
    def calc_iva(val):
        try:
            v = float(str(val).replace("$", "").replace(".", "").replace(",", ".").strip())
            return f"$ {int(v * 1.19):,}".replace(",", ".")
        except Exception:
            return "$ 0"

    if col_monto and col_monto in df.columns:
        df["Monto Total + IVA (Adjudicado / Estimado)"] = df[col_monto].apply(calc_iva)

    # Eliminar columnas obsoletas de evaluación
    cols_eliminar = [c for c in df.columns if any(k in c.lower() for k in ["criterio", "evaluac", "puntaje"])]
    df.drop(columns=cols_eliminar, inplace=True, errors="ignore")

    # Ordenar columnas
    columnas_ordenadas = [
        "Workspace",
        "Código Proceso",
        "Fecha Publicación",
        "Fecha de Cierre",
        "Tipo Proceso",
        "Monto Total + IVA (Adjudicado / Estimado)",
        "Comentarios"
    ]

    cols_finales = [c for c in columnas_ordenadas if c in df.columns] + \
                   [c for c in df.columns if c not in columnas_ordenadas]

    return df[cols_finales]


def sincronizar():
    log("🔄 Iniciando sincronización...")
    creds = obtener_credenciales_google()
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1

    df_raw = obtener_datos_licitalab()
    if df_raw is None or df_raw.empty:
        log("📄 Leyendo datos de la planilla actual...")
        raw_records = sheet.get_all_records()
        df_raw = pd.DataFrame(raw_records)

    log(f"📊 Registros procesados: {len(df_raw)}")

    df_limpio = procesar_y_corregir_tabla(df_raw)

    log("🧹 Limpiando Google Sheets...")
    sheet.clear()

    log("📝 Escribiendo la tabla corregida...")
    valores = [df_limpio.columns.tolist()] + df_limpio.fillna("").astype(str).values.tolist()
    sheet.update(range_name="A1", values=valores)

    log("🚀 ¡Sincronización realizada!")


if __name__ == "__main__":
    sincronizar()
