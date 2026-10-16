import requests
import gspread
from google.oauth2.service_account import Credentials
import json
import os

LICITALAB_API_KEY = "llab_live_kxaJvD38lM1h8Qj11SVe6P18cZ-nEp2lMsECS5_THoE"
SPREADSHEET_ID = "1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek"

def clasificar_codigo(code):
    code_upper = str(code).upper()
    if "COT" in code_upper:
        return "Compra Ágil"
    elif any(suf in code_upper for suf in ["LE", "LP", "LR", "L1", "E2"]):
        return "Licitación Pública"
    elif "CO" in code_upper:
        return "Licitación Privada"
    return "Licitación Pública"

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

    # Especificación oficial LicitaLAB BI API
    url = "https://biapi.licitalab.cl/bi/v2/opportunities"
    headers = {
        "x-api-key": LICITALAB_API_KEY,
        "Accept": "application/json"
    }

    print(f"Consultando endpoint oficial: {url}")
    try:
        res = requests.get(url, headers=headers)
        print(f"Respuesta HTTP {res.status_code}")
        
        if res.status_code == 200:
            data = res.json()
            items = data.get("data", data) if isinstance(data, dict) else data
            
            if isinstance(items, list) and len(items) > 0:
                filas_nuevas = []
                for item in items:
                    codigo = item.get("code") or item.get("codigo") or item.get("id") or ""
                    tipo = clasificar_codigo(codigo)
                    fecha = item.get("published_at") or item.get("created_at") or item.get("fecha_publicacion") or ""
                    comprador = item.get("buyer") or item.get("comprador") or item.get("organization_name") or ""
                    nombre = item.get("title") or item.get("name") or item.get("nombre") or ""
                    prestacion = item.get("category") or item.get("category_name") or item.get("prestacion") or ""

                    filas_nuevas.append([
                        str(fecha), str(codigo), str(tipo),
                        str(comprador), str(nombre), str(prestacion)
                    ])

                sheet.append_rows(filas_nuevas)
                print(f"¡ÉXITO TOTAL! Se agregaron {len(filas_nuevas)} oportunidades a Google Sheets.")
            else:
                print("Conexión exitosa: No hay nuevas oportunidades registradas actualmente en LicitaLAB.")
        else:
            print(f"Error devuelto por LicitaLAB API: {res.status_code} - {res.text}")
    except Exception as err:
        print(f"Excepción al conectar con la API: {err}")

if __name__ == "__main__":
    main()
