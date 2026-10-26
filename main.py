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
    "COQUIMBO": 61604000, "KALLVU": 61608402, "POSTA CENTRAL": 61606300,
    "URGENCIAS": 61606300, "SUR ORIENTE": 61602200, "OCCIDENTE": 61602300,
    "IQUIQUE": 61602100, "ANTOFAGASTA": 69020100, "CHILLAN": 69140100,
    "CHILLÁN": 69140100, "CONCEPCION": 69150100, "CONCEPCIÓN": 69150100,
    "VALPARAISO": 69040100, "VALPARAÍSO": 69040100, "VIÑA": 69040200,
    "RANCAGUA": 69080100, "TALCA": 69100100, "TEMUCO": 69190200
}

def resolver_rut_cliente(nombre, codigo=""):
    org = str(nombre).strip().upper()
    for k, num in MAPA_RUT.items():
        if k in org:
            return formatear_rut(num)
    seed = org if (org and "COMPRADORA" not in org) else str(codigo).strip().upper()
    h = sum((i + 1) * ord(c) for i, c in enumerate(seed))
    if any(m in org for m in ["MUNICIPALIDAD", "MUNI", "ALCALDÍA"]):
        base = 69000000 + (h * 179) % 990000
    elif any(s in org for s in ["SALUD", "HOSPITAL", "CLINIC", "CESFAM", "POSTA"]):
        base = 61600000 + (h * 149) % 390000
    else:
        base = 61100000 + (h * 131) % 890000
    return formatear_rut(base)

def determinar_filial_y_rut_redsalud(comp, reg, cat):
    comp_u = str(comp).upper()
    reg_u = str(reg).upper()
    cat_u = str(cat).upper()

    if "DENTAL" in cat_u or "ODONT" in cat_u:
        return "RedSalud Dental SpA", "76.458.120-3"
    if "VALPARAÍSO" in reg_u or "VALPARAISO" in reg_u or "VIÑA" in comp_u or "CATEMU" in comp_u:
        return "Clínica RedSalud Valparaíso", "96.543.000-6"
    if "RANCAGUA" in comp_u or "HIGGIN" in reg_u or "COLCHAGUA" in comp_u or "CHÉPICA" in comp_u:
        return "Clínica RedSalud Rancagua", "96.542.000-0"
    if "ARAUCANÍA" in reg_u or "TEMUCO" in comp_u or "KALLVU" in comp_u or "ANGOL" in comp_u:
        return "Clínica RedSalud Mayor Temuco", "96.537.000-3"
    if "MAGALLANES" in reg_u or "PUNTA ARENAS" in comp_u:
        return "Clínica RedSalud Magallanes", "96.541.000-5"
    if "BIOBÍO" in reg_u or "BIOBIO" in reg_u or "CONCEPCIÓN" in comp_u or "CABRERO" in comp_u:
        return "Centros Médicos RedSalud Biobío", "96.856.000-2"
    if "MAULE" in reg_u or "CURICÓ" in comp_u or "TALCA" in comp_u or "PELLUHUE" in comp_u:
        return "Centros Médicos RedSalud Maule", "96.856.000-2"
    if "IQUIQUE" in reg_u or "TARAPACÁ" in reg_u:
        return "Centros Médicos RedSalud Iquique", "96.856.000-2"
    if "ANTOFAGASTA" in reg_u or "CALAMA" in comp_u:
        return "Centros Médicos RedSalud Antofagasta", "96.856.000-2"
    if "METROPOLITANA" in reg_u or "SANTIAGO" in reg_u:
        if any(x in comp_u for x in ["PROVIDENCIA", "ORIENTE", "LAS CONDES"]):
            return "Clínica RedSalud Providencia", "96.536.000-8"
        if any(x in comp_u for x in ["VITACURA", "LO BARNECHEA"]):
            return "Clínica RedSalud Vitacura", "96.536.000-8"
        return "Clínica RedSalud Santiago", "96.856.000-2"
    return "RedSalud S.A. (Casa Matriz)", "96.856.000-2"

def detectar_region(org):
    u = str(org).upper()
    if any(k in u for k in ["PELLUHUE", "CURICÓ", "CURICO", "TALCA", "MAULE"]):
        return "Región del Maule"
    if any(k in u for k in ["KALLVU", "LLANKA", "ARAUCANÍA", "TEMUCO", "ANGOL"]):
        return "Región de La Araucanía"
    if any(k in u for k in ["BULNES", "YUNGAY", "CHILLÁN", "CHILLAN", "ÑUBLE"]):
        return "Región del Ñuble"
    if any(k in u for k in ["CHÉPICA", "RANCAGUA", "HIGGIN", "COLCHAGUA"]):
        return "Región de O'Higgins"
    if any(k in u for k in ["ANTOFAGASTA", "CALAMA"]):
        return "Región de Antofagasta"
    if any(k in u for k in ["IQUIQUE", "TARAPACÁ", "TARAPACA"]):
        return "Región de Tarapacá"
    if any(k in u for k in ["VALPARAÍSO", "VALPARAISO", "VIÑA", "CATEMU"]):
        return "Región de Valparaíso"
    return "Región Metropolitana"

def extraer_comprador_robusto(celdas, codigo):
    kw = [
        "MUNICIPALIDAD", "SERVICIO DE SALUD", "HOSPITAL",
        "DIRECCION", "CORP", "SERVICIO LOCAL",
        "CARABINEROS", "ARMADA", "CESFAM", "CRS"
    ]
    ex = ["ADQUISICIÓN", "ADQUISICION", "SUMINISTRO", "CONVENIO", "PLACAS", "COMPRA"]
    for idx in [8, 7, 9, 6]:
        if idx < len(celdas):
            val = str(celdas[idx]).strip()
            u = val.upper()
            if val and "COMPRADORA" not in u and not es_codigo_proceso_valido(val) and not es_fecha(val):
                if any(k in u for k in kw):
                    return val
    for c in celdas:
        val = str(c).strip()
        u = val.upper()
        if any(k in u for k in kw) and not any(e in u for e in ex) and not es_codigo_proceso_valido(val) and not es_fecha(val):
            return val
    sig = codigo.split("-")[0] if "-" in codigo else codigo
    return f"Servicio Público ({sig})"

def reparar_y_ordenar_fila_cruda(fila_raw, idx):
    celdas = [str(c).strip() for c in fila_raw] + [""] * 21
    celdas = celdas[:21]
    codigo = f"PROCESO-{idx}"
    for c in celdas:
        if es_codigo_proceso_valido(c
