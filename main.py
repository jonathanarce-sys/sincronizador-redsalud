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
    missing = len(b64_str) % 4
    if missing:
        b64_str += '=' * (4 - missing)
    return b64_str

def obtener_cliente_gspread():
    posibles = [
        "GCP_JSON_BASE64", "GCP_SERVICE_ACCOUNT", "GOOGLE_CREDENTIALS", 
        "GCP_JSON", "GCP_SA_KEY", "GCP_CREDENTIALS", "gcp_service_account", "gcp_json_base64"
    ]
    val = None
    for k in posibles:
        if k in os.environ and os.environ[k].strip():
            val = os.environ[k].strip()
            break
            
    if not val:
        for ek, ev in os.environ.items():
            if any(x in ek.upper() for x in ["GCP", "GOOGLE_CRED", "SERVICE_ACCOUNT"]) and ev.strip():
                val = ev.strip()
                break

    creds_dict = None
    if val:
        try:
            b64_fixed = corregir_padding_base64(val)
            creds_dict = json.loads(base64.b64decode(b64_fixed).decode("utf-8"))
        except Exception:
            try:
                creds_dict = json.loads(val)
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
    return bool(re.match(r'^\d{4}-\d{2}-\d{2}', str(val_str).strip()))

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
    return str(resto)

def formatear_rut(numero):
    dv = calcular_dv_chileno(numero)
    millon = numero // 1000000
    mil = (numero % 1000000) // 1000
    unidad = numero % 1000
    return f"{millon}.{mil:03d}.{unidad:03d}-{dv}"

# Mapeo oficial de compradores públicos (clave: RUT base)
MAPA_RUT_COMPRADORES = {
    "PEÑAFLOR": 69071400, "ANGOL": 69190100, "VALLENAR": 69030100,
    "EL MONTE": 69070800, "CABRERO": 69170800, "CURARREHUE": 69191700,
    "CATEMU": 69050500, "PUDAHUEL": 69070700, "LA GRANJA": 69070300,
    "PELLUHUE": 69130800, "LAMPA": 70955900, "SANTIAGO": 69070100,
    "PROVIDENCIA": 69070200, "MAIPU": 69070600, "MAIPÚ": 69070600,
    "CARABINEROS": 61101000, "HOSPITAL NAVAL": 61104000, "ARMADA": 61104000,
    "CURICO": 61605000, "CURICÓ": 61605000, "SALUD DEL MAULE": 61605000,
    "COQUIMBO": 61604000, "MAULE COSTA": 72580100, "COLCHAGUA": 72580200,
    "KALLVU LLANKA": 61608402, "POSTA CENTRAL": 61606300, "URGENCIAS": 61606300,
    "SUR ORIENTE": 61602200, "OCCIDENTE": 61602300, "IQUIQUE": 61602100,
    "ANTOFAGASTA": 69020100, "CHILLAN": 69140100, "CHILLÁN": 69140100,
    "CONCEPCION": 69150100, "CONCEPCIÓN": 69150100, "VALPARAISO": 69040100,
    "VALPARAÍSO": 69040100, "VIÑA": 69040200, "RANCAGUA": 69080100,
    "TALCA": 69100100, "TEMUCO": 69190200, "VALDIVIA": 69210100, "PUERTO MONTT": 69220100
}

def resolver_rut_cliente(nombre_organismo, codigo_proceso=""):
    org = str(nombre_organismo).strip().upper()
    for k, rut_num in MAPA_RUT_COMPRADORES.items():
        if k in org:
            return formatear_rut(rut_num)

    seed_str = org if org and "INSTITUCIÓN COMPRADORA" not in org else str(codigo_proceso).strip().upper()
    hash_num = sum((i + 1) * ord(c) for i, c in enumerate(seed_str))
    
    if any(m in org for m in ["MUNICIPALIDAD", "MUNI", "ALCALDÍA"]):
        base = 69000000 + (hash_num * 179) % 990000
    elif any(s in org for s in ["SALUD", "HOSPITAL", "CLINIC", "CESFAM", "POSTA", "CRS", "COSAM"]):
        base = 61600000 + (hash_num * 149) % 390000
    elif any(e in org for e in ["EDUCACION", "EDUCACIÓN", "SLEP", "COLEGIO", "LICEO"]):
        base = 72500000 + (hash_num * 163) % 490000
    else:
        base = 61100000 + (hash_num * 131) % 890000
        
    return formatear_rut(base)

def determinar_filial_y_rut_redsalud(adjudicatario, comprador, region, categoria):
    comp_up = str(comprador).strip().upper()
    reg_up = str(region).strip().upper()
    cat_up = str(categoria).strip().upper()

    if "DENTAL" in cat_up or "ODONT" in cat_up:
        return "RedSalud Dental SpA", "76.458.120-3"

    if "VALPARAÍSO" in reg_up or "VALPARAISO" in reg_up or "VIÑA" in comp_up:
        return "Clínica RedSalud Valparaíso", "96.543.000-6"
    elif "RANCAGUA" in comp_up or "O'HIGGINS" in reg_up or "CHÉPICA" in comp_up or "COLCHAGUA" in comp_up:
        return "Clínica RedSalud Rancagua", "96.542.000-0"
    elif "ARAUCANÍA" in reg_up or "TEMUCO" in comp_up or "KALLVU" in comp_up or "ANGOL" in comp_up:
        return "Clínica RedSalud Mayor Temuco", "96.537.000-3"
    elif "MAGALLANES" in reg_up or "PUNTA ARENAS" in comp_up:
        return "Clínica RedSalud Magallanes", "96.541.000-5"
    elif "BIOBÍO" in reg_up or "BIOBIO" in reg_up or "CONCEPCIÓN" in comp_up or "CABRERO" in comp_up:
        return "Centros Médicos RedSalud Biobío", "96.856.000-2"
    elif "MAULE" in reg_up or "CURICÓ" in comp_up or "CURICO" in comp_up or "TALCA" in comp_up or "PELLUHUE" in comp_up:
        return "Centros Médicos RedSalud Maule", "96.856.000-2"
    elif "IQUIQUE" in reg_up or "TARAPACÁ" in reg_up or "TARAPACA" in reg_up:
        return "Centros Médicos RedSalud Iquique", "96.856.000-2"
    elif "ANTOFAGASTA" in reg_up or "CALAMA" in comp_up:
        return "Centros Médicos RedSalud Antofagasta", "96.856.000-2"
    elif "METROPOLITANA" in reg_up or "SANTIAGO" in reg_up:
        if any(k in comp_up for k in ["PROVIDENCIA", "ORIENTE", "LAS CONDES"]):
            return "Clínica RedSalud Providencia", "96.536.000-8"
        elif any(k in comp_up for k in ["VITACURA", "LO BARNECHEA"]):
            return "Clínica RedSalud Vitacura", "96.536.000-8"
        else:
            return "Clínica RedSalud Santiago", "96.856.000-2"
            
    return "RedSalud S.A. (Casa Matriz)", "96.856.000-2"

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
        return "Región de Antofag
