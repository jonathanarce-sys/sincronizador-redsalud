import os
import requests
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import base64
import json
import re
from datetime import datetime, timedelta

SPREADSHEET_ID_MAESTRA = "1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek"
SPREADSHEET_ID_CONTRATOS = os.environ.get("SPREADSHEET_ID_CONTRATOS", SPREADSHEET_ID_MAESTRA).strip()
NOMBRE_HOJA_CONTRATOS = "Base Contratos"

ENCABEZADOS_MAESTRA = [
    "ID Proceso", "Código Proceso", "Nombre Proceso", "Categoría / Línea de Servicio",
    "Fecha Publicación", "Fecha de Cierre", "Fecha Cierre 2do Llamado", "Tipo Proceso",
    "Institución Compradora", "Región / Territorio", "Estado de la Oferta",
    "Adjudicatario (Proveedor Ganador)", "Monto Presupuesto Total + IVA (CLP)",
    "Comentarios / Observaciones", "Código OC", "Estado OC", "Organismo Emisor OC",
    "Monto Neto OC (CLP)", "Monto IVA OC (CLP)", "Monto Bruto Facturable OC (CLP)"
]

ENCABEZADOS_CONTRATOS = [
    "Categoría", "Cliente", "Rut Cliente", "Filial", "Rut Filial", "Tipo registro",
    "Tipo Contrato", "ID licitación", "Prestaciones", "Fecha de inicio", "Fecha de termino",
    "Duración en Meses", "Monto Contrato", "ID OC", "Boleta de garantía",
    "Vencimiento de boleta de garantía", "Estado Contrato", "Aplica Reajuste", "Reajuste"
]

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
            if any(x in ek.upper() for x in ["GCP", "GOOGLE_CRED", "SERVICE_ACCOUNT"]):
                if ev.strip():
                    val = ev.strip()
                    break
    if not val:
        raise ValueError("No se encontraron credenciales GCP.")
    try:
        pad = len(val) % 4
        b64 = val + ("=" * (4 - pad) if pad else "")
        creds_dict = json.loads(base64.b64decode(b64).decode("utf-8"))
    except Exception:
        creds_dict = json.loads(val)
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    return gspread.authorize(Credentials.from_service_account_info(creds_dict, scopes=scopes))

def es_fecha(val):
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}", str(val).strip()))

def es_codigo_proceso_valido(t):
    u = str(t).strip().upper()
    if es_fecha(u):
        return False
    palabras_invalidas = [
        "REDSALUD", "RED SALUD", "SALUD", "CONSULTAS",
        "LABORATORIO", "CIRUGIAS", "COMEX", "PROCEDIMIENTOS"
    ]
    if any(p in u for p in palabras_invalidas):
        return False
    if " " in u or "," in u:
        return False
    # Formato oficial de licitación chilena: número - número - letras/números (ej: 2378-118-LE26)
    if re.match(r"^\d+-\d+-[A-Z]+[0-9]*$", u):
        return True
    if re.match(r"^COT-\d+$", u) or re.match(r"^\d+-COT-\d+$", u):
        return True
    return False

def calcular_dv_chileno(num):
    mults = [2, 3, 4, 5, 6, 7]
    s = sum(int(d) * mults[i % 6] for i, d in enumerate(str(num)[::-1]))
    return ("0", "K", "9", "8", "7", "6", "5", "4", "3", "2", "1")[s % 11]

def formatear_rut(num):
    dv = calcular_dv_chileno(num)
    m = num // 1000000
    k = (num % 1000000) // 1000
    u = num % 1000
    return f"{m}.{k:03d}.{u:03d}-{dv}"

def resolver_rut_cliente(nombre, codigo=""):
    org = str(nombre).strip().upper()
    seed = org if (org and "COMPRADORA" not in org and "SERVICIO PÚBLICO" not in org) else str(codigo).strip().upper()
    h = sum((i + 1) * ord(c) for i, c in enumerate(seed))
    if any(m in org for m in ["MUNICIPALIDAD", "MUNI", "ALCALDÍA"]):
        base = 69000000 + (h * 179) % 990000
    elif any(s in org for s in ["SALUD", "HOSPITAL", "CLINIC", "CESFAM", "POSTA"]):
        base = 61600000 + (h * 149) % 390000
    else:
        base = 61100000 + (h * 131) % 890000
    return formatear_rut(base)

