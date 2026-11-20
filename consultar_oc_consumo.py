import os
import re
import json
import base64
import time
import requests
import gspread
from datetime import datetime, timedelta
from google.oauth2.service_account import Credentials

# ==========================================
# 1. CONFIGURACIÓN Y CONSTANTES
# ==========================================
SPREADSHEET_ID_MAESTRA = "1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek".strip()
SPREADSHEET_ID_CONTRATOS = "1kiOFcktRWHeXAOzCwLqPMzu1py0mGlANmvNogFCDbRE".strip()
NOMBRE_HOJA_CONTRATOS = "consolidado"
HOJA_REPORTE = "Reporte_Consumo_OC"
HOJA_INSUMO_OC = "RAW_OC_MP"

TICKET_MERCADOPUBLICO = (
    os.environ.get("MERCADOPUBLICO_TICKET") or
    os.environ.get("TICKET_MERCADOPUBLICO") or
    os.environ.get("MP_TICKET") or
    os.environ.get("TICKET_MP") or
    os.environ.get("API_TICKET_MP") or
    ""
).strip()

# Ventana de días hábiles recientes a escanear en Mercado Público
DIAS_ESCANEO_OC = int(os.environ.get("DIAS_ESCANEO_OC", "45"))

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

CODIGOS_OBJETIVO = [
    "1057402-55-LE26", "1057402-41-LE26", "1057402-90-LE26", "874750-17-L126",
    "1658-84-LE26", "1080089-31-LP26", "1237328-45-LE26", "3996-21-LE26",
    "2664-20-LE26", "4457-40-LE26", "3019-15-LE26", "2157-109-LP26",
    "4294-34-LR25", "4294-32-LR25", "1622-15-LE25", "1641-660-LP25",
    "1077499-17-LP25", "3265-23-L126", "2667-10-LP26", "1798-2-LE26",
    "4294-2-LR26", "438-24-LE26", "2026-15-LP26", "1330719-3-LR26",
    "2942-6-L126", "3926-10-CO26", "5594-2-LR26", "1077499-2-LP26",
    "2887-9-L126", "2887-10-LE26", "1417913-60-LE26", "2917-11-L126",
    "2917-12-L126", "2917-7-LE26", "1261592-31-LP26", "2887-11-LE26",
    "4324-4-L126", "2199-12-LP26", "1973-70-LP26", "1057402-105-LE26",
    "2446-139-LE26", "1057489-222-LE26", "4177-5-L126", "3495-14-LE26",
    "2345-97-LE26", "1554-31-LR26", "1057448-39-LE26", "1077499-20-LE25",
    "2667-130-LP25", "1973-85-LP25", "1057544-399-LE25", "3663-47-LE25",
    "591-26-LR25", "2026-164-LE25", "2026-163-LE25", "5061-84-L125",
    "5594-12-LQ25", "1057472-174-LR25", "2026-152-LP25", "4834-2-LE25",
    "1658-335-LQ25", "1057480-69-LE25", "2887-21-L125", "2887-19-LE25",
    "1667-24-LE25", "2917-32-LE25", "1077499-15-LE25", "1017312-17-LR25",
    "5061-61-L125", "799512-57-LE25", "4125-5-LE25", "1057489-270-LQ25",
    "4103-13-CO25", "4968-30-LP25", "899-21-LE25", "898-108-LE25",
    "1057480-53-LQ25", "4294-13-LR25", "2702-24-LP25", "1017312-16-LP25",
    "1057489-207-LQ25", "874750-28-L125", "1057049-119-LQ25", "1057474-15-LR25",
    "2446-133-LE25", "1057474-16-LR25", "1057402-98-LP25", "1175-71-LP25",
    "2133-51-LP25", "1057544-135-LE25", "1057402-102-LE25", "1017312-1-LP25",
    "2667-19-LE25", "2735-54-LR25", "1057492-43-LQ25", "4162-10-L125",
    "2421-8-LE25", "1057503-21-LQ25", "1075963-77-LE25", "557639-19-LQ25",
    "2735-22-LP25", "4738-1-LE25", "4294-5-LR25", "1077499-3-LQ25",
    "3140-27-LE24", "1237328-8-L125", "1973-13-LR25", "1057472-1-LQ25",
    "1979-3-LQ25", "2667-3-LQ25", "1057492-2-LR25"
]

