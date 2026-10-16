import requests
import gspread
from google.oauth2.service_account import Credentials
import json
import os

LICITALAB_API_KEY = "llab_live_kxaJvD381M1h8Qj11SVe6P18cZ-nEp21MsECS5_THoE"
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
    print("Iniciando sincronización desde GitHub Actions...")

    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        creds_dict = json.loads(creds_json)
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
    else:
        print("Error: No se encontraron credenciales en GOOGLE_CREDENTIALS_JSON")
        return

    sheet = client.open_by_key(SPREADSHEET_ID).sheet1

    headers = {
        "Authorization": f"Bearer {LICITALAB_API_KEY}",
        "Accept": "application/json"
    }

    # Probar endpoints comunes de la API de LicitaLAB
    endpoints = [
        "https://api.licitalab.cl/v1/licitaciones",
        "https://api.licitalab.cl/v1/oportunidades",
        "https://api.licitalab.cl/v1/procesos"
    ]

    response = None
    for url in endpoints:
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            response = res
            print(f"¡Conexión exitosa con LicitaLAB en: {url}!")
            break

    if not response or response.status_code != 200:
        url_fallba = "https://api.licitalab.cl/v1/licitaciones"
        response = requests.get(url_fallba, headers=headers)
        print(f"Respuesta API LicitaLAB: {response.status_code} - {response.text}")

    if response.status_code == 200:
        data = response.json()
        items = data.get("data", data) if isinstance(data, dict) else data
        
        if isinstance(items, list) and len(items) > 0:
            filas_nuevas = []
            for item in items:
                codigo = item.get("code") or item.get("codigo") or item.get("id") or ""
                tipo = clasificar_codigo(codigo)
                fecha = item.get("published_at") or item.get("fecha_publicacion") or ""
                comprador = item.get("buyer") or item.get("comprador") or item.get("institucion") or ""
                nombre = item.get("title") or item.get("nombre") or ""
                prestacion = item.get("category") or item.get("prestacion") or ""

                filas_nuevas.append([
                    str(fecha),
                    str(codigo),
                    str(tipo),
                    str(comprador),
                    str(nombre),
                    str(prestacion)
                ])

            if filas_nuevas:
                sheet.append_rows(filas_nuevas)
                print(f"¡Éxito! Se agregaron {len(filas_nuevas)} filas a Google Sheets.")
        else:
            print("No se encontraron registros nuevos en LicitaLAB en esta ejecución.")

if __name__ == "__main__":
    main()
