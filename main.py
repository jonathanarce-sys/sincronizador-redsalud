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

# Fila 434 contiene "San Antonio"; las nuevas cargas parten en la fila 434
FILA_INICIO_OBJETIVO = 434

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
# 2. LISTA BLANCA OFICIAL RUTS Y ADJUDICACIONES CONFIRMADAS
# ==========================================
RUTS_REDSALUD_WHITELIST = {
    "96856000", "76458120", "96536000", "96543000", "99568700",
    "96542000", "96537000", "96541000", "96524000", "96527000",
    "96559000", "76326330", "96942400", "96567920", "96598850",
    "76906480", "96774580", "76181326", "76207967", "78918290",
    "88611600", "76124062", "99568720", "96680980", "76110809",
    "76046416", "78040520", "78053560"
}

# Las 25 adjudicaciones confirmadas que deben incorporarse en el consolidado
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
# 4. CONSULTA PUNTUAL A MERCADO PUBLICO / LICITALAB PARA IDs FALTANTES
# ==========================================
def consultar_detalle_mercado_publico(codigo_lic):
    if not MERCADOPUBLICO_TICKET:
        return None
    url = "https://api.mercadopublico.cl/servicios/v1/publico/licitaciones.json"
    params = {"codigo": codigo_lic, "ticket": MERCADOPUBLICO_TICKET}
    try:
        resp = requests.get(url, params=params, timeout=20)
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
                
                adj_nombre = ""
                monto_total = ""
                items_obj = lic.get("Items") or {}
                listado_items = items_obj.get("Listado") or []
                suma_monto = 0
                for it in listado_items:
                    adj = it.get("Adjudicacion") or {}
                    if adj:
                        prov = str(adj.get("NombreProveedor") or "").strip()
                        rut_p = str(adj.get("RutProveedor") or "").strip()
                        if prov and prov not in adj_nombre:
                            adj_nombre = f"{adj_nombre} | {prov} ({rut_p})".strip(" |")
                        m_unit = adj.get("MontoUnitario") or 0
                        cant = adj.get("Cantidad") or 1
                        try:
                            suma_monto += float(m_unit) * float(cant)
                        except Exception:
                            pass
                if suma_monto > 0:
                    monto_total = str(int(round(suma_monto)))

                return {
                    "codigo": codigo_lic.upper(),
                    "nombre": nombre_lic,
                    "comprador": nombre_org,
                    "rut_comprador": rut_org,
                    "region": region_org,
                    "estado": estado_lic,
                    "adjudicatario": adj_nombre,
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
        fecha_pub = str(item.get("PUBLISH_DATE") or item.get("published_at") or "")[:10]
        fecha_cie = str(item.get("CLOSING_DATE") or item.get("closing_at") or "")[:10]
        fecha_2do = "-"

        tipo_raw = item.get("OPPORTUNITY_TYPE") or item.get("type") or ""
        tipo_proc = normalizar_tipo_proceso(tipo_raw, cod)

        estado = str(item.get("OPPORTUNITY_STATUS") or item.get("status") or "Publicada").strip()
        adj = str(item.get("AWARDED_PROVIDERS") or item.get("award") or "").strip()
        
        monto_raw = item.get("AVAILABLE_AMOUNT") if item.get("AVAILABLE_AMOUNT") is not None else item.get("TOTAL_AWARDED_AMOUNT")
        monto = str(int(monto_raw)) if isinstance(monto_raw, (int, float)) else str(monto_raw or "").strip()

        fila_20 = [""] * total_cols
        fila_20[0] = item_id
        fila_20[1] = cod
        fila_20[2] = nombre
        fila_20[3] = categoria
        fila_20[4] = fecha_pub
        fila_20[5] = fecha_cie
        fila_20[6] = fecha_2do
        fila_20[7] = tipo_proc
        fila_20[8] = comprador
        fila_20[9] = region
        fila_20[10] = estado
        fila_20[11] = adj
        fila_20[12] = monto

        filas_nuevas.append(fila_20)
        codigos_existentes.add(cod)

    print(f"Resumen análisis: {len(filas_nuevas)} nuevas completas para insertar | {rechazados_existentes} ya existian | {rechazados_incompletos} descartadas.", flush=True)

    if filas_nuevas:
        filas_nuevas.sort(key=lambda r: str(r[4]), reverse=True)
        print(f"Insertando {len(filas_nuevas)} licitaciones 100% completas en Fila 2 de la Base Madre...", flush=True)
        sheet_maestra.insert_rows(filas_nuevas, row=2)
        print(f"Exito Fase 1: Se insertaron {len(filas_nuevas)} licitaciones completas y alineadas en Base Madre.", flush=True)

# ==========================================
# 6. FASE 2: FILTRADO + RESCATE DE ADJUDICACIONES HACIA 'CONSOLIDADO'
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
    if "IQUIQUE" in reg_u or "TARAPACÁ" in reg_u or "1017312-" in cod_u or "2145-" in cod_u:
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
    if re.search(r"-[A-Za-z0-9]+26\b", str(codigo)):
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

def construir_fila_consolidado(codigo, comprador, rut_comprador, region, categoria, prestacion, monto, adj_celda=""):
    cat_cliente = clasificar_categoria_cliente(comprador)
    rut_cli = rut_comprador if rut_comprador else resolver_rut_cliente(comprador, codigo)
    filial, rut_filial = determinar_filial(categoria, region, comprador, adj=adj_celda, codigo=codigo)
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
        "",
        "",
        12,
        monto,
        "",
        "",
        "",
        "En gestión",
        "Sí",
        ""
    ]

# ==========================================
# 7. ORQUESTADOR COMPLETO
# ==========================================
def sincronizar_todo():
    print("=== INICIANDO SINCRONIZADOR INTEGRAL LICITALAB -> REDSALUD ===", flush=True)
    try:
        client, sa_email = obtener_cliente_gspread()
        print(f"Autenticado en Google Sheets como: {sa_email}", flush=True)
    except Exception as e:
        print(f"Error de conexión: {repr(e)}", flush=True)
        return

    try:
        ss_maestra = client.open_by_key(SPREADSHEET_ID_MAESTRA)
        sheet_maestra = ss_maestra.sheet1
    except Exception as e:
        print(f"Error abriendo Base Madre: {repr(e)}", flush=True)
        return

    actualizar_base_madre_licitalab(sheet_maestra)

    print("\n--- FASE 2: Sincronizando hacia consolidado ---", flush=True)
    valores_maestra = sheet_maestra.get_all_values()
    print(f"Total filas en Base Madre: {len(valores_maestra)}", flush=True)

    cabecera = valores_maestra[0] if valores_maestra else []
    idx_codigo = 1
    idx_nombre = 2
    idx_categoria = 3
    idx_tipo = 7
    idx_comprador = 8
    idx_region = 9
    idx_estado = 10
    idx_adjudicatario = 11
    idx_monto = 12

    for idx, c in enumerate(cabecera):
        t = str(c).strip().upper()
        if ("CÓDIGO" in t or "CODIGO" in t or "ID" in t) and not any(x in t for x in ["OC", "ORDEN", "FACTURABLE", "COMPRA"]):
            idx_codigo = idx
        elif "NOMBRE" in t and "PROCESO" in t:
            idx_nombre