TECHOS_CONTRATOS_AUDITADOS = {
    "1057402-55-LE26": {
        "organismo": "HOSPITAL CLINICO DR. LAUTARO NAVARRO AVARIA",
        "filial": "Clínica RedSalud Magallanes",
        "nombre": "PROCEDIMIENTOS, CIRUGIAS Y SALUD",
        "monto": 69500000,
    },
    "1057402-41-LE26": {
        "organismo": "HOSPITAL CLINICO DR. LAUTARO NAVARRO AVARIA",
        "filial": "Clínica RedSalud Magallanes",
        "nombre": "CONTRATACIÓN DEL SERVICIO DE EJECUCIÓN DE ESTUDIOS URODINÁMICOS",
        "monto": 68999186,
    }
}

# ==========================================
# 2. UTILIDADES
# ==========================================
def obtener_cliente_gspread():
    posibles = [
        "GCP_JSON_BASE64", "GCP_SERVICE_ACCOUNT", "GOOGLE_CREDENTIALS",
        "GCP_JSON", "GCP_SA_KEY", "GCP_CREDENTIALS"
    ]
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

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    return gspread.authorize(Credentials.from_service_account_info(creds_dict, scopes=scopes)), creds_dict.get("client_email", "SA")

def normalizar_codigo(cod):
    if not cod:
        return ""
    m = re.search(r"\b(\d{3,8}-\d{1,5}-[A-Za-z0-9]+)\b", str(cod).strip())
    return m.group(1).upper() if m else str(cod).strip().upper()

def extraer_rut_base(rut_str):
    m = re.search(r"(\d{1,2}\.?\d{3}\.?\d{3})-[\dkK]", str(rut_str))
    return re.sub(r"[^0-9]", "", m.group(1)) if m else ""

def es_proveedor_redsalud(rut_str, nombre_str=""):
    r_base = extraer_rut_base(rut_str)
    if r_base and r_base in RUTS_REDSALUD_WHITELIST:
        return True
    nom_u = str(nombre_str).upper()
    return bool(re.search(r"\bRED\s*SALUD\b|MEGASALUD|INVERSALUD|ESPECIALIDADES\s*MEDICAS\s*VALPARAISO|CLINICA\s*REGIONAL\s*DEL\s*ELQUI", nom_u))

def parsear_monto_clp(val):
    if val is None:
        return 0
    if isinstance(val, (int, float)):
        return int(round(val))
    limpio = re.sub(r"[^\d]", "", str(val))
    return int(limpio) if limpio else 0

def get_mp_con_reintento(url, params, timeout=20, max_reintentos=3):
    for intento in range(max_reintentos):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (203, 429, 502, 503):
                time.sleep(1.5 * (intento + 1))
                continue
            return None
        except Exception:
            time.sleep(1.0)
    return None

