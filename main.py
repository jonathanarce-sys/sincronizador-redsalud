import requests
import gspread
from google.oauth2.service_account import Credentials
import json
import os

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
    """Convierte un número a formato CLP $ X.XXX.XXX"""
    if val is None or val == "" or str(val).upper() == "NONE":
        return "$ 0"
    try:
        monto = int(float(val))
        return f"$ {monto:,}".replace(",", ".")
    except:
        return str(val)

def limpiar_texto_o_lista(val):
    """Limpia listas, corchetes y comillas innecesarias de las respuestas de la API."""
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

def main():
    print("Iniciando sincronización formateada con LicitaLAB BI API...")

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

    url = "https://biapi.licitalab.cl/bi/v2/opportunities"
    headers = {
        "x-api-key": LICITALAB_API_KEY,
        "Accept": "application/json"
    }

    try:
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            data = res.json()
            items = data.get("data", data) if isinstance(data, dict) else data
            
            if isinstance(items, list) and len(items) > 0:
                filas_nuevas = []
                for item in items:
                    # A: Fecha Publicación
                    fecha_raw = str(item.get("PUBLISH_DATE") or item.get("CREATED_AT") or "").strip()
                    fecha = fecha_raw.split("T")[0] if "T" in fecha_raw else fecha_raw

                    # B: Código Proceso
                    codigo = str(item.get("OPPORTUNITY_CODE") or item.get("opportunity_code") or "").strip()

                    # C: Tipo Proceso
                    tipo_orig = str(item.get("OPPORTUNITY_TYPE") or item.get("opportunity_type") or "").strip()
                    tipo = clasificar_tipo(tipo_orig, codigo)

                    # D: Institución Compradora
                    comprador = str(item.get("ORGANISM") or item.get("organism") or "").strip()

                    # E: Nombre Proceso
                    nombre = str(item.get("OPPORTUNITY_NAME") or item.get("opportunity_name") or "").strip()

                    # F: Prestación (Categoría RedSalud)
                    prestacion = limpiar_texto_o_lista(item.get("B_LINE_TITLE") or item.get("ORGANISM_CATEGORY"))

                    # G: Monto Ofertado / Estimado (CLP)
                    monto_ofertado = formatear_moneda(item.get("APPLIED_AMOUNT") or item.get("AVAILABLE_AMOUNT"))

                    # H: Monto Total / Estimado (CLP)
                    monto_total = formatear_moneda(item.get("TOTAL_AWARDED_AMOUNT") or item.get("AVAILABLE_AMOUNT"))

                    # I: Estado de la Oferta
                    estado_oferta = str(item.get("OPPORTUNITY_STATUS") or item.get("MANAGED_STATUS_NAME") or "").strip()

                    # J: Adjudicatario (Proveedor Ganador)
                    adjudicatario = limpiar_texto_o_lista(item.get("AWARDED_PROVIDERS"))

                    # K: Motivo de No Adjudicación (RedSalud)
                    motivo_no_adj = limpiar_texto_o_lista(item.get("COMMENTS") or item.get("MANAGED_STATUS_NAME"))

                    filas_nuevas.append([
                        fecha, codigo, tipo, comprador, nombre,
                        prestacion, monto_ofertado, monto_total,
                        estado_oferta, adjudicatario, motivo_no_adj
                    ])

                # Limpieza y actualización limpia
                sheet.resize(rows=1)
                sheet.resize(rows=len(filas_nuevas) + 1)
                sheet.append_rows(filas_nuevas)
                print(f"¡Sincronización completada! {len(filas_nuevas)} filas actualizadas con formato profesional.")
            else:
                print("No hay nuevas oportunidades disponibles.")
        else:
            print(f"Error HTTP {res.status_code}: {res.text}")
    except Exception as err:
        print(f"Excepción: {err}")

if __name__ == "__main__":
    main()