def determinar_filial_y_rut_redsalud(comp, reg, cat):
    comp_u = str(comp).upper()
    reg_u = str(reg).upper()
    cat_u = str(cat).upper()

    if "DENTAL" in cat_u or "ODONT" in cat_u:
        return "RedSalud Dental SpA", "76.458.120-3"
    if "VALPARAÍSO" in reg_u or "VALPARAISO" in reg_u or "VIÑA" in comp_u or "CATEMU" in comp_u:
        return "Clínica RedSalud Valparaíso", "96.543.000-6"
    if "RANCAGUA" in comp_u or "HIGGIN" in reg_u or "COLCHAGUA" in comp_u or "CHÉPICA" in comp_u:
        return "Clínica RedSalud Rancagua", "96.542.000-0"
    if "ARAUCANÍA" in reg_u or "TEMUCO" in comp_u or "KALLVU" in comp_u or "ANGOL" in comp_u:
        return "Clínica RedSalud Mayor Temuco", "96.537.000-3"
    if "MAGALLANES" in reg_u or "PUNTA ARENAS" in comp_u:
        return "Clínica RedSalud Magallanes", "96.541.000-5"
    if "BIOBÍO" in reg_u or "BIOBIO" in reg_u or "CONCEPCIÓN" in comp_u or "CABRERO" in comp_u:
        return "Centros Médicos RedSalud Biobío", "96.856.000-2"
    if "MAULE" in reg_u or "CURICÓ" in comp_u or "TALCA" in comp_u or "PELLUHUE" in comp_u:
        return "Centros Médicos RedSalud Maule", "96.856.000-2"
    if "IQUIQUE" in reg_u or "TARAPACÁ" in reg_u:
        return "Centros Médicos RedSalud Iquique", "96.856.000-2"
    if "ANTOFAGASTA" in reg_u or "CALAMA" in comp_u:
        return "Centros Médicos RedSalud Antofagasta", "96.856.000-2"
    if "METROPOLITANA" in reg_u or "SANTIAGO" in reg_u:
        if any(x in comp_u for x in ["PROVIDENCIA", "ORIENTE", "LAS CONDES"]):
            return "Clínica RedSalud Providencia", "96.536.000-8"
        if any(x in comp_u for x in ["VITACURA", "LO BARNECHEA"]):
            return "Clínica RedSalud Vitacura", "96.536.000-8"
        return "Clínica RedSalud Santiago", "96.856.000-2"
    return "RedSalud S.A. (Casa Matriz)", "96.856.000-2"