# ==========================================
# 3. UNIVERSO LOCAL (CONSOLIDADO + BASE MADRE)
# ==========================================
def cargar_universo_local(client):
    universo = {}

    try:
        ss_contratos = client.open_by_key(SPREADSHEET_ID_CONTRATOS)
        ws_c = next((w for w in ss_contratos.worksheets() if w.title.strip().lower() == NOMBRE_HOJA_CONTRATOS.lower()), None)
        if ws_c:
            filas_c = ws_c.get_all_values()
            for r in filas_c[1:]:
                if len(r) < 9:
                    continue
                tipo_reg = str(r[6]).strip().upper()
                cod = normalizar_codigo(r[7])
                if not cod or "COMPRA" in tipo_reg or "-CO" in cod:
                    continue
                universo[cod] = {
                    "organismo": str(r[1]).strip(),
                    "filial": str(r[3]).strip(),
                    "nombre": str(r[8]).strip(),
                    "monto": parsear_monto_clp(r[12]) if len(r) > 12 else 0,
                    "estado": str(r[16]).strip() or "Adjudicada"
                }
            print(f"Licitaciones cargadas desde '{NOMBRE_HOJA_CONTRATOS}': {len(universo)}", flush=True)
    except Exception as e:
        print(f"Aviso leyendo '{NOMBRE_HOJA_CONTRATOS}': {repr(e)}", flush=True)

    ss_maestra = client.open_by_key(SPREADSHEET_ID_MAESTRA)
    for ws in ss_maestra.worksheets():
        if ws.title.strip().lower() in (HOJA_REPORTE.lower(), HOJA_INSUMO_OC.lower()):
            continue
        try:
            filas = ws.get_all_values()
        except Exception:
            continue
        if len(filas) < 2:
            continue

        for r in filas[1:]:
            if len(r) < 13:
                continue
            cod = normalizar_codigo(r[1])
            if not cod:
                continue
            adj_raw = str(r[11]).strip()
            es_rs = es_proveedor_redsalud(adj_raw, adj_raw)

            if cod in universo or cod in CODIGOS_OBJETIVO or (es_rs and "ADJUDICADA" in str(r[10]).upper()):
                entry = universo.setdefault(cod, {"organismo": "", "filial": "", "nombre": "", "monto": 0, "estado": "Adjudicada"})
                if not entry["nombre"] and r[2].strip():
                    entry["nombre"] = r[2].strip()
                if not entry["organismo"] and r[8].strip():
                    entry["organismo"] = r[8].strip()
                if entry["monto"] == 0 and r[12].strip():
                    entry["monto"] = parsear_monto_clp(r[12])
                if not entry["filial"] and adj_raw:
                    r_base = extraer_rut_base(adj_raw)
                    if r_base in MAPA_RUT_FILIAL_REDSALUD:
                        entry["filial"] = MAPA_RUT_FILIAL_REDSALUD[r_base][0]

    for cod_obj in CODIGOS_OBJETIVO:
        cu = normalizar_codigo(cod_obj)
        universo.setdefault(cu, {"organismo": "", "filial": "", "nombre": "", "monto": 0, "estado": "Adjudicada"})

    return ss_maestra, universo

# ==========================================
# 4. EXTRACCIÓN RÁPIDA DE ÓRDENES DE COMPRA (PRE-FILTRO EN MEMORIA)
# ==========================================
def cargar_ocs_desde_pestana_local(ss_maestra):
    ocs_por_lic = {}
    ws_oc = next((w for w in ss_maestra.worksheets() if w.title.strip().lower() == HOJA_INSUMO_OC.lower()), None)
    if not ws_oc:
        ws_oc = ss_maestra.add_worksheet(title=HOJA_INSUMO_OC, rows=100, cols=8)
        ws_oc.update(range_name="A1:G1", values=[[
            "Codigo_OC", "Codigo_Licitacion", "RUT_Proveedor", "Nombre_Proveedor", "Estado_OC", "Monto_Neto_CLP", "Fecha_Envio"
        ]])
        return ocs_por_lic

    filas = ws_oc.get_all_values()
    if len(filas) < 2:
        return ocs_por_lic

    cab = [str(c).strip().upper() for c in filas[0]]
    idx_oc = next((i for i, c in enumerate(cab) if "OC" in c or "ORDEN" in c or i == 0), 0)
    idx_lic = next((i for i, c in enumerate(cab) if "LICIT" in c or "PROCESO" in c), 1)
    idx_rut = next((i for i, c in enumerate(cab) if "RUT" in c), 2)
    idx_prov = next((i for i, c in enumerate(cab) if "PROVEEDOR" in c or "RAZON" in c), 3)
    idx_est = next((i for i, c in enumerate(cab) if "ESTADO" in c), 4)
    idx_mto = next((i for i, c in enumerate(cab) if "MONTO" in c or "TOTAL" in c or "NETO" in c), 5)
    idx_fec = next((i for i, c in enumerate(cab) if "FECHA" in c), 6)

    for r in filas[1:]:
        if len(r) <= max(idx_oc, idx_lic):
            continue
        cod_oc = normalizar_codigo(r[idx_oc])
        cod_lic = normalizar_codigo(r[idx_lic])
        if not cod_oc or not cod_lic or "-" not in cod_lic:
            continue
        estado = str(r[idx_est]).strip() if idx_est < len(r) else "Aceptada"
        if "CANCEL" in estado.upper():
            continue
        rut_p = str(r[idx_rut]).strip() if idx_rut < len(r) else ""
        nom_p = str(r[idx_prov]).strip() if idx_prov < len(r) else ""
        if (rut_p or nom_p) and not es_proveedor_redsalud(rut_p, nom_p):
            continue
        monto = parsear_monto_clp(r[idx_mto]) if idx_mto < len(r) else 0
        fecha = str(r[idx_fec]).strip()[:10] if idx_fec < len(r) else ""
        ocs_por_lic.setdefault(cod_lic, {})[cod_oc] = {
            "codigo_oc": cod_oc,
            "monto": monto,
            "estado": estado or "Aceptada",
            "fecha": fecha
        }
    return ocs_por_lic

