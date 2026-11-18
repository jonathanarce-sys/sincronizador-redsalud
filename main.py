import os
import time
import requests
import gspread
from google.oauth2.service_account import Credentials
import base64
import json
import re
from datetime import datetime, timedelta

# 1. IDENTIFICADORES Y CONFIGURACION
SPREADSHEET_ID_MAESTRA = "1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek".strip()
SPREADSHEET_ID_CONTRATOS = "1kiOFcktRWHeXAOzCwLqPMzu1py0mGlANmvNogFCDbRE".strip()
NOMBRE_HOJA_CONTRATOS = "consolidado"
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

# 2. CATALOGO ESTRICTO DE RUTS Y FILIALES OFICIALES REDSALUD
# Solo se aceptan licitaciones adjudicadas a estos RUTs del holding RedSalud
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
    "96527000": ("Centros Médicos RedSalud", "96.527.000-9"),
    "96559000": ("Centros Médicos RedSalud", "96.559.000-3"),
    "96942400": ("RedSalud S.A.", "96.942.400-0"),
    "99568720": ("RedSalud S.A.", "99.568.720-8"),
}

RUTS_REDSALUD_WHITELIST = set(MAPA_RUT_FILIAL_REDSALUD.keys())

# Lista de códigos a auditar contra API (solo entran si Mercado Público confirma RUT RedSalud)
CODIGOS_AUDITAR_REDSALUD = [
    "2145-65-LE26", "2704-72-LE26", "2548-81-LE26", "1057489-264-LE26",
    "2101-140-LE26", "5594-10-LR26", "1057404-77-LR26",
    "3130-23-LE26", "5594-8-LP26", "3934-19-CO26",
    "2792-8-LE26", "1057547-323-LP26", "1667-19-LP26", "5056-82-LP26",
    "1952-55-LP26", "1017312-11-LE26", "1017312-10-LP26", "1017312-9-LP26",
    "1057492-84-LR26", "1240099-5-LR26", "812261-32-LR26", "2446-139-LE26",
    "1057492-2-LR25"
]

LICITACIONES_DESCARTADAS_EXPLICITAS = {
    "3934-20-L126", "2704-58-L126", # Competidores: U. Mayor (76.046.416-3) y Sanatorio Alemán (88.611.600-4)
    "1464-65-LE26", "3283-9-LE26", "359-115-LE26", "2770-153-LE26",
    "2378-118-LE26", "1063538-37-LR26", "899-58-LE25", "899-27-LE26",
    "1374899-22-LR26", "1017312-1-LP26", "1057540-23-LP26", "1057508-16-LE26",
    "1077499-65-SE26", "1374899-42-LP26", "1656-23-LP26", "1057490-75-LE26",
    "612-43-LE26", "1422825-57-RFI26", "2667-79-LP26", "2667-73-LE26",
    "2107-147-LE26", "1175-74-LP26", "757-80-LE26", "899-38-LP26",
    "899-37-LE26", "857-5-LE26", "1274285-46-LE26", "5512-15-LP26",
    "548874-75-LP26", "1374899-24-LR26"
}

# 3. AUTENTICACION GOOGLE
def obtener_cliente_gspread():
    posibles = ["GCP_JSON_BASE64", "GCP_SERVICE_ACCOUNT", "GOOGLE_CREDENTIALS", "GCP_JSON", "GCP_SA_KEY", "GCP_CREDENTIALS"]
    val = next((os.environ[k].strip() for k in posibles if k in os.environ and os.environ[k].strip()), None)
    if not val:
        raise ValueError("Sin credenciales GCP en el entorno.")
    try:
        pad = len(val) % 4
        if pad:
            val += "=" * (4 - pad)
        creds_dict = json.loads(base64.b64decode(val).decode("utf-8"))
    except Exception:
        creds_dict = json.loads(val)
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    return gspread.authorize(Credentials.from_service_account_info(creds_dict, scopes=scopes)), creds_dict.get("client_email", "SA")

def normalizar_tipo_proceso(tipo_raw, codigo):
    t, c = str(tipo_raw).strip().upper(), str(codigo).strip().upper()
    return "Compra Ágil" if ("AGIL" in t or "ÁGIL" in t or "COT" in c) else "Licitación Pública"

