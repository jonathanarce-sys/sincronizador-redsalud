import os
import time
import requests
import gspread
from google.oauth2.service_account import Credentials
import base64
import json
import re
from datetime import datetime, timedelta

# ==========================================
# 1. IDENTIFICADORES Y CONFIGURACIÓN
# ==========================================
SPREADSHEET_ID_MAESTRA = "1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek".strip()
SPREADSHEET_ID_CONTRATOS = "1kiOFcktRWHeXAOzCwLqPMzu1py0mGlANmvNogFCDbRE".strip()
NOMBRE_HOJA_CONTRATOS = "consolidado"
FILA_INICIO_OBJETIVO = 372

# Credenciales y Endpoint de LicitaLAB
LICITALAB_TOKEN = (
    os.environ.get("LICITALAB_TOKEN") or 
    os.environ.get("LICITALAB_API_KEY") or 
    os.environ.get("TOKEN_LICITALAB") or 
    ""
).strip()

LICITALAB_API_URL = os.environ.get(
    "LICITALAB_API_URL", 
    "https://api.licitalab.cl/v1/licitaciones"
).strip()

# ==========================================
# 2. LISTA BLANCA OFICIAL RUTS REDSALUD
# ==========================================
RUTS_REDSALUD_WHITELIST = {
    "96856000",  # RedSalud S.A. / Servicios Clínicos RedSalud / Casa Matriz (96.856.000-2)
    "76458120",  # RedSalud Dental SpA (76.458.120-3)
    "96536000",  # Clínica RedSalud Providencia / Vitacura / Santiago (96.536.000-8)
    "96543000",  # Clínica RedSalud Valparaíso (96.543.000-6)
    "99568700",  # Centro de Especialidades Médicas Valparaíso / Inversalud (99.568.700-3)
    "96542000",  # Clínica RedSalud Rancagua (96.542.000-0)
    "96537000",  # Clínica RedSalud Mayor Temuco (96.537.000-3)
    "96541000",  # Clínica RedSalud Magallanes (96.541.000-5)
    "96524000",  # Clínica RedSalud Iquique (96.524.000-5)
    "96527000",  # Clínica RedSalud Elqui / La Serena (96.527.000-1)
    "96559000",  # Centros Médicos y Dentales RedSalud (96.559.000-3)
    "76326330",  # Sociedad Médica RedSalud (76.326.330-5)
    "96942400",  # Clínica RedSalud Bicentenario (96.942.400-2)
    "96567920",  # Clínica RedSalud Tabancura (96.567.920-0)
    "96598850",  # Clínica RedSalud Avansalud (96.598.850-0)
    "76906480",  # Megasalud (76.906.480-K)
    "96774580",  # Inversiones RedSalud (96.774.580-4)
}

LICITACIONES_DESCARTADAS_EXPLICITAS = {
    "1464-65-LE26", "3283-9-LE26", "359-115-LE26", "2770-153-LE26",
    "2378-118-LE26", "1063538-37-LR26", "899-58-LE25", "899-27-LE26",
    "1374899-22-LR26", "1017312-1-LP26", "1057540-23-LP26", "1057508-16-LE26",
    "1077499-65-SE26", "1374899-42-LP26", "1656-23-LP26", "1057490-75-LE26",
    "612-43-LE26", "1422825-57-RFI26", "2667-79-LP26", "2667-73-LE26",
    "2107-147-LE26", "1175-74-LP26", "757-80-LE26", "899-38-LP26",
    "899-37-LE26", "857-5-LE26", "1274285-46-LE26", "5512-15-LP26",
    "548874-75-LP26", "1374899-24-LR26"
}

# ==========================================
# 3. AUTENTICACIÓN GOOGLE
# ==========================================
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
            if any(x in ek.upper() for x in ["GCP", "GOOGLE_CRED", "SERVICE_ACCOUNT"]) and ev.strip():
                val = ev.strip()
                break
    if not val:
        raise ValueError("Sin credenciales GCP en el entorno.")
    try:
        pad = len(val) % 4
        if pad:
            val += "=" * (4 - pad)
        dec = base64.b64decode(val)
        creds_dict = json.loads(dec.decode("utf-8"))
    except Exception:
        creds_dict = json.loads(val)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    sa_email = creds_dict.get("client_email", "Email no identificado")
    client = gspread.authorize(Credentials.from_service_account_info(creds_dict, scopes=scopes))
    return client, sa_email

# ==========================================
# 4. FASE 1: DESCARGA DESDE LICITALAB HACIA BASE MADRE
# ==========================================
def actualizar_base_madre_licitalab(sheet_maestra):
    print("--- FASE 1: Conexión y descarga desde LicitaLAB hacia Base Madre ---", flush=True)
    
    if not LICITALAB_TOKEN:
        print("AVISO: No se detectó 'LICITALAB_TOKEN' en los Secrets de GitHub.", flush=True)
        print("Por favor agrega el secreto 'LICITALAB_TOKEN' con la clave entregada por LicitaLAB.", flush=True)
        return

    datos_actuales = sheet_maestra.get_all_values()
    codigos_existentes = set()
    for fila in datos_actuales[1:]:
        if len(fila) > 1 and fila[1].strip():
            codigos_existentes.add(fila[1].strip().upper())
            
    print(f"Base Madre contiene actualmente {len(codigos_existentes)} licitaciones únicas.", flush=True)

    headers = {
        "Authorization": f"Bearer {LICITALAB_TOKEN}",
        "Accept": "application/json",
        "User-Agent": "RedSalud-Sync/1.0"
    }

    endpoints_a_probar = [
        LICITALAB_API_URL,
        "https://api.licitalab.cl/v1/licitaciones",
        "https://api.licitalab.cl/api/licitaciones"
    ]

    items_licitalab = []
    exito = False

    for url in endpoints_a_probar:
        try:
            print(f"Consultando LicitaLAB en: {url}...", flush=True)
            resp = requests.get(url, headers=headers
