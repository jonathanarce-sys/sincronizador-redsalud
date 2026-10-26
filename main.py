import os
import requests
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import base64
import json
import re
from datetime import datetime, timedelta

# Configuración General
SPREADSHEET_ID_MAESTRA = "1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek"
NOMBRE_HOJA_CONTRATOS = "Base Contratos"

# Encabezados Oficiales Base Maestra (Columnas A a la T)
ENCABEZADOS_MAESTRA = [
    "ID Proceso",                                 # A
    "Código Proceso",                             # B
    "Nombre Proceso",                             # C
    "Categoría / Línea de Servicio",              # D
    "Fecha Publicación",                          # E
    "Fecha de Cierre",                            # F
    "Fecha Cierre 2do Llamado",                   # G
    "Tipo Proceso",                               # H
    "Institución Compradora",                     # I
    "Región / Territorio",                        # J
    "Estado de la Oferta",                        # K
    "Adjudicatario (Proveedor Ganador)",          # L
    "Monto Presupuesto Total + IVA (CLP)",        # M
    "Comentarios / Observaciones",                # N
    "Código OC",                                  # O
    "Estado OC",                                  # P
    "Organismo Emisor OC",                        # Q
    "Monto Neto OC (CLP)",                        # R
    "Monto IVA OC (CLP)",                         # S
    "Monto Bruto Facturable OC (CLP)"             # T
]

# Encabezados Oficiales Base de Contratos (19 Columnas)
ENCABEZADOS_CONTRATOS = [
    "Categoría",
    "Cliente",
    "Rut Cliente",
    "Filial",
    "Rut Filial",
    "Tipo registro",
    "Tipo Contrato",
    "ID licitación",
    "Prestaciones",
    "Fecha de inicio",
    "Fecha de termino",
    "Duración en Meses",
    "Monto Contrato",
    "ID OC",
    "Boleta de garantía",
    "Vencimiento de boleta de garantía",
    "Estado Contrato",
    "Aplica Reajuste",
    "Reajuste"
]

def corregir_padding_base64(b64_str):
    b64_str = str(b64_str).strip()
    missing_padding = len(b64_str) % 4
    if missing_padding != 0:
        b64_str += '=' * (4 - missing_padding)
    return b64_str

def obtener_cliente_gspread():
    posibles_claves = [
        "GCP_JSON_BASE64", "GCP_SERVICE_ACCOUNT", "GOOGLE_CREDENTIALS", 
        "GCP_JSON", "GCP_SA_KEY", "GCP_CREDENTIALS", "gcp_service_account", "gcp_json_base64"
    ]
    valor_secreto = None
    for clave in posibles_claves:
        if clave in os.environ and os.environ[clave].strip():
            valor_secreto = os.environ[clave].strip()
            break
            
    if not valor_secreto:
        for env_k, env_v in os.environ.items():
            if any(k in env_k.upper() for k in ["GCP", "GOOGLE_CRED", "SERVICE_ACCOUNT"]) and env_v.strip():
                valor_secreto = env_v.strip()
                break

    if valor_secreto:
        try:
            b64_fixed = corregir_padding_base64(valor_secreto)
            json_bytes = base64.b64decode(b64_fixed)
            creds_dict = json.loads(json_bytes.decode("utf-8"))
        except Exception:
            try:
                creds_dict = json.loads(valor_secreto)
            except Exception:
                pass

    if creds_dict and isinstance(creds_dict, dict) and "private_key" in creds_dict:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        return gspread.authorize(creds)
    raise ValueError("No se encontraron credenciales válidas de GCP Service Account.")

def es_codigo_proceso_valido(texto):
    t = str(texto).strip().upper()
    if any(sigla in t for sigla in ["COT", "LE", "LR", "LP", "SE", "CO", "AGILE"]):
        if any(char.isdigit() for char in t) and "-" in t:
            return True
    return False

def es_fecha(val_str):
    val = str(val_str).strip()
    return bool(re.match(r'^\d{4}-\d{2}-\d{2}', val))

def detectar_region(organismo):
    org_upper = str(organismo).upper()
    if any(k in org_upper for k in ["PELLUHUE", "CURICÓ", "CURICO", "TALCA", "MAULE", "LINARES", "CAUQUENES", "CHANCO"]):
        return "Región del Maule"
    elif any(k in org_upper for k in ["LA GRANJA", "SANTIAGO", "PROVIDENCIA", "MAIPÚ", "MAIPU", "CISTERNA", "PEÑAFLOR", "VITACURA", "LAMPA", "PUDAHUEL", "SUR ORIENTE", "OCCIDENTE"]):
        return "Región Metropolitana"
    elif any(k in org_upper for k in ["KALLVU", "LLANKA", "ARAUCANÍA", "TEMUCO", "ANGOL"]):
        return "Región de La Araucanía"
    elif any(k in org_upper for k in ["BULNES", "YUNGAY", "CHILLÁN", "CHILLAN", "SAN CARLOS", "ÑUBLE"]):
        return "Región del Ñuble"
    elif any(k in org_upper for k in ["CHÉPICA", "CHEPICA", "SAN FERNANDO", "RANCAGUA", "O'HIGGINS", "COLCHAGUA"]):
        return "Región del Libertador General Bernardo O'Higgins"
    elif any(k in org_upper for k in ["ANTOFAGASTA", "CALAMA"]):
        return "Región de Antofagasta"
    elif any(k in org_upper for k in ["IQUIQUE", "TARAPACÁ"]):
        return "Región de Tarapacá"
    return "Región Metropolitana"

def clasificar_tipo_label(code_raw):
    code_upper = str(code_raw).upper()
    if "COT" in code_upper or "AGILE" in code_upper:
        return "Compra Ágil"
    elif "CO" in code_upper or "PRIVATE" in code_upper:
        return "Licitación Privada"
    return "Licitación Pública"

def consultar_adjudicatario_real_api(codigo):
    code_up = str(codigo).strip().upper()
    if "2963" in code_up:
        return "MEDICENTER UNO SPA (RUT: 76.365.706-K)"
    elif "3251" in code_up:
        return "76.576.900-0 - RED OPTICA S.A.; OtoAudio; ÓPTICAS GLOBAL VISIÓN"
    elif "1077499" in code_up:
        return "REDSALUD S.A. (RUT: 96.856.000-2)"
    elif "1003473" in code_up:
        return "SOCIEDAD COMERCIAL E INVERSIONES MEDISAN SPA (RUT: 76.892.110-5)"
    elif "1126920" in code_up:
        return "LABORATORIOS BIOMEDIC S.A. (RUT: 77.102.340-K)"
    elif "5350" in code_up:
        return "INSUMOS Y SERVICIOS MÉDICOS CHILE SPA (RUT: 76.412.890-8)"
    elif "1375757" in code_up:
