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

def limpiar_texto_o_lista(val):
    if val is None or val == "" or str(val).upper() == "NONE":
        return ""
    if isinstance(val, list):
        items_limpios = [str(x).strip(" []'\"") for x in val if x]
        return ", ".join(items_limpios)
    
    val_str = str(val).strip()
    if val_str.startswith("[") and val_str.endswith("]"):
        try:
            parsed = json.loads(val_str)
            if isinstance(parsed, list):
                items_limpios = [str(x).strip(" []'\"") for x in parsed if x]
                return ", ".join(items_limpios)
        except:
            pass
    return val_str.strip(" []'\"")

def determinar_workspace_redsalud(item, nombre_proceso):
    """Extrae la Clínica o Centro Médico asignado evaluando Etiquetas (Tags), Miembros y Título."""
    # 1. Búsqueda en Etiquetas (TRANSLATED_TAGS / TAGS / LABELS)
    tags_raw = item.get("TRANSLATED_TAGS") or item.get("TAGS") or item.get("LABELS") or item.get("tags")
    tags_txt = limpiar_texto_o_lista(tags_raw)
    
    if tags_txt and tags_txt.upper() not in ["NONE", "NULL", ""]:
        return tags_txt

    # 2. Búsqueda en Título / Nombre o Comentarios de palabras clave de sedes RedSalud
    texto_evaluar = f"{nombre_proceso} {limpiar_texto_o_lista(item.get('COMMENTS'))}".upper()
    
    sedes = {
        "MAGALLANES": "CENTRO DE DIAGNOSTICO CLINICA MAGALLANES SPA",
        "SANTIAGO": "Clínica RedSalud Santiago",
        "VALPARAÍSO": "Clínica RedSalud Valparaíso",
        "VALPARAISO": "Clínica RedSalud Valparaíso",
        "PROVIDENCIA": "Centro Médico RedSalud Providencia",
        "VITACURA": "Clínica RedSalud Vitacura",
        "MAIPÚ": "Centro Médico RedSalud Maipú",
        "MAIPU": "Centro Médico RedSalud Maipú",
        "TEMUCO": "Clínica RedSalud Temuco",
        "IQUIQUE": "Clínica RedSalud Iquique",
        "ANTOFAGASTA": "Clínica RedSalud Antofagasta",
        "RANCAGUA": "Clínica RedSalud Rancagua",
        "TALCA": "Clínica RedSalud Talca"
    }

    for clave, nombre_sede in sedes.items():
        if clave in texto_evaluar:
            return nombre_sede

    # 3. Búsqueda en Miembro / Usuario asignado o Línea de Negocio
    miembro = item.get("MEMBER_NAME") or item.get("member_name")
    if miembro and str(miembro).strip() not in ["", "None", "null"]:
        return f"Asignado a: {str(miembro).strip()}"

    b_line = limpiar_texto_o_lista(item.get("B_LINE_TITLE"))
    if b_line and b_line.upper() not in ["MUNICIPALIDADES", "SALUD", "GOBIERNO", "NONE"]:
        return f"RedSalud - {b_line}"

    # 4. Fallback si es un registro de la Casa Matriz
    ws_title = item.get("WORKSPACE_TITLE") or item.get("workspace_title")
    if ws_title and str(ws_title).strip() not in ["", "None"]:
        return str(ws_title).strip()

    return "RedSalud Casa Matriz"

def determinar_prestacion(item, nombre_proceso):
    b_line = limpiar_texto_o_lista(item.get("B_LINE_TITLE") or item.get("b_line_title"))
    
    if b_line and b_line.upper() not in ["MUNICIPALIDADES", "SALUD", "GOBIERNO", "MUNICIPALIDAD"]:
        return b_line

    nombre_upper = str(nombre_proceso).upper()
    
    if any(k in nombre_upper for k in ["ECOGRAF", "ECOGRAFÍA", "ECOGRAFIAS"]):
        return "Ecografías / Imágenes"
    elif any(k in nombre_upper for k in ["MAMOGRAF", "MAMOGRAFÍA", "MAMOGRAFIAS"]):
        return "Mamografías / Imágenes"
    elif any(k in nombre_upper for k in ["LABORATORIO", "MUESTRAS", "INSUMOS LABORATORIO", "TEST"]):
        return "Laboratorio"
    elif any(k in nombre_upper for k in ["RADIOGRAF", "RAYOS", "TOMOGRAF"]):
        return "Imágenes / Radiología"
    elif any(k in nombre_upper for k in ["MEDICAMENTO", "FARMACO", "CENABAST", "COMPRIMIDOS"]):
        return "Farmacia / Medicamentos"
    elif any(k in nombre_upper for k in ["DENTAL", "ENDODONCIA", "LIMAS"]):
        return "Dental"
    elif any(k in nombre_upper for k in ["CONSULTA", "MEDICAS", "ESPECIALISTAS"]):
        return "Consultas Médicas"
        
    return b_line if b_line else "Salud General"

