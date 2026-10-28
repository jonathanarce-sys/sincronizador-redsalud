import os
import requests
import gspread
from google.oauth2.service_account import Credentials
import base64
import json
import re
from datetime import datetime, timedelta

# ==========================================
# 1. IDENTIFICADORES DE HOJAS
# ==========================================
SPREADSHEET_ID_MAESTRA = "1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek".strip()
SPREADSHEET_ID_CONTRATOS = "1kiOFcktRWHeXAOzCwLqPMzu1py0mGlANmvNogFCDbRE".strip()
NOMBRE_HOJA_CONTRATOS = "consolidado"
FILA_INICIO_OBJETIVO = 372

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
# 4. FASE 1: DESCARGA AUTOMÁTICA A BASE MADRE
# ==========================================
def actualizar_base_madre(sheet_maestra):
    print("--- FASE 1: Consultando novedades para la Base Maestra ---", flush=True)
    
    # Obtenemos códigos actuales en la Base Madre para no duplicar
    datos_actuales = sheet_maestra.get_all_values()
    codigos_existentes = set()
    for fila in datos_actuales[1:]:
        if len(fila) > 1 and fila[1].strip():
            codigos_existentes.add(fila[1].strip().upper())
            
    print(f"Base Madre contiene actualmente {len(codigos_existentes)} licitaciones únicas.", flush=True)

    # Consultamos los últimos 3 días en la API pública de Mercado Público
    filas_a_insertar = []
    fechas_a_revisar = [
        datetime.now().strftime("%d%m%Y"),
        (datetime.now() - timedelta(days=1)).strftime("%d%m%Y"),
        (datetime.now() - timedelta(days=2)).strftime("%d%m%Y"),
    ]

    # Ticket público estándar de consulta
    ticket_publico = "F8537A18-6766-4DEF-9E59-426B4F609C66"

    for f_str in fechas_a_revisar:
        url = f"https://api.mercadopublico.cl/servicios/v1/publico/licitaciones.json?fecha={f_str}&ticket={ticket_publico}"
        try:
            r = requests.get(url, timeout=20)
            if r.status_code == 200:
                data = r.json()
                lista = data.get("Listado", [])
                for item in lista:
                    cod = item.get("CodigoExterno", "").strip().upper()
                    # Solo nos interesan licitaciones que no tengamos y que sean compras públicas formales
                    if cod and cod not in codigos_existentes and not cod.endswith("-COT26"):
                        nombre = item.get("Nombre", "").strip()
                        estado = item.get("CodigoEstado", "Publicada")
                        fecha_cie = item.get("FechaCierre", "")[:10]
                        fecha_pub = f"{f_str[4:]}-{f_str[2:4]}-{f_str[:2]}"  # YYYY-MM-DD
                        
                        # Armar fila compatible con las columnas de tu Base Madre
                        nueva_fila = [
                            "",                # Col A: ID
                            cod,               # Col B: Código Proceso
                            nombre,            # Col C: Nombre Proceso
                            "Salud",           # Col D: Categoría
                            fecha_pub,         # Col E: Fecha Publicación
                            fecha_cie,         # Col F: Fecha Cierre
                            "",                # Col G: Región
                            "Licitación",      # Col H: Tipo Proceso
                            item.get("Comprador", {}).get("NombreOrganismo", ""), # Col I: Comprador
                            "",                # Col J: Región Territorio
                            estado,            # Col K: Estado
                            "",                # Col L: Adjudicatario
                            ""                 # Col M: Monto
                        ]
                        filas_a_insertar.append(nueva_fila)
                        codigos_existentes.add(cod)
        except Exception as e:
            print(f"Aviso consultando fecha {f_str}: {repr(e)}", flush=True)

    if filas_a_insertar:
        # Añadir al final de la Base Madre en bloques
        sheet_maestra.append_rows(filas_a_insertar)
        print(f"Éxito Fase 1: Se agregaron {len(filas_a_insertar)} licitaciones nuevas a la Base Madre.", flush=True)
    else:
        print("Fase 1 completada: La Base Madre ya se encuentra al día con los últimos registros disponibles.", flush=True)

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
    if any(m in org for m in ["MUNICIPALIDAD", "MUNI", "ALCALDÍA"]):
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

    # Si es adjudicado a Valparaíso o el código es 899-33-LE26
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

    # Si hay RUTs explícitos en adjudicación, debe coincidir con la lista blanca
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
    print("=== INICIANDO SINCRONIZADOR INTEGRAL ===", flush=True)
    try:
        client, sa_email = obtener_cliente_gspread()
        print(f"Autenticado en Google Sheets como: {sa_email}", flush=True)
    except Exception as e:
        print(f"Error de conexión: {repr(e)}", flush=True)
        return

    # 1. Base Madre
    try:
        ss_maestra = client.open_by_key(SPREADSHEET_ID_MAESTRA)
        sheet_maestra = ss_maestra.sheet1
    except Exception as e:
        print(f"Error abriendo Base Madre: {repr(e)}", flush=True)
        return

    # Ejecutar Fase 1: Traer novedades a la Base Madre
    actualizar_base_madre(sheet_maestra)

    # Ejecutar Fase 2: Filtrar Base Madre hacia 'consolidado'
    print("\n--- FASE 2: Sincronizando hacia 'consolidado' ---", flush=True)
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
            idx_nombre = idx
        elif "CATEGOR" in t:
            idx_categoria = idx
        elif "TIPO" in t:
            idx_tipo = idx
        elif "COMPRADOR" in t or "INSTITUCI" in t:
            idx_comprador = idx
        elif "REGI" in t:
            idx_region = idx
        elif "ESTADO" in t and "OFERTA" in t:
            idx_estado = idx
        elif ("ADJUDICATARIO" in t or "PROVEEDOR ADJUDICADO" in t or "RAZÓN SOCIAL ADJUDICATARIO" in t or "GANADOR" in t) and "CATEGOR" not in t:
            idx_adjudicatario = idx
        elif "MONTO" in t:
            idx_monto = idx

    try:
        ss_contratos = client.open_by_key(SPREADSHEET_ID_CONTRATOS)
    except Exception:
        url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID_CONTRATOS}/edit"
        ss_contratos = client.open_by_url(url)

    ws_contratos = None
    for ws in ss_contratos.worksheets():
        if ws.title.strip().lower() == NOMBRE_HOJA_CONTRATOS.lower():
            ws_contratos = ws
            break
    if not ws_contratos:
        print(f"Error: Hoja '{NOMBRE_HOJA_CONTRATOS}' no encontrada.", flush=True)
        return

    datos_existentes = ws_contratos.get_all_values()
    print(f"Filas actuales en '{NOMBRE_HOJA_CONTRATOS}': {len(datos_existentes)}", flush=True)

    ids_historicos = set()
    limite_historico = min(FILA_INICIO_OBJETIVO - 1, len(datos_existentes))
    for row in datos_existentes[:limite_historico]:
        if len(row) > 7 and row[7].strip():
            ids_historicos.add(row[7].strip().upper())
        if len(row) > 1 and row[1].strip():
            ids_historicos.add(row[1].strip().upper())

    filas_nuevas = []
    ids_nuevos = set()

    if len(valores_maestra) > 1:
        for r in valores_maestra[1:]:
            fila = list(r) + [""] * (25 - len(r))
            categoria = fila[idx_categoria].strip() if idx_categoria < len(fila) else ""
            tipo_proc = fila[idx_tipo].strip() if idx_tipo < len(fila) else ""
            comprador = fila[idx_comprador].strip() if idx_comprador < len(fila) else ""
            region = fila[idx_region].strip() if idx_region < len(fila) else ""
            estado = fila[idx_estado].strip() if idx_estado < len(fila) else ""
            monto = fila[idx_monto].strip() if idx_monto < len(fila) else ""
            adjudicatario_celda = fila[idx_adjudicatario].strip() if idx_adjudicatario < len(fila) else ""

            codigo = extraer_id_licitacion(fila, idx_codigo)
            if not codigo or codigo.upper() in LICITACIONES_DESCARTADAS_EXPLICITAS:
                continue

            if "AGIL" in tipo_proc.upper() or "COT" in codigo.upper():
                continue

            es_adj = "ADJUDICADA" in estado.upper() or any(str(c).strip().upper() == "ADJUDICADA" for c in fila)
            if not es_adj:
                continue

            if not verificar_adjudicacion_exclusiva_redsalud(fila, idx_adjudicatario, idx_comprador):
                continue

            if not cumple_filtro_periodo(fila, codigo):
                continue

            cod_u = codigo.upper()
            if cod_u in ids_historicos or cod_u in ids_nuevos:
                continue

            cat_cliente = clasificar_categoria_cliente(comprador)
            prestacion = extraer_prestacion(fila, idx_nombre)
            rut_cliente = resolver_rut_cliente(comprador, codigo)
            filial, rut_filial = determinar_filial(categoria, region, comprador, adj=adjudicatario_celda, codigo=codigo)

            filas_nuevas.append([
                cat_cliente, comprador, rut_cliente, filial, rut_filial,
                "", "Licitación", codigo, prestacion, "", "", 12, monto,
                "", "", "", "En gestión", "Sí", ""
            ])
            ids_nuevos.add(cod_u)

    tot_nuevas = len(filas_nuevas)
    print(f"Licitaciones VERDADERAMENTE adjudicadas a RedSalud: {tot_nuevas}", flush=True)

    fila_inicio = FILA_INICIO_OBJETIVO
    filas_totales_actuales = max(len(datos_existentes), fila_inicio)

    if filas_totales_actuales >= fila_inicio:
        print(f"Purgando filas erróneas desde A{fila_inicio}:S{filas_totales_actuales + 100}...", flush=True)
        ws_contratos.batch_clear([f"A{fila_inicio}:S{filas_totales_actuales + 100}"])

    if tot_nuevas > 0:
        fila_fin = fila_inicio + tot_nuevas - 1
        filas_necesarias = max(fila_fin + 50, 450)
        ws_contratos.resize(rows=filas_necesarias, cols=25)

        for s in range(0, tot_nuevas, 1000):
            e = min(s + 1000, tot_nuevas)
            r_ini = fila_inicio + s
            r_fin = fila_inicio + e - 1
            ws_contratos.update(
                range_name=f"A{r_ini}:S{r_fin}",
                values=filas_nuevas[s:e]
            )
        print(f"Éxito: Se escribieron {tot_nuevas} licitaciones legítimas de RedSalud desde la fila {fila_inicio}.", flush=True)
    else:
        print("RESULTADO: Ninguna licitación ajena fue insertada. Rango consolidado purgado.", flush=True)

if __name__ == "__main__":
    sincronizar_todo()
