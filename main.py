import requests
import gspread
from google.oauth2.service_account import Credentials
import json
import os

LICITALAB_API_KEY = "llab_live_kxaJvD38lM1h8Qj11SVe6P18cZ-nEp2lMsECS5_THoE"
SPREADSHEET_ID = "1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek"

def clasificar_codigo(code):
    code_upper = str(code).upper()
    if "COT" in code_upper or "CO" in code_upper:
        if "COT" in code_upper:
            return "Compra Ágil"
        return "Licitación Privada"
    elif any(suf in code_upper for suf in ["LE", "LP", "LR", "L1", "E2"]):
        return "Licitación Pública"
    return "Licitación Pública"

def extraer_valor(item, claves):
    """Busca en el diccionario la primera clave existente o subclave anidada."""
    for clave in claves:
        if "." in clave:
            partes = clave.split(".")
            val = item
            for p in partes:
                if isinstance(val, dict):
                    val = val.get(p)
                else:
                    val = None
                    break
            if val is not None and str(val).strip() != "":
                return str(val).strip()
        else:
            val = item.get(clave)
            if val is not None and str(val).strip() != "":
                return str(val).strip()
    return ""

def main():
    print("Iniciando sincronización con LicitaLAB BI API...")

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

    print(f"Consultando endpoint oficial: {url}")
    try:
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            data = res.json()
            items = data.get("data", data) if isinstance(data, dict) else data
            
            if isinstance(items, list) and len(items) > 0:
                print(f"Estructura recibida. Primer elemento JSON: {items[0]}")
                filas_nuevas = []
                for item in items:
                    # Búsqueda exhaustiva de claves
                    codigo = extraer_valor(item, ["external_code", "code", "codigo", "id", "market_code", "opportunity_code"])
                    tipo = clasificar_codigo(codigo)
                    
                    # Fecha
                    fecha_raw = extraer_valor(item, ["published_at", "publication_date", "created_at", "fecha_publicacion", "updated_at"])
                    fecha = fecha_raw.split("T")[0] if "T" in fecha_raw else fecha_raw
                    
                    # Comprador
                    comprador = extraer_valor(item, ["buyer_name", "buyer.name", "organization_name", "buyer_organization", "comprador", "buyer", "institucion"])
                    
                    # Nombre / Título
                    nombre = extraer_valor(item, ["title", "name", "nombre", "description", "opportunity_title"])
                    
                    # Prestación / Categoría
                    prestacion = extraer_valor(item, ["category_name", "category.name", "category", "prestacion", "sector", "rubro"])

                    filas_nuevas.append([
                        fecha, codigo, tipo, comprador, nombre, prestacion
                    ])

                # Limpiar datos previos si es necesario o añadir nuevas filas
                sheet.append_rows(filas_nuevas)
                print(f"¡ÉXITO TOTAL! Se agregaron {len(filas_nuevas)} oportunidades completas a Google Sheets.")
            else:
                print("Conexión exitosa: No hay oportunidades en LicitaLAB actualmente.")
        else:
            print(f"Error devuelto por LicitaLAB API: {res.status_code} - {res.text}")
    except Exception as err:
        print(f"Excepción al procesar datos: {err}")

if __name__ == "__main__":
    main()