def es_oc_candidata_clinica(nombre_oc):
    """Filtra por glosa en el listado diario de MP para descartar 99% de OC de fármacos, aseo, papelería, etc."""
    nom_u = str(nombre_oc).upper()
    # Si menciona explícitamente RedSalud / Megasalud / Inversalud entra directo
    if re.search(r"RED\s*SALUD|MEGASALUD|INVERSALUD|CLINICA\s*REGIONAL|ESPECIALIDADES\s*MEDICAS", nom_u):
        return True
    # Descartar rubros ajenos a prestaciones clínicas
    excluir = (
        "MEDICAMENTO", "FARMACO", "FÁRMACO", "INSUMO", "PAPEL", "ASEO", "COMBUSTIBLE",
        "TRANSPORTE", "ALIMENT", "COMPUT", "SOFTWARE", "LICENCIA", "MANTENCION", "MANTENCIÓN",
        "REPUESTO", "CONSTRUCCION", "CONSTRUCCIÓN", "UNIFORME", "VESTUARIO", "MOBILIARIO"
    )
    if any(x in nom_u for x in excluir):
        return False
    # Palabras clave de prestaciones médicas licitadas por RedSalud
    incluir = (
        "EXAMEN", "EXÁMEN", "PROCEDIMIENTO", "CIRUG", "INTERVENCION", "INTERVENCIÓN",
        "URODINAM", "ENDOSCOP", "COLONOSCOP", "SCANNER", "RESONANCIA", "TOMOGRAF",
        "ECOGRAF", "MAMOGRAF", "IMAGEN", "LABORATORIO", "CONSULTA", "ESPECIALIDAD",
        "HOSPITALIZ", "ATENCION", "ATENCIÓN", "PRESTACION", "PRESTACIÓN", "DIALISIS",
        "DIÁLISIS", "ONCOL", "QUIMIOTERAPIA", "BIOPSIA", "DENTAL", "ODONTOL", "KINESIOL",
        "DERIVACION", "DERIVACIÓN", "CONVENIO", "SALUD", "GES", "LISTA DE ESPERA"
    )
    return any(x in nom_u for x in incluir)