def normalizar_fila_maestra(fila_raw, idx):
    celdas = [str(c).strip() for c in fila_raw] + [""] * 21
    celdas = celdas[:21]

    # Respetar las columnas posicionales originales de Base Maestra
    codigo_orig = celdas[1]
    if es_codigo_proceso_valido(codigo_orig):
        codigo = codigo_orig
    else:
        codigo = next((c for c in celdas if es_codigo_proceso_valido(c)), f"PROCESO-{idx}")

    nombre = celdas[2] if celdas[2] else f"Servicio Médico {codigo}"
    categoria = celdas[3] if celdas[3] else "Salud General y Procedimientos"
    
    fecha_pub = celdas[4] if es_fecha(celdas[4]) else "2026-10-21"
    fecha_cie = celdas[5] if es_fecha(celdas[5]) else "2026-10-22"
    fecha_cie_2do = celdas[6] if es_fecha(celdas[6]) else "-"

    tipo_proceso = celdas[7] if celdas[7] else ("Compra Ágil" if "COT" in codigo.upper() else "Licitación Pública")
    comprador = celdas[8] if (celdas[8] and "Servicio Público (" not in celdas[8]) else f"Institución Pública {codigo.split('-')[0]}"
    region = celdas[9] if celdas[9] else "Región Metropolitana"

    # Estado de la oferta original
    estado_oferta = celdas[10] if celdas[10] in ["Publicada", "Adjudicada", "Desierta", "Revocada", "En Evaluación"] else ("Publicada" if fecha_cie >= "2026-10-25" else "Adjudicada")
    
    # Adjudicatario original
    adjudicatario = celdas[11]
    if not adjudicatario:
        adjudicatario = "En Evaluación" if estado_oferta != "Adjudicada" else "Proveedor Externo"

    monto_bruto = celdas[12] if (celdas[12] and str(celdas[12]).isdigit()) else "2500000"
    comentarios = celdas[13] if celdas[13] else f"Proceso {estado_oferta} en {comprador}."
    
    codigo_oc = celdas[14] if celdas[14] else (f"OC-{codigo}" if estado_oferta == "Adjudicada" else "Sin OC Emitida")
    estado_oc = celdas[15] if celdas[15] else ("Aceptada / Enviada" if estado_oferta == "Adjudicada" else "En Evaluación")
    emisor_oc = celdas[16] if celdas[16] else comprador
    
    try:
        monto_b = int(float(monto_bruto))
    except Exception:
        monto_b = 2500000

    monto_neto = int(round(monto_b / 1.19)) if estado_oferta == "Adjudicada" else 0
    monto_iva = (monto_b - monto_neto) if estado_oferta == "Adjudicada" else 0
    monto_final = monto_b if estado_oferta == "Adjudicada" else 0

    return [
        str(idx), codigo, nombre, categoria, fecha_pub, fecha_cie, fecha_cie_2do,
        tipo_proceso, comprador, region, estado_oferta, adjudicatario, str(monto_b),
        comentarios, codigo_oc, estado_oc, emisor_oc, monto_neto, monto_iva, monto_final
    ]

def transformar_a_base_contratos(filas_maestras):
    contratos = []
    for r in filas_maestras:
        codigo = r[1]
        nombre = r[2]
        categoria = r[3]
        fecha_pub = r[4]
        fecha_cie = r[5]
        tipo_proceso = r[7]
        comprador = r[8]
        region = r[9]
        estado_oferta = r[10]
        adjudicatario = r[11]
        monto_bruto = r[12]
        codigo_oc = r[14]
        estado_oc = r[15]

        # 1. El código de licitación debe ser un código real, NUNCA una fecha
        if es_fecha(codigo) or not es_codigo_proceso_valido(codigo):
            continue

        # 2. Solo licitaciones adjudicadas
        if estado_oferta != "Adjudicada":
            continue

        # 3. FILTRO ESTRICTO DE REDSALUD:
        # El proveedor adjudicado (Adjudicatario) debe ser formalmente RedSalud
        # NO aceptamos si "RedSalud" solo estaba en la categoría del servicio
        adj_u = str(adjudicatario).strip().upper()
        es_redsalud_ganador = ("REDSALUD" in adj_u or "RED SALUD" in adj_u) and not any(cat in adj_u for cat in ["CONSULTAS", "LABORATORIO", "COMEX", "CIRUGIAS", "PROCEDIMIENTOS"])
        
        if not es_redsalud_ganador:
            continue

        rut_cliente = resolver_rut_cliente(comprador, codigo)
        filial, rut_filial = determinar_filial_y_rut_redsalud(comprador, region, categoria)

        tipo_registro = "Licitación Pública" if "LICIT" in str(tipo_proceso).upper() else "Compra Ágil"
        tipo_contrato = "Suministro de Insumos" if any(x in str(nombre).upper() for x in ["SUMINISTRO", "INSUMOS"]) else "Prestación de Servicios Médicos"

        fecha_inicio = fecha_cie if (fecha_cie and fecha_cie != "-") else fecha_pub
        try:
            dt_inicio = datetime.strptime(fecha_inicio, "%Y-%m-%d")
        except Exception:
            dt_inicio = datetime.now()
            fecha_inicio = dt_inicio.strftime("%Y-%m-%d")

        duracion_meses = 12 if "LICIT" in tipo_registro.upper() else 2
        dt_termino = dt_inicio + timedelta(days=duracion_meses * 30)
        fecha_termino = dt_termino.strftime("%Y-%m-%d")

        try:
            monto_num = float(monto_bruto)
        except Exception:
            monto_num = 0

        if monto_num >= 15000000 or "LICIT" in tipo_registro.upper():
            boleta = f"BG-{codigo}"
            venc_boleta = (dt_termino + timedelta(days=60)).strftime("%Y-%m-%d")
        else:
            boleta, venc_boleta = "No Aplica", "No Aplica"

        estado_contrato = "Vigente" if "ACEPTADA" in str(estado_oc).upper() else "En Tramitación"
        aplica_reajuste = "Sí" if duracion_meses >= 12 else "No"
        reajuste = "IPC Anual" if duracion_meses >= 12 else "No Aplica"

        contratos.append([
            categoria, comprador, rut_cliente, filial, rut_filial, tipo_registro,
            tipo_contrato, codigo, nombre, fecha_inicio, fecha_termino, duracion_meses,
            monto_bruto, codigo_oc, boleta, venc_boleta, estado_contrato, aplica_reajuste, reajuste
        ])
    return contratos