def descargar_oportunidades_licitalab():
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
                    log(f"Página {page} vacía. Fin de la descarga.")
                    break
                
                todos_los_items.extend(items)
                page += 1
                time.sleep(0.3)
            else:
                log(f"⚠️ API retornó HTTP {res.status_code} en página {page}")
                break
        except Exception as e:
            log(f"⚠️ Error al conectar con LicitaLAB en página {page}: {e}")
            break

    log(f"✅ Se obtuvieron {len(todos_los_items)} oportunidades desde LicitaLAB BI.")
    return todos_los_items

def procesar_items_api(items):
    filas = []
    
    for item in items:
        # 1. Nombre Proceso
        nombre = str(item.get("OPPORTUNITY_NAME") or item.get("opportunity_name") or "").strip()

        # 2. Workspace asignado (Búsqueda inteligente multicampo/tags)
        workspace = determinar_workspace_redsalud(item, nombre)
        
        # 3. Código Proceso
        codigo = str(item.get("OPPORTUNITY_CODE") or item.get("opportunity_code") or "").strip()
        
        # 4. Fecha Publicación
        fecha_pub = formatear_fecha(item.get("PUBLISH_DATE") or item.get("CREATED_AT"))
        
        # 5. Fecha de Cierre real
        fecha_cierre = formatear_fecha(item.get("CLOSING_DATE") or item.get("closing_date") or item.get("EXPIRATION_DATE"))
        
        # 6. Tipo Proceso
        tipo_orig = str(item.get("OPPORTUNITY_TYPE") or item.get("opportunity_type") or "").strip()
        tipo = clasificar_tipo(tipo_orig, codigo)
        
        # 7. Institución Compradora
        comprador = str(item.get("ORGANISM") or item.get("organism") or item.get("BUYER_NAME") or "").strip()
        
        # 8. Prestación
        prestacion = determinar_prestacion(item, nombre)
        
        # 9. Monto Total + IVA
        monto_neto = item.get("APPLIED_AMOUNT") or item.get("AVAILABLE_AMOUNT") or item.get("TOTAL_AWARDED_AMOUNT")
        monto_total_iva = formatear_moneda(monto_neto)
        
        # 10. Estado
        estado = str(item.get("OPPORTUNITY_STATUS") or item.get("MANAGED_STATUS_NAME") or "").strip()
        
        # 11. Adjudicatario
        adjudicatario = limpiar_texto_o_lista(item.get("AWARDED_PROVIDERS") or item.get("awarded_providers"))
        
        # 12. Comentarios
        comentarios = limpiar_texto_o_lista(item.get("COMMENTS") or item.get("comments") or item.get("MANAGED_STATUS_NAME"))

        filas.append([
            workspace,          # A
            codigo,             # B
            fecha_pub,          # C
            fecha_cierre,       # D
            tipo,               # E
            comprador,          # F
            nombre,             # G
            prestacion,         # H
            monto_total_iva,    # I
            estado,             # J
            adjudicatario,      # K
            comentarios         # L
        ])

    df = pd.DataFrame(filas, columns=[
        "Workspace", 
        "Código Proceso", 
        "Fecha Publicación", 
        "Fecha de Cierre",
        "Tipo Proceso", 
        "Institución Compradora", 
        "Nombre Proceso",
        "Prestación (Categoría RedSalud)", 
        "Monto Total + IVA (Adjudicado / Estimado)",
        "Estado de la Oferta", 
        "Adjudicatario (Proveedor Ganador)",
        "Comentarios"
    ])

    # Filtrar solo 2025 en adelante
    if "Fecha Publicación" in df.columns:
        df["_year"] = pd.to_datetime(df["Fecha Publicación"], errors="coerce").dt.year
        df = df[df["_year"] >= 2025].drop(columns=["_year"], errors="ignore")

    return df

def sincronizar():
    log("🔄 Iniciando sincronización de Base Maestra desde LicitaLAB BI API...")
    creds = obtener_credenciales_google()
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1

    items_api = descargar_oportunidades_licitalab()

    if items_api:
        df_final = procesar_items_api(items_api)
        log(f"📊 Registros procesados (Año 2025+): {len(df_final)}")

        log("🧹 Limpiando la planilla Google Sheets...")
        sheet.clear()

        log("📝 Escribiendo los datos con los Workspaces asignados por Clínica/Centro Médico...")
        valores = [df_final.columns.tolist()] + df_final.fillna("").astype(str).values.tolist()
        sheet.update(range_name="A1", values=valores)

        log("🚀 ¡Base Maestra sincronizada exitosamente!")
    else:
        log("⚠️ No se pudieron obtener datos desde la API. Revisa la conectividad.")

if __name__ == "__main__":
    sincronizar()
