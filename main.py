import os
import json
import base64
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek"

def obtener_credenciales_google():
    """Obtiene y decodifica las credenciales tolerando problemas de padding en Base64."""
    creds_dict = None
    gcp_b64 = os.getenv("GCP_JSON_BASE64", "").strip()
    
    if gcp_b64:
        # Si la cadena no es múltiplo de 4, corregir el padding de Base64 agregando '='
        missing_padding = len(gcp_b64) % 4
        if missing_padding != 0:
            gcp_b64 += '=' * (4 - missing_padding)
            
        try:
            json_bytes = base64.b64decode(gcp_b64)
            creds_dict = json.loads(json_bytes.decode("utf-8"))
        except Exception:
            # Si no es Base64 válido, intentar leer como JSON directo
            try:
                creds_dict = json.loads(gcp_b64, strict=False)
            except Exception as e:
                raise ValueError(f"No se pudo interpretar GCP_JSON_BASE64 como Base64 ni como JSON: {e}")

    if not creds_dict and os.getenv("GOOGLE_CREDENTIALS_JSON"):
        raw_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
        creds_dict = json.loads(raw_json, strict=False)

    if not creds_dict:
        raise ValueError("❌ No se encontraron credenciales válidas.")

    if "private_key" in creds_dict:
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    return Credentials.from_service_account_info(creds_dict, scopes=scopes)