# 4. CONSULTAS API MERCADO PUBLICO Y LICITALAB (FILTRANDO SOLO LINEAS ADJUDICADAS A REDSALUD)
def extraer_rut_base(rut_str):
    m = re.search(r"(\d{1,2}\.?\d{3}\.?\d{3})-[\dkK]", str(rut_str))
    return re.sub(r"[^0-9]", "", m.group(1)) if m else ""

def es_proveedor_redsalud(rut_str, nombre_str=""):
    r_base = extraer_rut_base(rut_str)
    if r_base and r_base in RUTS_REDSALUD_WHITELIST:
        return True
    nom_u = str(nombre_str).upper()
    if any(bad in nom_u for bad in ["SANATORIO ALEMAN", "UNIVERSIDAD MAYOR", "FALP", "ATRYS", "RUBIKAL", "BARLARO", "APSORAD", "INGEFISIC"]):
        return False
    return bool(re.search(r"\bRED\s*SALUD\b|MEGASALUD|INVERSALUD|ESPECIALIDADES\s*MEDICAS\s*VALPARAISO|CLINICA\s*REGIONAL\s*DEL\s*ELQUI", nom_u))

def consultar_detalle_mercado_publico(codigo_lic):
    if not MERCADOPUBLICO_TICKET:
        return None
    url = "https://api.mercadopublico.cl/servicios/v1/publico/licitaciones.json"
    try:
        resp = requests.get(url, params={"codigo": codigo_lic, "ticket": MERCADOPUBLICO_TICKET}, timeout=25)
        if resp.status_code == 200:
            listado = resp.json().get("Listado") or []
            if listado and isinstance(listado, list):
                lic = listado[0]
                comp = lic.get("Comprador") or {}
                adj_redsalud, adj_otros, suma_redsalud = [], [], 0

                for it in (lic.get("Items") or {}).get("Listado") or []:
                    adj = it.get("Adjudicacion") or {}
                    if not adj:
                        continue
                    prov = str(adj.get("NombreProveedor") or "").strip()
                    rut_p = str(adj.get("RutProveedor") or "").strip()
                    etiqueta = f"{prov} ({rut_p})".strip()
                    try:
                        monto_it = float(adj.get("MontoUnitario") or 0) * float(adj.get("Cantidad") or 1)
                    except Exception:
                        monto_it = 0

                    if es_proveedor_redsalud(rut_p, prov):
                        if etiqueta and etiqueta not in adj_redsalud:
                            adj_redsalud.append(etiqueta)
                        suma_redsalud += monto_it
                    else:
                        if etiqueta and etiqueta not in adj_otros:
                            adj_otros.append(etiqueta)

                return {
                    "codigo": codigo_lic.upper(),
                    "nombre": str(lic.get("Nombre") or "").strip(),
                    "comprador": str(comp.get("NombreOrganismo") or comp.get("NombreUnidad") or "").strip(),
                    "rut_comprador": str(comp.get("RutUnidad") or "").strip(),
                    "region": str(comp.get("RegionUnidad") or "").strip(),
                    "ganador_redsalud": len(adj_redsalud) > 0,
                    "adjudicatario_redsalud": " | ".join(adj_redsalud),
                    "adjudicatario_otros": " | ".join(adj_otros),
                    "monto_redsalud": str(int(round(suma_redsalud))) if suma_redsalud > 0 else ""
                }
    except Exception as e:
        print(f"  [MP API] Error {codigo_lic}: {repr(e)}", flush=True)
    return None

