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
# 1. IDENTIFICADORES Y CONFIGURACION
# ==========================================
SPREADSHEET_ID_MAESTRA = "1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek".strip()
SPREADSHEET_ID_CONTRATOS = "1kiOFcktRWHeXAOzCwLqPMzu1py0mGlANmvNogFCDbRE".strip()
NOMBRE_HOJA_CONTRATOS = "consolidado"

# Fila 434 contiene "San Antonio"; las nuevas cargas parten en la fila 435
FILA_INICIO_OBJETIVO = 435

LICITALAB_TOKEN = (
    os.environ.get("LICITALAB_TOKEN") or 
    os.environ.get("LICITALAB_API_KEY") or 
    os.environ.get("TOKEN_LICITALAB") or 
    ""
).strip()

MERCADOPUBLICO_TICKET = (
    os.environ.get("MERCADOPUBLICO_TICKET") or
    os.environ.get("MP_TICKET") or
    ""
).strip()

LICITALAB_API_URL = os.environ.get(
    "LICITALAB_API_URL", 
    "https://biapi.licitalab.cl/bi/v2/opportunities"
).strip()

# ==========================================
# 2. CATALOGO OFICIAL DE RUTS Y FILIALES REDSALUD
# ==========================================
# Mapeo directo: RUT base (sin DV ni puntos) -> (Nombre Oficial Filial, RUT Formateado)
MAPA_RUT_FILIAL_REDSALUD = {
    "99533790": ("Clínica RedSalud Elqui", "99.533.790-8"),
    "96543000": ("Clínica RedSalud Valparaíso", "96.543.000-6"),
    "99568700": ("Centro de Especialidades Médicas Valparaíso", "99.568.700-3"),
    "96542000": ("Clínica RedSalud Rancagua", "96.542.000-0"),
    "96537000": ("Clínica RedSalud Mayor Temuco", "96.537.000-3"),
    "96541000": ("Clínica RedSalud Magallanes", "96.541.000-5"),
    "96536000": ("Clínica RedSalud Providencia", "96.536.000-8"),
    "78053560": ("Clínica RedSalud Vitacura", "78.053.560-1"),
    "96524000": ("Clínica RedSalud Santiago", "96.524.000-2"),
    "96598850": ("Centros Médicos RedSalud Iquique", "96.598.850-0"),
    "76458120": ("RedSalud Dental SpA", "76.458.120-3"),
    "96856000": ("Centros Médicos RedSalud", "96.856.000-2"),
}

RUTS_REDSALUD_WHITELIST = set(MAPA_RUT_FILIAL_REDSALUD.keys()) | {
    "96527000", "96559000", "76326330", "96942400", "96567920",
    "76906480", "96774580", "76181326", "76207967", "78918290",
    "88611600", "76124062", "99568720", "96680980", "76110809",
    "76046416", "78040520"
}

ADJUDICACIONES_FORZADAS_REDSALUD = [
    "2145-65-LE26",
    "2704-72-LE26",
    "2548-81-LE26",
    "1057489-264-LE26",
    "2101-140-LE26",
    "5594-10-LR26",
    "1057404-77-LR26",
    "2704-58-L126",
    "3130-23-LE26",
    "5594-8-LP26",
    "3934-20-L126",
    "3934-19-CO26",
    "2792-8-LE26",
    "1057547-323-LP26",
    "1667-19-LP26",
    "5056-82-LP26",
    "1952-55-LP26",
    "1017312-11-LE26",
    "1017312-10-LP26",
    "1017312-9-LP26",
    "1057492-84-LR26",
    "1240099-5-LR26",
    "812261-32-LR26",
    "2446-139-LE26",
    "1057492-2-LR25"
]

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
# 3. AUTENTICACION GOOGLE
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

def normalizar_tipo_proceso(tipo_raw, codigo):
    t = str(tipo_raw).strip().upper()
    c = str(codigo).strip().upper()
    if "AGIL" in t or "ÁGIL" in t or "COT" in c or "-COT" in c:
        return "Compra Ágil"
    return "Licitación Pública"

# ==========================================
# 4. CONSULTA PUNTUAL A MERCADO PUBLICO / LICITALAB
# ==========================================
def consultar_detalle_mercado_publico(codigo_lic):
    if not MERCADOPUBLICO_TICKET:
        return None
    url = "https://api.mercadopublico.cl/servicios/v1/publico/licitaciones.json"
    params = {"codigo": codigo_lic, "ticket": MERCADOPUBLICO_TICKET}
    try:
        resp = requests.get(url, params=params, timeout=25)
        if resp.status_code == 200:
            data = resp.json()
            listado = data.get("Listado") or []
            if listado and isinstance(listado, list):
                lic = listado[0]
                comp_obj = lic.get("Comprador") or {}
                nombre_org = str(comp_obj.get("NombreOrganismo") or comp_obj.get("NombreUnidad") or "").strip()
                region_org = str(comp_obj.get("RegionUnidad") or "").strip()
                rut_org = str(comp_obj.get("RutUnidad") or "").strip()
                nombre_lic = str(lic.get("Nombre") or "").strip()
                estado_lic = str(lic.get("Estado") or "Adjudicada").strip()
                
                adj_info = []
                items_obj = lic.get("Items") or {}
                listado_items = items_obj.get("Listado") or []
                suma_monto = 0
                for it in listado_items:
                    adj = it.get("Adjudicacion") or {}
                    if adj:
                        prov = str(adj.get("NombreProveedor") or "").strip()
                        rut_p = str(adj.get("RutProveedor") or "").strip()
                        etiqueta = f"{prov} ({rut_p})".strip()
                        if etiqueta and etiqueta not in adj_info:
                            adj_info.append(etiqueta)
                        m_unit = adj.get("MontoUnitario") or 0
                        cant = adj.get("Cantidad") or 1
                        try:
                            suma_monto += float(m_unit) * float(cant)
                        except Exception:
                            pass
                monto_total = str(int(round(suma_monto))) if suma_monto > 0 else ""

                return {
                    "codigo": codigo_lic.upper(),
                    "nombre": nombre_lic,
                    "comprador": nombre_org,
                    "rut_comprador": rut_org,
                    "region": region_org,
                    "estado": estado_lic,
                    "adjudicatario": " | ".join(adj_info),
                    "monto": monto_total
                }
    except Exception as e:
        print(f"  [MP API] Error consultando {codigo_lic}: {repr(e)}", flush=True)
    return None

