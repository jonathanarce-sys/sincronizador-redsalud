import requests
import gspread
from google.oauth2.service_account import Credentials
import json
import os
import re
import time

LICITALAB_API_KEY = "llab_live_kxaJvD38lM1h8Qj11SVe6P18cZ-nEp2lMsECS5_THoE"
SPREADSHEET_ID = "1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek"

def clasificar_tipo(tipo_raw, code_raw):
    code_upper = str(code_raw).upper()
    tipo_upper = str(tipo_raw).upper()

    if "COT" in code_upper or "AGILE" in tipo_upper or "COMPRA ÁGIL" in tipo_upper:
        return "Compra Ágil"
    elif "CO" in code_upper or "PRIVATE" in tipo_upper:
        return "Licitación Privada"
    return "Licitación Pública"

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

def extraer_motivo_no_adjudicacion(item):
    motivo_oficial = item.get("MANAGED_STATUS_NAME") or item.get("DISCARD_REASON") or item.get("managed_status_name")
    if motivo_oficial and str(motivo_oficial).strip() not in ["", "None", "null"]:
        return str(motivo_oficial).strip()

    comentario = limpiar_texto_o_lista(item.get("COMMENTS"))
    if comentario:
        comentario_limpio = re.sub(r"^\[?\d{4}-\d{2}-\d{2}[^\]]*\]?\s*", "", comentario)
        return comentario_limpio.strip()

    return ""

def extraer_criterios_evaluacion(item):
    """Extrae los criterios de evaluación, ponderaciones o puntaje asignado."""
    criterios = item.get("EVALUATION_CRITERIA") or item.get("CRITERIA") or item.get("EVALUATION_SUMMARY") or item.get("evaluation_criteria")
    if criterios:
        return limpiar_texto_o_lista(criterios)
    
    score = item.get("SCORE") or item.get("score")
    if score is not None and str(score).strip() not in ["", "None", "null"]:
        return f"Puntaje Asignado: {score}"
        
    return ""

def procesar_item(item):
    fecha_raw = str(item.get("PUBLISH_DATE") or item.get("CREATED_AT") or "").strip()
    fecha = fecha_raw.split("T")[0] if "T" in fecha_raw else fecha_raw

    codigo = str(item.get("OPPORTUNITY_CODE") or item.get("opportunity_code") or "").strip()
    tipo_orig = str(item.get("OPPORTUNITY_TYPE") or item.get("opportunity_type") or "").strip()
    tipo = clasificar_tipo(tipo_orig, codigo)

    comprador = str(item.get("ORGANISM") or item.get("organism") or "").strip()
    nombre = str(item.get("OPPORTUNITY_NAME") or item.get("opportunity_name") or "").strip()
    prestacion = limpiar_texto_o_lista(item.get("B_LINE_TITLE") or item.get("ORGANISM_CATEGORY"))

    monto_ofertado = formatear_moneda(item.get("APPLIED_AMOUNT") or item.get("AVAILABLE_AMOUNT"))
    monto_total = formatear_moneda(item.get("TOTAL_AWARDED_AMOUNT") or item.get("AVAILABLE_AMOUNT"))
    estado_oferta = str(item.get("OPPORTUNITY_STATUS") or "").strip()
    adjudicatario = limpiar_texto_o_lista(item.get("AWARDED_PROVIDERS"))
    
    motivo_no_adj = extraer_motivo_no_adjudicacion(item)
    
    # Nueva Columna L: Criterios de Evaluación
    criterios_eval = extraer_criterios_evaluacion(item)

    return [
        fecha, codigo, tipo, comprador, nombre,
        prestacion, monto_ofertado, monto_total,
        estado_oferta, adjudicatario, motivo_no_adj,
        criterios_eval
    ]

def main():
    print("Iniciando Sincronización con 12 Columnas (incluye Criterios de Evaluación)...")

    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        try:
            creds_dict = json.loads(creds_json)
            scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
            creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
            client = gspread.authorize(creds)
        except Exception as e:
            print(f"Error al autenticar credenciales de Google: {e}")
            return
    else:
        print("Error: No se encontraron credenciales en GOOGLE_CREDENTIALS_JSON")
        return

    try:
        sheet = client.open_by_key(SPREADSHEET_ID).sheet1
        print("¡Conexión exitosa con Google Sheets!")
    except Exception as e:
        print(f"Error al abrir la planilla de Google Sheets: {e}")
        return

    headers_api = {
        "x-api-key": LICITALAB_API_KEY,
        "Accept": "application/json"
    }

    page = 1
    max_pages = 20
    todas_las_filas = []

    while page <= max_pages:
        url = f"https://biapi.licitalab.cl/bi/v2/opportunities?page={page}"
        print(f"Consultando página {page}: {url}")
        try:
            res = requests.get(url, headers=headers_api)
            if res.status_code == 200:
                data = res.json()
                items = data.get("data", data) if isinstance(data, dict) else data
                
                if not isinstance(items, list) or len(items) == 0:
                    print(f"Página {page} vacía. Se alcanzó el final de los datos.")
                    break
                
                for item in items:
                    fila_proc = procesar_item(item)
                    if fila_proc[1]:
                        todas_las_filas.append(fila_proc)

                page += 1
                time.sleep(0.5)
            else:
                print(f"Fin de paginación o error HTTP {res.status_code} en página {page}")
                break
        except Exception as err:
            print(f"Excepción en página {page}: {err}")
            break

    if todas_las_filas:
        print(f"Actualizando {len(todas_las_filas)} filas con las 12 columnas en Google Sheets...")
        
        sheet.resize(rows=1)
        sheet.resize(rows=len(todas_las_filas) + 1)
        
        chunk_size = 500
        for i in range(0, len(todas_las_filas), chunk_size):
            chunk = todas_las_filas[i:i + chunk_size]
            sheet.append_rows(chunk)
            time.sleep(1)
            
        print(f"¡ÉXITO TOTAL! Las 12 columnas (A-L) quedaron sincronizadas correctamente.")

if __name__ == "__main__":
    main()
