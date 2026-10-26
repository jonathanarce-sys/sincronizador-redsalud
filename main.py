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
SPREADSHEET_ID_CONTRATOS = os.environ.get("SPREADSHEET_ID_CONTRATOS", SPREADSHEET_ID_MAESTRA).strip()
NOMBRE_HOJA_CONTRATOS = "Base Contratos"

# Encabezados Oficiales Base Maestra (Columnas A a la T)
ENCABEZADOS_MAESTRA = [
    "ID Proceso",
    "Código Proceso",
    "Nombre Proceso",
    "Categoría / Línea de Servicio",
    "Fecha Publicación",
    "Fecha de Cierre",
    "Fecha Cierre 2do Llamado",
    "Tipo Proceso",
    "Institución Compradora",
    "Región / Territorio",
    "Estado de la Oferta",
    "Adjudicatario (Proveedor Ganador)",
    "Monto Presupuesto Total + IVA (CLP)",
    "Comentarios / Observaciones",
    "Código OC",
    "Estado OC",
    "Organismo Emisor OC",
    "Monto Neto OC (CLP)",
    "Monto IVA OC (CLP)",
    "Monto Bruto Facturable OC (CLP)"
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

    creds_dict = None
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
    siglas = ["COT", "LE", "LR", "LP", "SE", "CO", "AGILE"]
    return any(s in t for s in siglas) and any(c.isdigit() for c in t) and ("-" in t)

def es_fecha(val_str):
    val = str(val_str).strip()
    return bool(re.match(r'^\d{4}-\d{2}-\d{2}', val))

def calcular_dv_chileno(numero):
    multiplicadores = [2, 3, 4, 5, 6, 7]
    suma = 0
    num_str = str(numero)[::-1]
    for i, digito in enumerate(num_str):
        suma += int(digito) * multiplicadores[i % len(multiplicadores)]
    resto = 11 - (suma % 11)
    if resto == 11:
        return "0"
    elif resto == 10:
        return "K"
    else:
        return str(resto)

def resolver_rut_cliente(nombre_organismo, codigo_proceso=""):
    org = str(nombre_organismo).strip().upper()
    directos = {
        "PEÑAFLOR": 69071400, "ANGOL": 69190100, "VALLENAR": 69030100,
        "EL MONTE": 69070800, "CABRERO": 69170800, "CURARREHUE": 69191700,
        "CATEMU": 69050500, "PUDAHUEL": 69070700, "LA GRANJA": 69070300,
        "PELLUHUE": 69130800, "LAMPA": 70955900, "SANTIAGO": 69070100,
        "PROVIDENCIA": 69070200, "MAIPU": 69070600, "MAIPÚ": 69070600,
        "CARABINEROS": 61101000, "HOSPITAL NAVAL": 61104000, "ARMADA": 61104000,
        "CURICO": 61605000, "CURICÓ": 61605000, "SALUD DEL MAULE": 61605000,
        "CO