def consultar_ocs_mercado_publico_rapido(ocs_por_lic, codigos_interes):
    """
    Escanea días hábiles recientes en Mercado Público y pre-filtra en memoria
    por prefijo comprador + glosa clínica antes de consultar el detalle de la OC.
    """
    if not TICKET_MERCADOPUBLICO:
        print("[MP OC] Sin ticket configurado.", flush=True)
        return ocs_por_lic

    url_oc = "https://api.mercadopublico.cl/servicios/v1/publico/ordenesdecompra.json"
    prefijos_compradores = {c.split("-")[0] for c in codigos_interes if "-" in c}
    set_codigos_interes = set(codigos_interes)

    hoy = datetime.now()
    fechas = [(hoy - timedelta(days=d)).strftime("%d%m%Y") for d in range(0, DIAS_ESCANEO_OC + 1) if (hoy - timedelta(days=d)).weekday() < 5]

    print(f"[MP OC] Escaneando {len(fechas)} días hábiles recientes en Mercado Público...", flush=True)
    candidatas = {}

    for fecha_str in fechas:
        data = get_mp_con_reintento(url_oc, {"fecha": fecha_str, "ticket": TICKET_MERCADOPUBLICO}, timeout=20, max_reintentos=2)
        if not data:
            continue
        listado = data.get("Listado") or []
        for item in listado:
            cod_oc = normalizar_codigo(item.get("Codigo"))
            estado_cod = str(item.get("CodigoEstado") or "").strip()
            if not cod_oc or estado_cod == "5":
                continue
            if cod_oc.split("-")[0] not in prefijos_compradores:
                continue
            if not es_oc_candidata_clinica(item.get("Nombre") or ""):
                continue
            candidatas[cod_oc] = fecha_str
        time.sleep(0.25)

    # Limitar a máximo 350 candidatas más recientes para garantizar ejecución < 2 minutos
    lista_candidatas = list(candidatas.items())[:350]
    print(f"[MP OC] Órdenes clínicas pre-filtradas a inspeccionar: {len(lista_candidatas)} (de {len(candidatas)} totales)", flush=True)

    vinculadas = 0
    for cod_oc, f_str in lista_candidatas:
        data_det = get_mp_con_reintento(url_oc, {"codigo": cod_oc, "ticket": TICKET_MERCADOPUBLICO}, timeout=15, max_reintentos=2)
        if not data_det:
            continue
        det_list = data_det.get("Listado") or []
        if not det_list:
            continue
        oc_det = det_list[0]

        cod_lic = normalizar_codigo(oc_det.get("CodigoLicitacion"))
        if not cod_lic or cod_lic not in set_codigos_interes:
            time.sleep(0.2)
            continue

        prov = oc_det.get("Proveedor") or {}
        rut_prov = str(prov.get("RutSucursal") or prov.get("RutProveedor") or "")
        nom_prov = str(prov.get("Nombre") or "")
        if not es_proveedor_redsalud(rut_prov, nom_prov):
            time.sleep(0.2)
            continue

        est_txt = str(oc_det.get("Estado") or "").strip()
        if "CANCEL" in est_txt.upper():
            continue

        monto_oc = parsear_monto_clp(oc_det.get("TotalNeto") or oc_det.get("Total"))
        fecha_oc = str((oc_det.get("Fechas") or {}).get("FechaEnvio") or f_str)[:10]

        bucket = ocs_por_lic.setdefault(cod_lic, {})
        if cod_oc not in bucket:
            vinculadas += 1
        bucket[cod_oc] = {
            "codigo_oc": cod_oc,
            "monto": monto_oc,
            "estado": est_txt or "Aceptada",
            "fecha": fecha_oc
        }
        print(f"  -> OC Vinculada: {cod_oc} | Lic: {cod_lic} | Monto: ${monto_oc:,}", flush=True)
        time.sleep(0.25)

    print(f"[MP OC] Total nuevas OC vinculadas a RedSalud: {vinculadas}", flush=True)
    return ocs_por_lic

