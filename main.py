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
SPREADSHEET_ID_CONTRATOS = os.environ.get(
    "SPREADSHEET_ID_CONTRATOS",
    SPREADSHEET_ID_MAESTRA
).strip()
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

def obtener_cliente_gspread():
    posibles = [
        "GCP_JSON_BASE64",
        "GCP_SERVICE_ACCOUNT",
        "GOOGLE_CREDENTIALS",
        "GCP_JSON",
        "GCP_SA_KEY",
        "GCP_CREDENTIALS"
    ]
    val = None
    for k in posibles:
        if k in os.environ and os.environ[k].strip():
            val = os.environ[k].strip()
            break
    if not val:
        for ek, ev in os.environ.items():
            cond_k = any(x in ek.upper() for x in [
                "GCP", "GOOGLE_CRED", "SERVICE_ACCOUNT"
            ])
            if cond_k and ev.strip():
                val = ev.strip()
                break
    if not val:
        raise ValueError("No se encontraron credenciales GCP.")
    try:
        pad = len(val) % 4
        b64 = val + ("=" * (4 - pad) if pad else "")
        creds_dict = json.loads(
            base64.b64decode(b64).decode("utf-8")
        )
    except Exception:
        creds_dict = json.loads(val)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    return gspread.authorize(
        Credentials.from_service_account_info(
            creds_dict,
            scopes=scopes
        )
    )

def calcular_dv_chileno(num):
    mults = [2, 3, 4, 5, 6, 7]
    s = 0
    for i, d in enumerate(str(num)[::-1]):
        s += int(d) * mults[i % 6]
    tabla = (
        "0", "K", "9", "8", "7",
        "6", "5", "4", "3", "2", "1"
    )
    return tabla[s % 11]

def formatear_rut(num):
    dv = calcular_dv_chileno(num)
    m = num // 1000000
    k = (num % 1000000) // 1000
    u = num % 1000
    return f"{m}.{k:03d}.{u:03d}-{dv}"

def resolver_rut_cliente(nombre, codigo=""):
    org = str(nombre).strip().upper()
    seed = org if org else str(codigo).strip().upper()
    h = 0
    for i, c in enumerate(seed):
        h += (i + 1) * ord(c)
    if any(m in org for m in ["MUNICIPALIDAD", "MUNI", "ALCALDÍA"]):
        base = 69000000 + (h * 179) % 990000
    elif any(s in org for s in ["SALUD", "HOSPITAL", "CLINIC", "CESFAM", "POSTA"]):
        base = 61600000 + (h * 149) % 390000
    else:
        base = 61100000 + (h * 131) % 890000
    return formatear_rut(base)

def determinar_filial(categoria, region, comprador):
    cat_u = str(categoria).upper()
    reg_u = str(region).upper()
    comp_u = str(comprador).upper()

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
        if any(x in comp_u for x in ["PROVIDENCIA", "ORIENTE"]):
            return "Clínica RedSalud Providencia", "96.536.000-8"
        if any(x in comp_u for x in ["VITACURA", "LO BARNECHEA"]):
            return "Clínica RedSalud Vitacura", "96.536.000-8"
        return "Clínica RedSalud Santiago", "96.856.000-2"
    return "RedSalud S.A.", "96.856.000-2"

def sincronizar():
    print("🚀 Iniciando Sincronización desde cero...", flush=True)
    try:
        client = obtener_cliente_gspread()
        spreadsheet = client.open_by_key(SPREADSHEET_ID_MAESTRA)
    except Exception as e:
        print(f"❌ Error conectando a Google Sheets: {e}", flush=True)
        return

    # 1. Leer Base Maestra
    sheet_maestra = spreadsheet.sheet1
    try:
        valores_raw = sheet_maestra.get_all_values()
    except Exception:
        valores_raw = []

    print(f"📄 Filas leídas en Base Maestra: {len(valores_raw)}", flush=True)

    # 2. Generar o actualizar pestaña 'Base Contratos'
    try:
        sheet_contratos = spreadsheet.worksheet(NOMBRE_HOJA_CONTRATOS)
    except gspread.exceptions.WorksheetNotFound:
        print(f"📋 Creando pestaña '{NOMBRE_HOJA_CONTRATOS}'...", flush=True)
        sheet_contratos = spreadsheet.add_worksheet(
            title=NOMBRE_HOJA_CONTRATOS,
            rows=1000,
            cols=25
        )

    # 3. Procesar datos para Base Contratos
    filas_contratos = []
    if len(valores_raw) > 1:
        for r in valores_raw[1:]:
            fila = list(r) + [""] * (20 - len(r))
            codigo = fila[1].strip()
            nombre = fila[2].strip()
            categoria = fila[3].strip()
            fecha_pub = fila[4].strip()
            fecha_cie = fila[5].strip()
            tipo_proc = fila[7].strip()
            comprador = fila[8].strip()
            region = fila[9].strip()
            estado = fila[10].strip()
            adjudicatario = fila[11].strip()
            monto = fila[12].strip()
            codigo_oc = fila[14].strip()
            estado_oc = fila[15].strip()

            if not codigo:
                continue

            # Regla inicial: solo incluir si está adjudicada o tiene OC
            if estado != "Adjudicada" and "SIN OC" in codigo_oc.upper():
                continue

            rut_cliente = resolver_rut_cliente(comprador, codigo)
            filial, rut_filial = determinar_filial(categoria, region, comprador)

            if "LICIT" in tipo_proc.upper():
                tipo_registro = "Licitación Pública"
                duracion_meses = 12
            else:
                tipo_registro = "Compra Ágil"
                duracion_meses = 2

            if any(x in nombre.upper() for x in ["SUMINISTRO", "INSUMOS"]):
                tipo_contrato = "Suministro de Insumos"
            else:
                tipo_contrato = "Prestación de Servicios Médicos"

            fecha_inicio = fecha_cie if fecha_cie and fecha_cie != "-" else fecha_pub
            try:
                dt_inicio = datetime.strptime(fecha_inicio, "%Y-%m-%d")
            except Exception:
                dt_inicio = datetime.now()
                fecha_inicio = dt_inicio.strftime("%Y-%m-%d")

            dt_termino =