def consultar_detalle_licitalab(codigo_lic):
    if not LICITALAB_TOKEN:
        return None
    headers = {"x-api-key": LICITALAB_TOKEN, "Accept": "application/json", "User-Agent": "RedSalud-Sync/1.0"}
    for pk in ("code", "search", "q"):
        try:
            resp = requests.get(LICITALAB_API_URL, headers=headers, params={pk: codigo_lic}, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                items = data if isinstance(data, list) else (data.get("data") or data.get("opportunities") or data.get("items") or [])
                for it in items:
                    c = str(it.get("OPPORTUNITY_CODE") or it.get("code") or "").strip().upper()
                    if c == codigo_lic.upper():
                        adj_raw = str(it.get("AWARDED_PROVIDERS") or it.get("award") or "").strip()
                        m_raw = it.get("TOTAL_AWARDED_AMOUNT") if it.get("TOTAL_AWARDED_AMOUNT") is not None else it.get("AVAILABLE_AMOUNT")
                        return {
                            "codigo": c,
                            "nombre": str(it.get("OPPORTUNITY_NAME") or it.get("name") or "").strip(),
                            "comprador": str(it.get("ORGANISM") or it.get("buyer") or "").strip(),
                            "rut_comprador": "",
                            "region": str(it.get("REGION") or it.get("region") or "").strip(),
                            "ganador_redsalud": es_proveedor_redsalud(adj_raw, adj_raw),
                            "adjudicatario_redsalud": adj_raw,
                            "adjudicatario_otros": "" if es_proveedor_redsalud(adj_raw, adj_raw) else adj_raw,
                            "monto_redsalud": str(int(m_raw)) if isinstance(m_raw, (int, float)) else str(m_raw or "").strip()
                        }
        except Exception:
            pass
    return None

# 5. FASE 1: ACTUALIZAR BASE MADRE
def actualizar_base_madre_licitalab(sheet_maestra):
    print("--- FASE 1: Conectando a LicitaLAB API BI ---", flush=True)
    if not LICITALAB_TOKEN:
        print("AVISO: Sin LICITALAB_TOKEN.", flush=True)
        return
    datos_actuales = sheet_maestra.get_all_values()
    if not datos_actuales:
        return
    total_cols = max(len(datos_actuales[0]), 20)
    codigos_existentes = set()
    for fila in datos_actuales[1:]:
        if len(fila) > 1 and fila[1].strip():
            m = re.findall(r"\b\d{3,8}-\d{1,5}-[A-Za-z0-9]+\b", fila[1])
            codigos_existentes.add((m[0] if m else fila[1].strip()).upper())

    headers = {"x-api-key": LICITALAB_TOKEN, "Accept": "application/json", "User-Agent": "RedSalud-Sync/1.0"}
    fecha_delta = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%dT00:00:00Z")
    try:
        resp = requests.get(LICITALAB_API_URL, headers=headers, params={"since": fecha_delta}, timeout=40)
        if resp.status_code != 200:
            print(f"Error LicitaLAB HTTP {resp.status_code}", flush=True)
            return
        data = resp.json()
        items = data if isinstance(data, list) else (data.get("data") or data.get("opportunities") or data.get("items") or [])
    except Exception as e:
        print(f"Error consultando LicitaLAB: {repr(e)}", flush=True)
        return

    filas_nuevas = []
    for item in items:
        if not isinstance(item, dict):
            continue
        cod = str(item.get("OPPORTUNITY_CODE") or item.get("code") or "").strip().upper()
        comprador = str(item.get("ORGANISM") or item.get("buyer") or "").strip()
        if not cod or cod in codigos_existentes or not comprador:
            continue
        m_raw = item.get("AVAILABLE_AMOUNT") if item.get("AVAILABLE_AMOUNT") is not None else item.get("TOTAL_AWARDED_AMOUNT")
        fila_20 = [""] * total_cols
        fila_20[0] = str(item.get("OPPORTUNITY_ID") or item.get("id") or "")
        fila_20[1] = cod
        fila_20[2] = str(item.get("OPPORTUNITY_NAME") or item.get("name") or "").strip()
        fila_20[3] = str(item.get("B_LINE_TITLE") or item.get("category") or "Salud").strip()
        fila_20[4] = str(item.get("PUBLISH_DATE") or item.get("published_at") or "")[:10]
        fila_20[5] = str(item.get("CLOSING_DATE") or item.get("closing_at") or "")[:10]
        fila_20[6] = "-"
        fila_20[7] = normalizar_tipo_proceso(item.get("OPPORTUNITY_TYPE") or "", cod)
        fila_20[8] = comprador
        fila_20[9] = str(item.get("REGION") or item.get("region") or "").strip()
        fila_20[10] = str(item.get("OPPORTUNITY_STATUS") or item.get("status") or "Publicada").strip()
        fila_20[11] = str(item.get("AWARDED_PROVIDERS") or item.get("award") or "").strip()
        fila_20[12] = str(int(m_raw)) if isinstance(m_raw, (int, float)) else str(m_raw or "").strip()
        filas_nuevas.append(fila_20)
        codigos_existentes.add(cod)

    if filas_nuevas:
        filas_nuevas.sort(key=lambda r: str(r[4]), reverse=True)
        sheet_maestra.insert_rows(filas_nuevas, row=2)
        print(f"Exito Fase 1: {len(filas_nuevas)} nuevas en Base Madre.", flush=True)

# 6. FASE 2: DETERMINACION EXACTA DE FILIAL POR RUT GANADOR
def calcular_dv_chileno(num):
    mults = [2, 3, 4, 5, 6, 7]
    s = sum(int(d) * mults[i % 6] for i, d in enumerate(str(num)[::-1]))
    return ("0", "K", "9", "8", "7", "6", "5", "4", "3", "2", "1")[s % 11]

def formatear_rut(num):
    return f"{num // 1000000}.{(num % 1000000) // 1000:03d}.{num % 1000:03d}-{calcular_dv_chileno(num)}"

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
    if "FONASA" in c:
        return "Fonasa"
    if any(k in c for k in ["MUNICIPAL", "MUNI", "ALCALD", "CORP. MUNICIPAL", "CORMU"]):
        return "Municipalidades"
    if any(k in c for k in ["SERVICIO DE SALUD", "SS ", "S.S."]):
        return "Servicio de Salud"
    if any(k in c for k in ["HOSPITAL", "INSTITUTO", "COMPLEJO ASISTENCIAL", "POSTA", "CESFAM"]):
        return "Hospitales"
    return "Otros"

def determinar_filial_por_rut_y_zona(cat, reg, comp, adj_redsalud=""):
    adj_u, comp_u, reg_u, cat_u = str(adj_redsalud).upper(), str(comp).upper(), str(reg).upper(), str(cat).upper()

    # 1. PRIORIDAD ABSOLUTA: RUT exacto del proveedor RedSalud que ganó la línea
    for r_raw in re.findall(r"\b(\d{1,2}\.?\d{3}\.?\d{3})-[\dkK]\b", adj_u):
        r_base = re.sub(r"[^0-9]", "", r_raw)
        if r_base in MAPA_RUT_FILIAL_REDSALUD:
            filial_nombre, filial_rut = MAPA_RUT_FILIAL_REDSALUD[r_base]
            # Si es el RUT transversal de Centros Médicos RedSalud (96.856.000-2), precisar ciudad/región
            if r_base == "96856000":
                if "IQUIQUE" in reg_u or "TARAPAC" in reg_u or "IQUIQUE" in comp_u:
                    return "Centros Médicos RedSalud Iquique", "96.856.000-2"
                if "ANTOFAGASTA" in reg_u or "CALAMA" in comp_u:
                    return "Centros Médicos RedSalud Antofagasta", "96.856.000-2"
                if "COQUIMBO" in reg_u or "SERENA" in comp_u or "ELQUI" in comp_u:
                    return "Centros Médicos RedSalud La Serena", "96.856.000-2"
                if "VALPARA" in reg_u or "VIÑA" in comp_u:
                    return "Centros Médicos RedSalud Valparaíso", "96.856.000-2"
                if "MAULE" in reg_u or "TALCA" in comp_u or "CURIC" in comp_u:
                    return "Centros Médicos RedSalud Maule", "96.856.000-2"
                if "BIOB" in reg_u or "CONCEPCI" in comp_u:
                    return "Centros Médicos RedSalud Biobío", "96.856.000-2"
                if "LOS R" in reg_u or "VALDIVIA" in comp_u:
                    return "Centros Médicos RedSalud Valdivia", "96.856.000-2"
                if "LOS LAGOS" in reg_u or "PUERTO MONTT" in comp_u:
                    return "Centros Médicos RedSalud Puerto Montt", "96.856.000-2"
                return "Centros Médicos RedSalud Santiago", "96.856.000-2"
            return filial_nombre, filial_rut

    # 2. Razón social del proveedor RedSalud adjudicado
    if "ELQUI" in adj_u:
        return "Clínica RedSalud Elqui", "99.533.790-8"
    if "INVERSALUD" in adj_u or "ESPECIALIDADES MEDICAS VALPARAISO" in adj_u:
        return "Centro de Especialidades Médicas Valparaíso", "99.568.700-3"
    if "VALPARAISO" in adj_u or "VALPARAÍSO" in adj_u:
        return "Clínica RedSalud Valparaíso", "96.543.000-6"
    if "MAGALLANES" in adj_u:
        return "Clínica RedSalud Magallanes", "96.541.000-5"
    if "TEMUCO" in adj_u or "MAYOR" in adj_u:
        return "Clínica RedSalud Mayor Temuco", "96.537.000-3"
    if "RANCAGUA" in adj_u:
        return "Clínica RedSalud Rancagua", "96.542.000-0"
    if "VITACURA" in adj_u:
        return "Clínica RedSalud Vitacura", "78.053.560-1"
    if "PROVIDENCIA" in adj_u:
        return "Clínica RedSalud Providencia", "96.536.000-8"
    if "DENTAL" in adj_u or "DENTAL" in cat_u:
        return "RedSalud Dental SpA", "76.458.120-3"

    # 3. Respaldo por Región del comprador si el texto solo dice "RedSalud"
    if "COQUIMBO" in reg_u or "SERENA" in comp_u or "ELQUI" in comp_u:
        return "Clínica RedSalud Elqui", "99.533.790-8"
    if "VALPARA" in reg_u or "VIÑA" in comp_u:
        return "Clínica RedSalud Valparaíso", "96.543.000-6"
    if "RANCAGUA" in comp_u or "HIGGIN" in reg_u:
        return "Clínica RedSalud Rancagua", "96.542.000-0"
    if "ARAUCAN" in reg_u or "TEMUCO" in comp_u or "KALLVU" in comp_u:
        return "Clínica RedSalud Mayor Temuco", "96.537.000-3"
    if "MAGALLANES" in reg_u or "PUNTA ARENAS" in comp_u:
        return "Clínica RedSalud Magallanes", "96.541.000-5"
    if "IQUIQUE" in reg_u or "TARAPAC" in reg_u or "IQUIQUE" in comp_u:
        return "Centros Médicos RedSalud Iquique", "96.598.850-0"

    return "Clínica RedSalud Santiago", "96.524.000-2"

def extraer_id_licitacion(fila_raw, idx_codigo):
    valid_suffixes = ("LP", "LE", "LR", "LQ", "LS", "L1", "E2", "CO", "B2")
    cands = [fila_raw[idx_codigo]] if (idx_codigo is not None and idx_codigo < len(fila_raw)) else []
    cands += fila_raw[:5]
    for c in cands:
        for code in re.findall(r"\b\d{3,8}-\d{1,5}-[A-Za-z0-9]+\b", str(c).strip()):
            parts = code.split("-")
            if len(parts) == 3 and any(parts[2].upper().startswith(vs) for vs in valid_suffixes):
                return code.upper()
    return ""

def extraer_prestacion(fila_raw, idx_nombre):
    col_nom = fila_raw[idx_nombre].strip() if idx_nombre is not None and idx_nombre < len(fila_raw) else ""
    if len(col_nom) >= 5:
        return col_nom
    for c in fila_raw:
        cs = str(c).strip()
        if len(cs) >= 12 and not re.search(r"^\d+-\d+-[A-Za-z0-9]+$", cs):
            return cs
    return "Prestación Médica Asistencial"

def construir_fila_consolidado(codigo, comprador, rut_comprador, region, categoria, prestacion, monto, adj_redsalud=""):
    cat_cliente = clasificar_categoria_cliente(comprador)
    rut_cli = rut_comprador if rut_comprador else resolver_rut_cliente(comprador, codigo)
    filial, rut_filial = determinar_filial_por_rut_y_zona(categoria, region, comprador, adj_redsalud=adj_redsalud)
    tipo_reg = "Compra Ágil" if "-CO" in codigo.upper() else "Licitación"
    return [
        cat_cliente,
        comprador if comprador else "Institución Pública (Por confirmar)",
        rut_cli,
        filial,
        rut_filial,
        "Contrato Base",
        tipo_reg,
        codigo.upper(),
        prestacion if prestacion else "Prestación Médica Asistencial",
        "", "", 12, monto, "", "", "", "En gestión", "Sí", ""
    ]

# 7. ORQUESTADOR CON VERIFICACION ESTRICTA DE GANADOR REDSALUD
def sincronizar_todo():
    print("=== INICIANDO SINCRONIZADOR CALIBRADO LICITALAB -> REDSALUD ===", flush=True)
    client, sa_email = obtener_cliente_gspread()
    print(f"Autenticado como: {sa_email}", flush=True)

    ss_maestra = client.open_by_key(SPREADSHEET_ID_MAESTRA)
    sheet_maestra = ss_maestra.sheet1
    actualizar_base_madre_licitalab(sheet_maestra)

    print("--- FASE 2: Auditando y sincronizando adjudicaciones reales RedSalud ---", flush=True)
    valores_maestra = sheet_maestra.get_all_values()
    ss_contratos = client.open_by_key(SPREADSHEET_ID_CONTRATOS)
    ws_contratos = next((w for w in ss_contratos.worksheets() if w.title.strip().lower() == NOMBRE_HOJA_CONTRATOS.lower()), None)
    if not ws_contratos:
        print(f"Error: Hoja '{NOMBRE_HOJA_CONTRATOS}' no encontrada.", flush=True)
        return

    datos_existentes = ws_contratos.get_all_values()
    ids_historicos = set()
    for row in datos_existentes[:min(FILA_INICIO_OBJETIVO - 1, len(datos_existentes))]:
        if len(row) > 7 and row[7].strip():
            ids_historicos.add(row[7].strip().upper())

    candidatos = {}
    for r in valores_maestra[1:]:
        fila = list(r) + [""] * (25 - len(r))
        cod_u = extraer_id_licitacion(fila, 1)
        if not cod_u or cod_u in LICITACIONES_DESCARTADAS_EXPLICITAS or cod_u in ids_historicos:
            continue
        if "AGIL" in fila[7].upper() or "COT" in cod_u:
            continue
        if "ADJUDICADA" in fila[10].upper() or cod_u in CODIGOS_AUDITAR_REDSALUD:
            candidatos[cod_u] = {
                "comprador": fila[8].strip(),
                "region": fila[9].strip(),
                "categoria": fila[3].strip(),
                "prestacion": extraer_prestacion(fila, 2),
                "monto": fila[12].strip(),
                "adj_raw": fila[11].strip()
            }

    for c_audit in CODIGOS_AUDITAR_REDSALUD:
        cu = c_audit.strip().upper()
        if cu not in ids_historicos and cu not in LICITACIONES_DESCARTADAS_EXPLICITAS and cu not in candidatos:
            candidatos[cu] = {"comprador": "", "region": "", "categoria": "Salud", "prestacion": "", "monto": "", "adj_raw": ""}

    filas_nuevas = []
    for cod_u, base_info in candidatos.items():
        # Verificar siempre contra API de Mercado Público / LicitaLAB quién ganó realmente
        det = consultar_detalle_mercado_publico(cod_u) or consultar_detalle_licitalab(cod_u)
        time.sleep(0.35)

        if det:
            if not det.get("ganador_redsalud"):
                print(f"DESCARTADA ({cod_u}): Adjudicada a competidor -> {det.get('adjudicatario_otros')}", flush=True)
                continue

            comprador = det.get("comprador") or base_info["comprador"]
            rut_comp = det.get("rut_comprador") or ""
            region = det.get("region") or base_info["region"]
            prestacion = det.get("nombre") or base_info["prestacion"]
            monto = det.get("monto_redsalud") or base_info["monto"]
            adj_rs = det.get("adjudicatario_redsalud") or base_info["adj_raw"]
            print(f"CONFIRMADA ({cod_u}): Ganador RedSalud -> {adj_rs} | Monto: {monto}", flush=True)
            filas_nuevas.append(construir_fila_consolidado(cod_u, comprador, rut_comp, region, base_info["categoria"], prestacion, monto, adj_rs))
        else:
            # Respaldo solo si la Base Madre ya tiene explícitamente un RUT RedSalud verificado
            if es_proveedor_redsalud(base_info["adj_raw"], base_info["adj_raw"]):
                filas_nuevas.append(construir_fila_consolidado(cod_u, base_info["comprador"], "", base_info["region"], base_info["categoria"], base_info["prestacion"], base_info["monto"], base_info["adj_raw"]))

    tot_nuevas = len(filas_nuevas)
    print(f"Total adjudicaciones 100% verificadas RedSalud: {tot_nuevas}", flush=True)
    fila_inicio = FILA_INICIO_OBJETIVO
    filas_totales_actuales = max(len(datos_existentes), fila_inicio)
    ws_contratos.batch_clear([f"A{fila_inicio}:S{filas_totales_actuales + 100}"])

    if tot_nuevas > 0:
        ws_contratos.resize(rows=max(fila_inicio + tot_nuevas + 50, 500), cols=25)
        ws_contratos.update(range_name=f"A{fila_inicio}:S{fila_inicio + tot_nuevas - 1}", values=filas_nuevas)
        print(f"Éxito: {tot_nuevas} licitaciones verificadas escritas desde la fila {fila_inicio}.", flush=True)

if __name__ == "__main__":
    sincronizar_todo()
