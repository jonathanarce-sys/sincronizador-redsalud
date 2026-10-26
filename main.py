import os
import requests
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import base64
import json
import re
from datetime import datetime, timedelta

SPREADSHEET_ID_MAESTRA = "1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek"
SPREADSHEET_ID_CONTRATOS = os.environ.get("SPREADSHEET_ID_CONTRATOS", SPREADSHEET_ID_MAESTRA).strip()
NOMBRE_HOJA_CONTRATOS = "Base Contratos"

ENCABEZADOS_MAESTRA = [
    "ID Proceso", "Código Proceso", "Nombre Proceso", "Categoría / Línea de Servicio",
    "Fecha Publicación", "Fecha de Cierre", "Fecha Cierre 2do Llamado", "Tipo Proceso",
    "Institución Compradora", "Región / Territorio", "Estado de la Oferta",
    "Adjudicatario (Proveedor Ganador)", "Monto Presupuesto Total + IVA (CLP)",
    "Comentarios / Observaciones", "Código OC", "Estado OC", "Organismo Emisor OC",
    "Monto Neto OC (CLP)", "Monto IVA OC (CLP)", "Monto Bruto Facturable OC (CLP)"
]

ENCABEZADOS_CONTRATOS = [
    "Categoría", "Cliente", "Rut Cliente", "Filial", "Rut Filial", "Tipo registro",
    "Tipo Contrato", "ID licitación", "Prestaciones", "Fecha de inicio", "Fecha de termino",
    "Duración en Meses", "Monto Contrato", "ID OC", "Boleta de garantía",
    "Vencimiento de boleta de garantía", "Estado Contrato", "Aplica Reajuste", "Reajuste"
]

def obtener_cliente_gspread():
    posibles = [
        "GCP_JSON_BASE64", "GCP_SERVICE_ACCOUNT", "GOOGLE_CREDENTIALS",
        "GCP_JSON", "GCP_SA_KEY", "GCP_CREDENTIALS"
    ]
    val = None
    for k in posibles:
        if k in os.environ and os.environ[k].strip():
            val = os.environ[k].strip()
            break
    if not val:
        for ek, ev in os.environ.items():
            if any(x in ek.upper() for x in ["GCP", "GOOGLE_CRED", "SERVICE_ACCOUNT"]):
                if ev.strip():
                    val = ev.strip()
                    break
    if not val:
        raise ValueError("No se encontraron credenciales GCP.")
    try:
        pad = len(val) % 4
        b64 = val + ("=" * (4 - pad) if pad else "")
        creds_dict = json.loads(base64.b64decode(b64).decode("utf-8"))
    except Exception:
        creds_dict = json.loads(val)
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    return gspread.authorize(Credentials.from_service_account_info(creds_dict, scopes=scopes))

def es_codigo_proceso_valido(t):
    u = str(t).strip().upper()
    siglas = ["COT", "LE", "LR", "LP", "SE", "CO", "AGILE"]
    return any(s in u for s in siglas) and any(c.isdigit() for c in u) and ("-" in u)

def es_fecha(val):
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}", str(val).strip()))

def calcular_dv_chileno(num):
    mults = [2, 3, 4, 5, 6, 7]
    s = sum(int(d) * mults[i % 6] for i, d in enumerate(str(num)[::-1]))
    return ("0", "K", "9", "8", "7", "6", "5", "4", "3", "2", "1")[s % 11]

def formatear_rut(num):
    dv = calcular_dv_chileno(num)
    m = num // 1000000
    k = (num % 1000000) // 1000
    u = num % 1000
    return f"{m}.{k:03d}.{u:03d}-{dv}"

MAPA_RUT = {
    "PEÑAFLOR": 69071400, "ANGOL": 69190100, "VALLENAR": 69030100,
    "EL MONTE": 69070800, "CABRERO": 69170800, "CURARREHUE": 69191700,
    "CATEMU": 69050500, "PUDAHUEL": 69070700, "LA GRANJA": 69070300,
    "PELLUHUE": 69130800, "LAMPA": 70955900, "SANTIAGO": 69070100,
    "PROVIDENCIA": 69070200, "MAIPU": 69070600, "MAIPÚ": 69070600,
    "CARABINEROS": 61101000, "HOSPITAL NAVAL": 61104000, "ARMADA": 61104000,
    "CURICO": 61605000, "CURICÓ": 61605000, "MAULE": 61605000,
    "COQUIMBO": 61604000, "KALLVU": 61608402, "POSTA CENTRAL": 61