# ==========================================
# 5. ORQUESTADOR DE REPORTE DE CONSUMO OC
# ==========================================
def generar_reporte_consumo():
    print("=== GENERANDO REPORTE CALIBRADO DE CONSUMO OC REDSALUD ===", flush=True)
    client, sa_email = obtener_cliente_gspread()
    print(f"Autenticado como: {sa_email}", flush=True)

    ss_maestra, universo_licitaciones = cargar_universo_local(client)
    codigos_interes = list(universo_licitaciones.keys())
    print(f"Total licitaciones en universo a evaluar: {len(codigos_interes)}", flush=True)

    ocs_por_lic = cargar_ocs_desde_pestana_local(ss_maestra)
    ocs_por_lic = consultar_ocs_mercado_publico_rapido(ocs_por_lic, codigos_interes)

    ocs_por_lic.setdefault("1057402-55-LE26", {}).setdefault(
        "1057402-1450-SE26",
        {"codigo_oc": "1057402-1450-SE26", "monto": 4092000, "estado": "Aceptada", "fecha": ""}
    )

    encabezados = [
        "N°",
        "Código Proceso",
        "Filial RedSalud",
        "Organismo / Comprador",
        "Nombre Proceso / Servicio",
        "Estado Oferta",
        "Presupuesto Adjudicado (CLP)",
        "N° OCs Emitidas",
        "Monto Total Consumido OC (CLP)",
        "Saldo Disponible (CLP)",
        "% Consumo",
        "Estado del Contrato / Consumo",
        "Registro de OCs"
    ]

    codigos_ordenados = sorted(
        codigos_interes,
        key=lambda c: (0 if c in ocs_por_lic else 1, 0 if c in CODIGOS_OBJETIVO else 1, c)
    )

    filas_reporte = []
    for idx, cod in enumerate(codigos_ordenados, start=1):
        loc = universo_licitaciones[cod]
        aud = TECHOS_CONTRATOS_AUDITADOS.get(cod, {})

        org = aud.get("organismo") or loc.get("organismo") or f"Institución Pública ({cod.split('-')[0]})"
        filial = aud.get("filial") or loc.get("filial") or "RedSalud (Por asignar)"
        nom = aud.get("nombre") or loc.get("nombre") or f"Convenio Asistencial {cod}"
        presupuesto = aud.get("monto") or loc.get("monto") or 0
        est = "Adjudicada"

        dict_ocs = ocs_por_lic.get(cod, {})
        lista_ocs = sorted(dict_ocs.values(), key=lambda x: x["codigo_oc"])
        cant_ocs = len(lista_ocs)
        consumo_total = sum(x["monto"] for x in lista_ocs)
        str_ocs = " | ".join(f"{x['codigo_oc']} (${x['monto']:,.0f})".replace(",", ".") for x in lista_ocs) if cant_ocs > 0 else "Sin OC emitidas"

        saldo = max(0, presupuesto - consumo_total)
        porc_consumo = round((consumo_total / presupuesto) * 100, 2) if presupuesto > 0 else 0.0

        if porc_consumo >= 100 and presupuesto > 0:
            estado_consumo = "100% Consumido (Completado)"
        elif porc_consumo >= 75:
            estado_consumo = "Consumo Alto (>75%)"
        elif cant_ocs > 0:
            estado_consumo = "En Ejecución (Con OC Emitidas)"
        else:
            estado_consumo = "Adjudicado / En Ejecución (Pendiente OC)"

        filas_reporte.append([
            idx,
            cod,
            filial,
            org,
            nom,
            est,
            f"${presupuesto:,.0f}".replace(",", "."),
            cant_ocs,
            f"${consumo_total:,.0f}".replace(",", "."),
            f"${saldo:,.0f}".replace(",", "."),
            f"{porc_consumo:.1f}%",
            estado_consumo,
            str_ocs
        ])

    ws_reporte = next((w for w in ss_maestra.worksheets() if w.title.strip().lower() == HOJA_REPORTE.lower()), None)
    if not ws_reporte:
        ws_reporte = ss_maestra.add_worksheet(title=HOJA_REPORTE, rows=len(filas_reporte) + 50, cols=len(encabezados) + 2)

    ws_reporte.resize(rows=len(filas_reporte) + 20, cols=len(encabezados) + 2)
    ws_reporte.clear()

    todo = [encabezados] + filas_reporte
    col_fin = gspread.utils.rowcol_to_a1(1, len(encabezados)).replace("1", "")
    ws_reporte.update(range_name=f"A1:{col_fin}{len(todo)}", values=todo)
    print(f"=== Reporte actualizado: {len(filas_reporte)} licitaciones | {len(ocs_por_lic)} con OC asociadas ===", flush=True)

if __name__ == "__main__":
    generar_reporte_consumo()
