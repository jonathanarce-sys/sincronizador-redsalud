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
    url = "https://api.licitalab.cl/v1/opportunities"
    
    try:
        res = requests.get(url, headers=headers)
        if res.status_code != 200:
            print(f"Respuesta API LicitaLAB: {res.status_code} - {res.text}")
            return

        data = res.json()
        items = data.get("data", data) if isinstance(data, dict) else data
        
        filas_nuevas = []
        for item in items:
            code = item.get("code") or item.get("opportunity_code") or ""
            tipo_proceso = clasificar_codigo(code)
            fecha_pub = (item.get("published_at") or item.get("created_at") or "")[:10]
            monto = float(item.get("estimated_amount") or item.get("amount") or 0)
            
            filas_nuevas.append([
                fecha_pub,
                code,
                tipo_proceso,
                item.get("organism_name") or item.get("organism") or "",
                item.get("name") or item.get("title") or "",
                item.get("category_name") or item.get("category") or "Salud",
                monto,
                monto,
                "Publicada / En Proceso",
                "Pendiente de Adjudicación",
                "En proceso de postulación y evaluación de ofertas"
            ])

        if filas_nuevas:
            sheet.append_rows(filas_nuevas)
            print(f"¡Éxito! Se insertaron {len(filas_nuevas)} filas en Google Sheets.")
        else:
            print("No hay nuevas oportunidades en esta ejecución.")
    except Exception as e:
        print(f"Error durante la ejecución: {e}")

if __name__ == "__main__":
    main()
