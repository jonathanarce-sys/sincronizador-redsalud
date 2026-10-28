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

# ==========================================
# 2. LISTA BLANCA OFICIAL RUTS REDSALUD
# ==========================================
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

# ==========================================
# 4. FASE 1: DESCARGA DESDE LICITALAB
# ==========================================
def actualizar_base_madre_licitalab(sheet_maestra):
    print("--- FASE 1: Conexion y descarga desde LicitaLAB hacia Base Madre ---", flush=True)
    if not LICITALAB_TOKEN:
        print("AVISO: No se detecto 'LICITALAB_TOKEN' en los Secrets de GitHub.", flush=True)
        return

    datos_actuales = sheet_maestra.get_all_values()
    codigos_existentes = set()
    for fila in datos_actuales[1:]:
        if len(fila) > 1 and fila[1].strip():
            codigos_existentes.add(fila[1].strip().upper())
            
    print(f"Base Madre contiene actualmente {len(codigos_existentes)} licitaciones unicas.", flush=True)

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
            print(f"Consultando LicitaLAB en: {url}...", flush=True)
            resp = requests.get(url, headers=headers, timeout=30)
            print(f"Respuesta LicitaLAB: HTTP {resp.status_code}", flush=True)

            if resp.status_code in (401, 403):
                headers["Authorization"] = f"Token {LICITALAB_TOKEN}"
                headers["X-API-KEY"] = LICITALAB_TOKEN
                resp = requests.get(url, headers=headers, timeout=30)
                print(f"Reintento con header alternativo: HTTP {resp.status_code}", flush=True)

            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    items_licitalab = data
                elif isinstance(data, dict):
                    items_licitalab = data.get("data") or data.get("licitaciones") or data.get("results") or []
                print(f"Licitaciones recuperadas desde LicitaLAB: {len(items_licitalab)}", flush=True)
                exito = True
                break
            else:
                print(f"Detalle respuesta: {resp.text[:120]}", flush=True)
        except Exception as e:
            print(f"Error al conectar con {url}: {repr(e)}", flush=True)

    if not exito or not items_licitalab:
        print("Fase 1 completada: No se recibieron nuevos registros desde LicitaLAB en esta consulta.", flush=True)
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
        print(f"Exito Fase 1: Se insertaron {len(filas_nuevas)} licitaciones nuevas en la Base Madre.", flush=True)
    else:
        print("Base Madre al dia: Todas las licitaciones de LicitaLAB ya se encontraban registradas.", flush=True)

# ==========================================
# 5. FASE 2: FILTRADO HACIA 'CONSOLIDADO'
# ==========================================
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
        return "Hospitales"
    return "Otros"

def determinar_filial(cat, reg, comp, adj="", codigo=""):
    adj_u = str(adj).upper()
    comp_u = str(comp).upper()
    reg_u = str(reg).upper()
    cat_u = str(cat).upper()
    cod_u = str(codigo).upper()

    if "899-33-LE26" in cod_u or "99.568.700" in adj_u or "99568700" in adj_u or "VALPARAISO" in adj_u or "VALPARAÍSO" in adj_u or "INVERSALUD" in adj_u:
        return "Centro de Especialidades Médicas Valparaíso", "99.568.700-3"

    if "DENTAL" in cat_u:
        return "RedSalud Dental SpA", "76.458.120-3"

    if "VALPARAÍSO" in reg_u or "VALPARAISO" in reg_u or "VIÑA" in comp_u:
        return "Clínica RedSalud Valparaíso", "96.543.000-6"
    if "RANCAGUA" in comp_u or "HIGGIN" in reg_u or "COLCHAGUA" in comp_u:
        return "Clínica RedSalud Rancagua", "96.542.000-0"
    if "ARAUCANÍA" in reg_u or "TEMUCO" in comp_u or "KALLVU" in comp_u:
        return "Clínica RedSalud Mayor Temuco", "96.537.000-3"
    if "MAGALLANES" in reg_u or "PUNTA ARENAS" in comp_u:
        return "Clínica RedSalud Magallanes", "96.541.000-5"
    if "BIOBÍO" in reg_u or "BIOBIO" in reg_u or "CONCEPCIÓN" in comp_u:
        return "Centros Médicos RedSalud Biobío", "96.856.000-2"
    if "MAULE" in reg_u or "CURICÓ" in comp_u or "TALCA" in comp_u:
        return "Centros Médicos RedSalud Maule", "96.856.000-2"
    if "IQUIQUE" in reg_u or "TARAPACÁ" in reg_u:
        return "Centros Médicos RedSalud Iquique", "96.856.000-2"
    if "ANTOFAGASTA" in reg_u or "CALAMA" in comp_u:
        return "Centros Médicos RedSalud Antofagasta", "96.856.000-2"

    if "METROPOLITANA" in reg_u or "SANTIAGO" in reg_u:
        if any(x in comp_u for x in ["PROVIDENCIA", "ORIENTE"]) or "PROVIDENCIA" in adj_u:
            return "Clínica RedSalud Providencia", "96.536.000-8"
        if any(x in comp_u for x in ["VITACURA", "LO BARNECHEA"]) or "VITACURA" in adj_u:
            return "Clínica RedSalud Vitacura", "96.536.000-8"
        return "Clínica RedSalud Santiago", "96.856.000-2"

    return "RedSalud S.A.", "96.856.000-2"