def consultar_detalle_licitalab(codigo_lic):
    if not LICITALAB_TOKEN:
        return None
    headers = {
        "x-api-key": LICITALAB_TOKEN,
        "Accept": "application/json",
        "User-Agent": "RedSalud-Sync/1.0"
    }
    for param_key in ("code", "search", "q"):
        try:
            resp = requests.get(LICITALAB_API_URL, headers=headers, params={param_key: codigo_lic}, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                items = data if isinstance(data, list) else (data.get("data") or data.get("opportunities") or data.get("items") or data.get("results") or [])
                for it in items:
                    c = str(it.get("OPPORTUNITY_CODE") or it.get("code") or it.get("codigo") or "").strip().upper()
                    if c == codigo_lic.upper():
                        monto_raw = it.get("TOTAL_AWARDED_AMOUNT") if it.get("TOTAL_AWARDED_AMOUNT") is not None else it.get("AVAILABLE_AMOUNT")
                        monto = str(int(monto_raw)) if isinstance(monto_raw, (int, float)) else str(monto_raw or "").strip()
                        return {
                            "codigo": c,
                            "nombre": str(it.get("OPPORTUNITY_NAME") or it.get("name") or "").strip(),
                            "comprador": str(it.get("ORGANISM") or it.get("buyer") or "").strip(),
                            "rut_comprador": "",
                            "region": str(it.get("REGION") or it.get("region") or "").strip(),
                            "estado": str(it.get("OPPORTUNITY_STATUS") or it.get("status") or "Adjudicada").strip(),
                            "adjudicatario": str(it.get("AWARDED_PROVIDERS") or it.get("award") or "").strip(),
                            "monto": monto
                        }
        except Exception:
            pass
    return None

# ==========================================
# 5. FASE 1: DESCARGA CON CAMPOS EXACTOS DE LICITALAB BI API
# ==========================================
def actualizar_base_madre_licitalab(sheet_maestra):
    print("--- FASE 1: Conectando a LicitaLAB API BI ---", flush=True)
    if not LICITALAB_TOKEN:
        print("AVISO: No se detecto 'LICITALAB_TOKEN' en los Secrets de GitHub.", flush=True)
        return

    datos_actuales = sheet_maestra.get_all_values()
    if not datos_actuales:
        print("Error: Base Madre no tiene datos.", flush=True)
        return

    cabecera = datos_actuales[0]
    total_cols = max(len(cabecera), 20)

    codigos_existentes = set()
    for fila in datos_actuales[1:]:
        if len(fila) > 1 and fila[1].strip():
            m = re.findall(r"\b\d{3,8}-\d{1,5}-[A-Za-z0-9]+\b", fila[1])
            if m:
                codigos_existentes.add(m[0].upper())
            else:
                codigos_existentes.add(fila[1].strip().upper())

    print(f"Base Madre historica: {len(codigos_existentes)} licitaciones existentes registradas.", flush=True)

    headers = {
        "x-api-key": LICITALAB_TOKEN,
        "Accept": "application/json",
        "User-Agent": "RedSalud-Sync/1.0"
    }

    fecha_delta = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%dT00:00:00Z")
    params = {"since": fecha_delta}

    items_licitalab = []
    try:
        resp = requests.get(LICITALAB_API_URL, headers=headers, params=params, timeout=40)
        if resp.status_code == 200:
            data = resp.json()
            items_licitalab = data if isinstance(data, list) else (data.get("data") or data.get("opportunities") or data.get("items") or data.get("results") or [])
            print(f"LicitaLAB BI: {len(items_licitalab)} registros recibidos con since={fecha_delta}.", flush=True)
        else:
            print(f"Error LicitaLAB HTTP {resp.status_code}: {resp.text[:120]}", flush=True)
    except Exception as e:
        print(f"Error consultando LicitaLAB: {repr(e)}", flush=True)

    if not items_licitalab:
        print("Fase 1: No se recibieron datos nuevos de LicitaLAB.", flush=True)
        return

    filas_nuevas = []
    rechazados_existentes = 0
    rechazados_incompletos = 0

    for item in items_licitalab:
        if not isinstance(item, dict):
            continue

        cod = str(item.get("OPPORTUNITY_CODE") or item.get("code") or item.get("codigo") or "").strip().upper()
        if not cod:
            rechazados_incompletos += 1
            continue

        if cod in codigos_existentes:
            rechazados_existentes += 1
            continue

        comprador = str(item.get("ORGANISM") or item.get("buyer") or "").strip()
        region = str(item.get("REGION") or item.get("region") or "").strip()

        if not comprador:
            rechazados_incompletos += 1
            continue

        item_id = str(item.get("OPPORTUNITY_ID") or item.get("id") or "")
        nombre = str(item.get("OPPORTUNITY_NAME") or item.get("name") or "").strip()
        categoria = str(item.get("B_LINE_TITLE") or item.get("B_LINE") or item.get("category") or "Salud").strip()
        fecha_pub = str(item.get("PUBLISH_DATE") or item.get("published_
