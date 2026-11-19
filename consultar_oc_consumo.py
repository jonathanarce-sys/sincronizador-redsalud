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

LICITALAB_TOKEN = (
    os.environ.get("LICITALAB_TOKEN") or 
    os.environ.get("LICITALAB_API_KEY") or 
    os.environ.get("TOKEN_LICITALAB") or 
    ""
).strip()

TICKET_MERCADOPUBLICO = (
    os.environ.get("MERCADOPUBLICO_TICKET") or
    os.environ.get("MP_TICKET") or
    "F8537A18-6766-4DEF-9E59-426B4FEE5844"
).strip()

# Ventana de días hacia atrás para escanear OC emitidas a RUTs RedSalud en Mercado Público
DIAS_ESCANE0_OC = int(os.environ.get("DIAS_ESCANEO_OC", "120"))

# Catálogo oficial de RUTs de Clínicas y Centros Médicos RedSalud
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

# Estados válidos de OC en Mercado Público (se excluye estado 5 = Cancelada)
ESTADOS_OC_VALIDOS = {"4", "6", "9", "12", "ENVIADA A PROVEEDOR", "ACEPTADA", "EN PROCESO", "RECEPCION CONFORME", "RECEPCIÓN CONFORME"}

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
# 2. UTILIDADES DE AUTENTICACIÓN Y PARSEO
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

# ==========================================
# 3. INDEXACIÓN DE DATOS LOCALES (BASE MADRE + CONSOLIDADO)
# ==========================================
def cargar_universo_local(client):
    """Combina licitaciones de Base Madre, hoja Consolidado de Contratos y CODIGOS_OBJETIVO."""
    universo = {}

    # A. Leer hoja 'consolidado' de Contratos RedSalud (tiene filial, presupuesto y códigos adjudicados)
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

    # B. Enriquecer desde Base Madre LicitaLAB
    ss_maestra = client.open_by_key(SPREADSHEET_ID_MAESTRA)
    for ws in ss_maestra.worksheets():
        if ws.title.strip().lower() == HOJA_REPORTE.lower():
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

    # C. Asegurar que todos los CODIGOS_OBJETIVO estén presentes
    for cod_obj in CODIGOS_OBJETIVO:
        cu = normalizar_codigo(cod_obj)
        universo.setdefault(cu, {"organismo": "", "filial": "", "nombre": "", "monto": 0, "estado": "Adjudicada"})

    return ss_maestra, universo

# ==========================================
# 4. EXTRACCIÓN DE ÓRDENES DE COMPRA (MERCADO PÚBLICO + LICITALAB)
# ==========================================
def obtener_ocs_por_licitacion_licitalab():
    """Consulta Órdenes de Compra registradas en LicitaLAB API BI y las agrupa por código de licitación."""
    ocs_por_lic = {}
    if not LICITALAB_TOKEN:
        return ocs_por_lic

    headers = {"x-api-key": LICITALAB_TOKEN, "Accept": "application/json", "User-Agent": "RedSalud-Consumo/2.0"}
    endpoints = [
        "https://biapi.licitalab.cl/bi/v2/purchase-orders",
        "https://biapi.licitalab.cl/bi/v2/orders"
    ]
    for url in endpoints:
        try:
            resp = requests.get(url, headers=headers, params={"limit": 1000}, timeout=25)
            if resp.status_code != 200:
                continue
            data = resp.json()
            items = data if isinstance(data, list) else (data.get("data") or data.get("orders") or data.get("items") or [])
            for oc in items:
                cod_oc = normalizar_codigo(oc.get("ORDER_CODE") or oc.get("code") or oc.get("Codigo"))
                cod_lic = normalizar_codigo(oc.get("OPPORTUNITY_CODE") or oc.get("tender_code") or oc.get("CodigoLicitacion"))
                estado = str(oc.get("ORDER_STATUS") or oc.get("status") or oc.get("Estado") or "").strip().upper()
                monto = parsear_monto_clp(oc.get("TOTAL_AMOUNT") or oc.get("amount") or oc.get("TotalNeto") or oc.get("Total"))
                if not cod_oc or not cod_lic or "CANCEL" in estado:
                    continue
                bucket = ocs_por_lic.setdefault(cod_lic, {})
                bucket[cod_oc] = {
                    "codigo_oc": cod_oc,
                    "monto": monto,
                    "estado": estado,
                    "fecha": str(oc.get("SENT_DATE") or oc.get("created_at") or "")[:10]
                }
            if ocs_por_lic:
                print(f"[LicitaLAB OC] Licitaciones con OC detectadas: {len(ocs_por_lic)}", flush=True)
                break
        except Exception as e:
            print(f"[LicitaLAB OC] Aviso en {url}: {repr(e)}", flush=True)
    return ocs_por_lic

