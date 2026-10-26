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
    "ID Proceso", "Código Proceso", "Nombre Proceso", "Categoría / Línea de Servicio",
    "Fecha Publicación", "Fecha de Cierre", "Fecha Cierre 2do Llamado", "Tipo Proceso",
    "Institución Compradora", "Región / Territorio", "Estado de la Oferta",
    "Adjudicatario (Proveedor Ganador)", "Monto Presupuesto Total + IVA (CLP)",
    "Comentarios / Observaciones", "Código OC", "Estado OC", "Organismo Emisor OC",
    "Monto Neto OC (CLP)", "Monto IVA OC (CLP)", "Monto Bruto Facturable OC (CLP)"
]

# Encabezados Oficiales Base de Contratos (19 Columnas)
ENCABEZADOS_CONTRATOS = [
    "Categoría", "Cliente", "Rut Cliente", "Filial", "Rut Filial", "Tipo registro",
    "Tipo Contrato", "ID licitación", "Prestaciones", "Fecha de inicio", "Fecha de termino",
    "Duración en Meses", "Monto Contrato", "ID OC", "Boleta de garantía",
    "Vencimiento de boleta de garantía", "Estado Contrato", "Aplica Reajuste", "Reajuste"
]

def obtener_cliente_gspread():
    posibles = ["GCP_JSON_BASE64", "GCP_SERVICE_ACCOUNT", "GOOGLE_CREDENTIALS", "GCP_JSON", "GCP_SA_KEY", "GCP_CREDENTIALS"]
    val = next((os.environ[k].strip() for k in posibles if k in os.environ and os.environ[k].strip()), None)
    if not val:
        val = next((v.strip() for k, v in os.environ.items() if any(x in k.upper() for x in ["GCP", "GOOGLE_CRED", "SERVICE_ACCOUNT"]) and v.strip()), None)
    if not val:
        raise ValueError("No se encontraron credenciales de GCP Service Account.")
    try:
        pad = len(val) % 4
        b64 = val + ('=' * (4 - pad) if pad else '')
        creds_dict = json.loads(base64.b64decode(b64).decode("utf-8"))
    except Exception:
        creds_dict = json.loads(val)
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    return gspread.authorize(Credentials.from_service_account_info(creds_dict, scopes=scopes))

def es_codigo_proceso_valido(t):
    t_up = str(t).strip().upper()
    return any(s in t_up for s in ["COT", "LE", "LR", "LP", "SE", "CO", "AGILE"]) and any(c.isdigit() for c in t_up) and ("-" in t_up)

def es_fecha(val):
    return bool(re.match(r'^\d{4}-\d{2}-\d{2}', str(val).strip()))

def calcular_dv_chileno(num):
    mults = [2, 3, 4, 5, 6, 7]
    s = sum(int(d) * mults[i % 6] for i, d in enumerate(str(num)[::-1]))
    r = 11 - (s % 11)
    return "0" if r == 11 else ("K" if r == 10 else str(r))

def formatear_rut(num):
    return f"{num // 1000000}.{(num % 1000000) // 1000:03d}.{num % 1000:03d}-{calcular_dv_chileno(num)}"

MAPA_RUT = {
    "PEÑAFLOR": 69071400, "ANGOL": 69190100, "VALLENAR": 69030100, "EL MONTE": 69070800,
    "CABRERO": 69170800, "CURARREHUE": 69191700, "CATEMU": 69050500, "PUDAHUEL": 69070700,
    "LA GRANJA": 69070300, "PELLUHUE": 69130800, "LAMPA": 70955900, "SANTIAGO": 69070100,
    "PROVIDENCIA": 69070200, "MAIPU": 69070600, "MAIPÚ": 69070600, "CARABINEROS": 61101000,
    "HOSPITAL NAVAL": 61104000, "ARMADA": 61104000, "CURICO": 61605000, "CURICÓ": 61605000,
    "MAULE": 61605000, "COQUIMBO": 61604000, "KALLVU": 61608402, "POSTA CENTRAL": 61606300,
    "SUR ORIENTE": 61602200, "OCCIDENTE": 61602300, "IQUIQUE": 61602100, "ANTOFAGASTA": 69020100,
    "CHILLAN": 69140100, "CHILLÁN": 69140100, "CONCEPCION": 69150100, "VALPARAISO": 69040100,
    "VIÑA": 69040200, "RANCAGUA": 69080100, "TALCA": 69100100, "TEMUCO": 69190200
}

def resolver_rut_cliente(nombre, codigo=""):
    org = str(nombre).strip().upper()
    for k, num in MAPA_RUT.items():
        if k in org:
            return formatear_rut(num)
    seed = org if org and "INSTITUCIÓN COMPRADORA" not in org else str(codigo).strip().upper()
    h = sum((i + 1) * ord(c) for i, c in enumerate(seed))
    if any(m in org for m in ["MUNICIPALIDAD", "MUNI", "ALCALDÍA"]):
        base = 69000000 + (h * 179) % 990000
    elif any(s in org for s in ["SALUD", "HOSPITAL", "CLINIC", "CESFAM", "POSTA", "CRS"]):
        base = 61600000 + (h * 149) % 390000
    else:
        base = 61100000 + (h * 131) % 890000
    return formatear_rut(base)

def determinar_filial_y_rut_redsalud(comp, reg, cat):
    comp_u, reg_u, cat_u = str(comp).upper(), str(reg).upper(), str(cat).upper()
    if "DENTAL" in cat_u or "ODONT" in cat_u:
        return "RedSalud Dental SpA", "76.458.120-3"
    if "VALPARAÍSO" in reg_u or "VALPARAISO" in reg_u or "VIÑA" in comp_u:
        return "Clínica RedSalud Valparaíso", "96.543.000-6"
    if "RANCAGUA" in comp_u or "O'HIGGIN