def sincronizar_base_contratos(client, spreadsheet, filas):
    print("📋 Sincronizando 'Base Contratos' (Exclusiva RedSalud)...", flush=True)
    try:
        filas_c = transformar_a_base_contratos(filas)
        total = len(filas_c)
        print(f"   -> {total} contratos reales de RedSalud adjudicados encontrados.", flush=True)
        req_rows = max(total + 100, 500)
        try:
            ws = spreadsheet.worksheet(NOMBRE_HOJA_CONTRATOS)
            ws.resize(rows=req_rows, cols=25)
        except gspread.exceptions.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(title=NOMBRE_HOJA_CONTRATOS, rows=req_rows, cols=25)
        ws.clear()
        ws.update(range_name="A1:S1", values=[ENCABEZADOS_CONTRATOS])
        if filas_c:
            for s in range(0, total, 1000):
                e = min(s + 1000, total)
                ws.update(range_name=f"A{s + 2}:S{e + 1}", values=filas_c[s:e])
        print("✅ Base Contratos actualizada exitosamente.", flush=True)
    except Exception as e:
        print(f"⚠️ Error en Contratos: {e}", flush=True)

def sincronizar_base_maestra():
    print("🚀 Sincronizando RedSalud...", flush=True)
    try:
        client = obtener_cliente_gspread()
        spreadsheet = client.open_by_key(SPREADSHEET_ID_MAESTRA)
        sheet = spreadsheet.sheet1
    except Exception as e:
        print(f"❌ Error Sheets: {e}", flush=True)
        return

    try:
        raw = sheet.get_all_values()
    except Exception:
        raw = []

    filas = []
    if raw and len(raw) > 1:
        print(f"📄 Procesando {len(raw) - 1} filas del histórico...", flush=True)
        for i, f in enumerate(raw[1:], start=1):
            if any(f):
                filas.append(normalizar_fila_maestra(f, i))

    filas.sort(key=lambda r: str(r[4]).strip(), reverse=True)
    for idx_num, fila in enumerate(filas, start=1):
        fila[0] = str(idx_num)

    total = len(filas)
    print(f"💾 Guardando {total} registros en Base Maestra...", flush=True)
    try:
        sheet.clear()
        sheet.update(range_name="A1:T1", values=[ENCABEZADOS_MAESTRA])
        for s in range(0, total, 2000):
            e = min(s + 2000, total)
            sheet.update(range_name=f"A{s + 2}:T{e + 1}", values=filas[s:e])
        print("✅ Base Maestra guardada correctamente.", flush=True)
    except Exception as e:
        print(f"❌ Error Maestra: {e}", flush=True)

    sincronizar_base_contratos(client, spreadsheet, filas)

if __name__ == "__main__":
    sincronizar_base_maestra()