def obtener_ocs_mercado_publico_por_ruts(ocs_por_lic):
    """
    Consulta la API oficial de Órdenes de Compra de Mercado Público para todos los RUTs
    de clínicas y centros médicos RedSalud dentro de la ventana configurada.
    """
    if not TICKET_MERCADOPUBLICO:
        return ocs_por_lic

    url_oc = "https://api.mercadopublico.cl/servicios/v1/publico/ordenesdecompra.json"
    hoy = datetime.now()
    # Muestreo cada 3 días o diario según ventana para cubrir histórico sin exceder límites de API
    paso = 1 if DIAS_ESCANE0_OC <= 45 else 2
    fechas = [(hoy - timedelta(days=d)).strftime("%d%m%Y") for d in range(0, DIAS_ESCANE0_OC + 1, paso)]

    print(f"[MP OC] Escaneando {len(fechas)} fechas en Mercado Público para los {len(MAPA_RUT_FILIAL_REDSALUD)} RUTs RedSalud...", flush=True)
    ocs_nuevas_detectadas = 0

    for fecha_str in fechas:
        try:
            resp = requests.get(url_oc, params={"fecha": fecha_str, "ticket": TICKET_MERCADOPUBLICO}, timeout=20)
            if resp.status_code != 200:
                continue
            listado = resp.json().get("Listado") or []
            for item in listado:
                cod_oc = normalizar_codigo(item.get("Codigo"))
                estado_cod = str(item.get("CodigoEstado") or "").strip().upper()
                if not cod_oc or estado_cod == "5":  # Excluir Canceladas
                    continue

                # Consultar detalle de OC que coincidan con organismos compradores de licitaciones objetivo
                # o verificar proveedor en detalle
                det_resp = requests.get(url_oc, params={"codigo": cod_oc, "ticket": TICKET_MERCADOPUBLICO}, timeout=15)
                if det_resp.status_code != 200:
                    continue
                det_list = det_resp.json().get("Listado") or []
                if not det_list:
                    continue
                oc_det = det_list[0]
                prov = oc_det.get("Proveedor") or {}
                rut_prov = str(prov.get("RutSucursal") or prov.get("RutProveedor") or "")
                nom_prov = str(prov.get("Nombre") or "")

                if not es_proveedor_redsalud(rut_prov, nom_prov):
                    continue

                cod_lic = normalizar_codigo(oc_det.get("CodigoLicitacion"))
                if not cod_lic or cod_lic in ("NONE", "NULL", "-"):
                    continue

                est_txt = str(oc_det.get("Estado") or estado_cod).strip()
                monto_oc = parsear_monto_clp(oc_det.get("TotalNeto") or oc_det.get("Total"))
                fecha_oc = str((oc_det.get("Fechas") or {}).get("FechaEnvio") or fecha_str)[:10]

                bucket = ocs_por_lic.setdefault(cod_lic, {})
                if cod_oc not in bucket:
                    ocs_nuevas_detectadas += 1
                bucket[cod_oc] = {
                    "codigo_oc": cod_oc,
                    "monto": monto_oc,
                    "estado": est_txt,
                    "fecha": fecha_oc
                }
        except Exception:
            pass
        time.sleep(0.15)

    print(f"[MP OC] Total OC vinculadas a RedSalud consolidadas: {ocs_nuevas_detectadas}", flush=True)
    return ocs_por_lic