def parsear_fechas_fila(fila):
    fechas = []
    for c in fila:
        c_str = str(c).strip()
        matches = re.findall(r"\b(\d{1,4})[-/.](\d{1,2})[-/.](\d{2,4})\b", c_str)
        for m in matches:
            p1, p2, p3 = int(m[0]), int(m[1]), int(m[2])
            if p1 > 1000:
                year, month, day = p1, p2, p3
            elif p3 > 1000:
                year, month, day = p3, p2, p1
            elif 20 <= p3 <= 35:
                year, month, day = 2000 + p3, p2, p1
            else:
                continue
            if 1 <= month <= 12 and 1 <= day <= 31:
                fechas.append((year, month, day))
    return fechas

def cumple_filtro_periodo(fila_raw, codigo):
    if re.search(r"-[A-Za-z]+26\b", str(codigo)):
        return True
    fechas = parsear_fechas_fila(fila_raw)
    for y, m, d in fechas:
        if (y == 2025 and m >= 9) or (y >= 2026):
            return True
    return False

def extraer_id_licitacion(fila_raw, idx_codigo):
    valid_suffixes = ("LP", "LE", "LR", "LQ", "LS", "L1", "E2", "CO", "B2")
    if idx_codigo is not None and idx_codigo < len(fila_raw):
        celda = str(fila_raw[idx_codigo]).strip()
        codes = re.findall(r"\b\d{3,8}-\d{1,5}-[A-Za-z0-9]+\b", celda)
        for code in codes:
            parts = code.split("-")
            if len(parts) == 3 and any(parts[2].upper().startswith(vs) for vs in valid_suffixes):
                return code.upper()

    for c in fila_raw[:5]:
        celda = str(c).strip()
        codes = re.findall(r"\b\d{3,8}-\d{1,5}-[A-Za-z0-9]+\b", celda)
        for code in codes:
            parts = code.split("-")
            if len(parts) == 3 and any(parts[2].upper().startswith(vs) for vs in valid_suffixes):
                return code.upper()
    return ""

def extraer_prestacion(fila_raw, idx_nombre):
    palabras_prohibidas = [
        "SERVICIO DE SALUD", "INSTITUCIÓN PÚBLICA", "INSTITUCION PUBLICA",
        "REDSALUD", "RED SALUD", "ACEPTADA", "EN PROCESO", "EVALUACIÓN",
        "EVALUACION", "ADJUDICADA", "PUBLICADA", "DESIERTA", "REVOCADA",
        "CANCELADA", "ENVIADA", "RUT:", "S.A.", "SPA", "LTDA", "E.I.R.L.",
        "COMPRADOR", "MUNICIPALIDAD", "HOSPITAL", "INGEFISIC", "RUBIKAL",
        "ATRYS", "BIOS", "ARTURO LOPEZ PEREZ", "BARLARO", "APSORAD"
    ]
    col_nom = fila_raw[idx_nombre].strip() if idx_nombre is not None and idx_nombre < len(fila_raw) else ""
    if col_nom and len(col_nom) >= 5 and not any(p in col_nom.upper() for p in palabras_prohibidas):
        return col_nom

    candidatos = []
    for c in fila_raw:
        cs = str(c).strip()
        if len(cs) >= 8 and not any(p in cs.upper() for p in palabras_prohibidas):
            if not re.search(r"^\d+-\d+-[A-Za-z0-9]+$", cs) and not re.search(r"^\d{7,8}-[\dkK]$", cs):
                candidatos.append(cs)

    if candidatos:
        return max(candidatos, key=len)
    return "Prestación Médica Asistencial"

def verificar_adjudicacion_exclusiva_redsalud(fila, idx_adjudicatario, idx_comprador):
    rut_comprador = ""
    if idx_comprador is not None and idx_comprador < len(fila):
        comp_str = str(fila[idx_comprador])
        ruts_comp = re.findall(r"\b\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]\b", comp_str)
        if ruts_comp:
            rut_comprador = re.sub(r"[^0-9]", "", ruts_comp[0])

    ruts_adjudicados = []
    if idx_adjudicatario is not None and idx_adjudicatario < len(fila):
        celda_adj = str(fila[idx_adjudicatario])
        for r in re.findall(r"\b\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]\b", celda_adj):
            r_num = re.sub(r"[^0-9]", "", r)
            if r_num != rut_comprador:
                ruts_adjudicados.append(r_num)

    for idx_col in range(10, len(fila)):
        val = str(fila[idx_col]).strip()
        for r in re.findall(r"\b\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]\b", val):
            r_num = re.sub(r"[^0-9]", "", r)
            if r_num != rut_comprador and r_num not in ruts_adjudicados:
                ruts_adjudicados.append(r_num)

    if ruts_adjudicados:
        return any(any(rs in r for rs in RUTS_REDSALUD_WHITELIST) for r in ruts_adjudicados)

    if idx_adjudicatario is not None and idx_adjudicatario < len(fila):
        celda_adj_u = str(fila[idx_adjudicatario]).upper()
        if any(bad in celda_adj_u for bad in ["APSORAD", "FALP", "BARLARO", "RUBIKAL", "ATRYS", "INGEFISIC", "VETERINARIO", "BIOMEDIC", "BIOS"]):
            return False
        if re.search(r"\bRED\s*SALUD\b|MEGASALUD|INVERSALUD|ESPECIALIDADES\s*MEDICAS\s*VALPARAISO", celda_adj_u):
            return True

    return False

# ==========================================
# 6. ORQUESTADOR COMPLETO
# ==========================================
def sincronizar_todo():
    print("=== INICIANDO SINCRONIZADOR INTEGRAL LICITALAB -> RED
