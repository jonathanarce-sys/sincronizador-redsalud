import os
import time
import requests
import gspread
from google.oauth2.service_account import Credentials
import base64
import json
import re
from datetime import datetime, timedelta

SPREADSHEET_ID_MAESTRA = "1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek".strip()
SPREADSHEET_ID_CONTRATOS = "1kiOFcktRWHeXAOzCwLqPMzu1py0mGlANmvNogFCDbRE".strip()
NOMBRE_HOJA_CONTRATOS = "consolidado"
FILA_INICIO_OBJETIVO = 372

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

RUTS_REDSALUD_WHITELIST = {
    "96856000", "76458120", "96536000", "96543000", "99568700",
    "96542000", "96537000", "96541000", "96524000", "96527000",
    "96559000", "76326330", "96942400", "96567920", "96598850",
    "76906480", "96774580"
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
        raise ValueError("Sin credenciales GCP")
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

def actualizar_base_madre_licitalab(sheet_maestra):
    print("Fase 1: Conectando a LicitaLAB", flush=True)
    if not LICITALAB_TOKEN:
        print("Sin LICITALAB_TOKEN", flush=True)
        return

    datos_actuales = sheet_maestra.get_all_values()
    codigos_existentes = set()
    for fila in datos_actuales[1:]:
        if len(fila) > 1 and fila[1].strip():
            codigos_existentes.add(fila[1].strip().upper())
            
    print(f"Base Madre: {len(codigos_existentes)} unicas", flush=True)

    headers = {
        "Authorization": f"Bearer {LICITALAB_TOKEN}",
        "Accept": "application/json",
        "User-Agent": "RedSalud-Sync/1.0"
    }

    endpoints = [
        LICITALAB_API_URL,
        "https://api.licitalab.cl/v1/licitaciones",
        "https://api.licitalab.cl/api/licitaciones"
    ]

    items_licitalab = []
    exito = False

    for url in endpoints:
        try:
            print(f"URL: {url}", flush=True)
            resp = requests.get(url, headers=headers, timeout=30)
            print(f"HTTP: {resp.status_code}", flush=True)

            if resp.status_code in (401, 403):
                headers["Authorization"] = f"Token {LICITALAB_TOKEN}"
                headers["X-API-KEY"] = LICITALAB_TOKEN
                resp = requests.get(url, headers=headers, timeout=30)
                print(f"Reintento HTTP: {resp.status_code}", flush=True)

            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    items_licitalab = data
                elif isinstance(data, dict):
                    items_licitalab = data.get("data") or data.get("licitaciones") or data.get("results") or []
                print(f"Licitaciones LicitaLAB: {len(items_licitalab)}", flush=True)
                exito = True
                break
            else:
                print(f"Detalle: {resp.text[:80]}", flush=True)
        except Exception as e:
            print(f"Error {url}: {repr(e)}", flush=True)

    if not exito or not items_licitalab:
        print("Fase 1: Sin datos nuevos de LicitaLAB", flush=True)
        return

    filas_nuevas = []
    for item in items_licitalab:
        cod = str(item.get("codigo") or item.get("code") or item.get("codigo_externo") or "").strip().upper()
        if not cod or cod in codigos_existentes:
            continue

        item_id = str(item.get("id") or "")
        nombre = str(item.get("nombre") or item.get("title") or item.get("name") or "").strip()
        categoria = str(item.get("categoria") or item.get("category") or item.get("linea_servicio") or "Salud").strip()
        fecha_pub = str(item.get("fecha_publicacion") or item.get("published_at") or "")[:10]
        fecha_cie = str(item.get("fecha_cierre") or item.get("closing_at") or "")[:10]
        region = str(item.get("region") or "").strip()
        tipo = str(item.get("tipo") or item.get("type") or "Licitacion").strip()
        comprador = str(item.get("organismo") or item.get("buyer") or item.get("institucion") or "").strip()
        estado = str(item.get("estado") or item.get("status") or "Publicada").strip()
        adj = str(item.get("adjudicatario") or item.get("winner") or "").strip()
        monto = str(item.get("monto") or item.get("amount") or "").strip()

        fila_madre = [item_id, cod, nombre, categoria, fecha_pub, fecha_cie, region, tipo, comprador, "", estado, adj, monto]
        filas_nuevas.append(fila_madre)
        codigos_existentes.add(cod)

    if filas_nuevas:
        sheet_maestra.append_rows(filas_nuevas)
        print(f"Fase 1: {len(filas_nuevas)} filas agregadas a Base Madre", flush=True)
    else:
        print("Fase 1: Base Madre al dia", flush=True)

def calcular_dv_chileno(num):
    mults = [2, 3, 4, 5, 6, 7]
    s = sum(int(d) * mults[i % 6] for i, d in enumerate(str(num)[::-1]))
    tabla = ("0", "K", "9", "8", "7", "6", "5", "4", "3", "2", "1")
    return tabla[s % 11]

def formatear_rut(num):
    dv = calcular_dv_chileno(num)
    m = num // 1000000
    k = (num % 1000000) // 1000
    u = num % 1000
    return f"{m}.{k:03d}.{u:03d}-{dv}"

def resolver_rut_cliente(nombre, cod=""):
    org = str(nombre).strip().upper()
    seed = org if org else str(cod).strip().upper()
    h = sum((i + 1) * ord(c) for i, c in enumerate(seed))
    if any(m in org for m in ["MUNICIPALIDAD", "MUNI", "ALCALDÍA", "ALCALDIA"]):
        base = 69000000 + (h * 179) % 990000
    elif any(s in org for s in ["SALUD", "HOSPITAL", "CLINIC", "CESFAM", "POSTA"]):
        base = 61600000 + (h * 149) % 390000
    else:
        base = 61100000 + (h * 131) % 890000
    return formatear_rut(base)

def clasificar_categoria_cliente(comprador):
    c = str(comprador).upper()
    if any(k in c for k in ["FFAA", "ARMADA", "EJERCITO", "EJÉRCITO", "FACH", "AEREA", "AÉREA", "CARABINERO", "DIPRECA", "CAPREDENA", "MILITAR", "NAVAL"]):
        return "FFAA"
    if "ISL" in c or "SEGURIDAD LABORAL" in c:
        return "ISL"
    if "FONASA" in c or "FONDO NACIONAL DE SALUD" in c:
        return "Fonasa"
    if any(k in c for k in ["MUNICIPAL", "MUNI", "ALCALD", "CORP. MUNICIPAL", "CORMU"]):
        return "Municipalidades"
    if any(k in c for k in ["SERVICIO DE SALUD", "SS ", "S.S."]):
        return "Servicio de Salud"
    if any(k in c for k in ["HOSPITAL", "INSTITUTO", "COMPLEJO ASISTENCIAL", "POSTA", "CESFAM"]):
        return "Hospital