def consultar_licitacion_mp_detalle(codigo):
    """Consulta ficha real de licitación en Mercado Público sumando solo ítems ganados por RedSalud."""
    url_mp = "https://api.mercadopublico.cl/servicios/v1/publico/licitaciones.json"
    try:
        r = requests.get(url_mp, params={"codigo": codigo, "ticket": TICKET_MERCADOPUBLICO}, timeout=12)
        if r.status_code != 200:
            return {}
        listado = r.json().get("Listado") or []
        if not listado:
            return {}
        lic = listado[0]
        comp = lic.get("Comprador") or {}
        suma_rs = 0
        filial_det = ""

        for it in (lic.get("Items") or {}).get("Listado") or []:
            adj = it.get("Adjudicacion") or {}
            if not adj:
                continue
            rut_p = str(adj.get("RutProveedor") or "")
            nom_p = str(adj.get("NombreProveedor") or "")
            if es_proveedor_redsalud(rut_p, nom_p):
                try:
                    suma_rs += float(adj.get("MontoUnitario") or 0) * float(adj.get("Cantidad") or 1)
                except Exception:
                    pass
                r_base = extraer_rut_base(rut_p)
                if r_base in MAPA_RUT_FILIAL_REDSALUD and not filial_det:
                    filial_det = MAPA_RUT_FILIAL_REDSALUD[r_base][0]

        return {
            "organismo": str(comp.get("NombreOrganismo") or "").strip(),
            "nombre": str(lic.get("Nombre") or "").strip(),
            "estado": str(lic.get("Estado") or "").strip(),
            "monto": int(round(suma_rs)),
            "filial": filial_det
        }
    except Exception:
        return {}

# ==========================================
# 5. ORQUESTADOR DE REPORTE DE CONSUMO OC
# ==========================================
def generar_reporte_consumo():
    print("=== GENERANDO REPORTE CALIBRADO DE CONSUMO OC REDSALUD ===", flush=True)
    client, sa_email = obtener_cliente_gspread()
    print(f"Autenticado como: {sa_email}", flush=True)

    ss_maestra, universo_licitaciones = cargar_universo_local(client)
    print(f"Total licitaciones en universo a evaluar: {len(universo_licitaciones)}", flush=True)

    # 1. Recolectar Órdenes de Compra desde LicitaLAB + Mercado Público
    ocs_por_lic = obtener_ocs_por_licitacion_licitalab()
    ocs_por_lic = obtener_ocs_mercado_publico_por_ruts(ocs_por_lic)

    # Asegurar la OC auditada conocida si no entró por ventana de fechas
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

    # Ordenar priorizando las que ya tienen OC emitidas y luego CODIGOS_OBJETIVO
    codigos_ordenados = sorted(
        universo_licitaciones.keys(),
        key=lambda c: (0 if c in ocs_por_lic else 1, 0 if c in CODIGOS_OBJETIVO else 1, c)
    )

    filas_reporte = []
    for idx, cod in enumerate(codigos_ordenados, start=1):
        loc = universo_licitaciones[cod]
        aud = TECHOS_CONTRATOS_AUDITADOS.get(cod, {})

        org = aud.get("organismo") or loc.get("organismo") or ""
        filial = aud.get("filial") or loc.get("filial") or ""
        nom = aud.get("nombre") or loc.get("nombre") or ""
        presupuesto = aud.get("monto") or loc.get("monto") or 0
        est = "Adjudicada"

        # Completar datos faltantes desde Mercado Público si falta presupuesto, organismo o filial
        if presupuesto == 0 or not org or not filial:
            det_mp = consultar_licitacion_mp_detalle(cod)
            if det_mp:
                org = org or det_mp.get("organismo", "")
                nom = nom or det_mp.get("nombre", "")
                filial = filial or det_mp.get("filial", "")
                est = det_mp.get("estado") or est
                if presupuesto == 0 and det_mp.get("monto", 0) > 0:
                    presupuesto = det_mp["monto"]
            time.sleep(0.15)

        if not org:
            org = f"Institución Pública ({cod.split('-')[0]})"
        if not nom:
            nom = f"Convenio Asistencial {cod}"
        if not filial:
            filial = "RedSalud (Por asignar)"

        # Consolidar OCs vinculadas a esta licitación
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
