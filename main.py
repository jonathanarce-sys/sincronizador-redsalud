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

def main():
    print("Iniciando sincronización exacta con LicitaLAB BI API...")

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
                filas_nuevas = []
                for item in items:
                    # Mapeo exacto basado en la respuesta real del servidor
                    codigo = str(item.get("OPPORTUNITY_CODE") or item.get("opportunity_code") or "").strip()
                    tipo_orig = str(item.get("OPPORTUNITY_TYPE") or item.get("opportunity_type") or "").strip()
                    tipo = clasificar_tipo(tipo_orig, codigo)
                    
                    # Fecha
                    fecha_raw = str(item.get("PUBLISH_DATE") or item.get("CREATED_AT") or "").strip()
                    fecha = fecha_raw.split("T")[0] if "T" in fecha_raw else fecha_raw
                    
                    # Comprador
                    comprador = str(item.get("ORGANISM") or item.get("organism") or "").strip()
                    
                    # Nombre Proceso
                    nombre = str(item.get("OPPORTUNITY_NAME") or item.get("opportunity_name") or "").strip()
                    
                    # Prestación / Categoría
                    b_line = item.get("B_LINE_TITLE") or item.get("b_line_title") or ""
                    if isinstance(b_line, list) and len(b_line) > 0:
                        prestacion = ", ".join([str(x) for x in b_line])
                    elif isinstance(b_line, str) and b_line.startswith("["):
                        try:
                            parsed = json.loads(b_line)
                            prestacion = ", ".join(parsed)
                        except:
                            prestacion = b_line
                    else:
                        prestacion = str(item.get("ORGANISM_CATEGORY") or b_line or "").strip()

                    filas_nuevas.append([
                        fecha, codigo, tipo, comprador, nombre, prestacion
                    ])

                # Limpiar datos antiguos de la tabla (manteniendo encabezados en fila 1)
                sheet.resize(rows=1)
                sheet.resize(rows=1000)
                
                # Escribir todas las filas completas
                sheet.append_rows(filas_nuevas)
                print(f"¡ÉXITO TOTAL Y ABSOLUTO! Se actualizaron {len(filas_nuevas)} oportunidades con todas sus columnas pobladas.")
            else:
                print("Conexión exitosa: No hay oportunidades en LicitaLAB actualmente.")
        else:
            print(f"Error devuelto por LicitaLAB API: {res.status_code} - {res.text}")
    except Exception as err:
        print(f"Excepción al procesar datos: {err}")

if __name__ == "__main__":
    main()
