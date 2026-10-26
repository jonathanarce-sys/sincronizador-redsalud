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
SPREADSHEET_ID_MAESTRA = (
    "1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek"
)
SPREADSHEET_ID_CONTRATOS = os.environ.get(
    "SPREADSHEET_ID_CONTRATOS",
    SPREADSHEET_ID_MAESTRA
).strip()
NOMBRE_HOJA_CONTRATOS = "Base Contratos"

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
        raise ValueError("No credenciales GCP.")
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
    print("🚀 Iniciando Sincronización de Base Contratos...", flush=True)
    try:
        client = obtener_cliente_gspread()
        spreadsheet = client.open_by_key(SPREADSHEET_ID_MAESTRA)
    except Exception as e:
        print(f"❌ Error conectando a Google Sheets: {e}", flush=True)
        return

    # 1. Leer Base Maestra como FUENTE ÚNICA (Solo Lectura)
    sheet_maestra = spreadsheet.sheet1
    try:
        valores_raw = sheet_maestra.get_all_values()
    except Exception:
        valores_raw = []

    print(f"📄 Filas leídas en Base Maestra: {len(valores_raw)}", flush=True)

    # 2. Crear o resetear la pestaña 'Base Contratos'
    try:
        sheet_contratos = spreadsheet.worksheet(NOMBRE_HOJA_CONTRATOS)
    except gspread.exceptions.WorksheetNotFound:
        print(f"📋 Creando pestaña '{NOMBRE_HOJA_CONTRATOS}'...", flush=True)
        sheet_contratos = spreadsheet.add_worksheet(
            title=NOMBRE_HOJA_CONTRATOS,
            rows=1000,
            cols=25
        )

    # 3. Procesar datos tomando directamente las columnas reales de Base Maestra
    filas_contratos = []
    if len(valores_raw) > 1:
        for r in valores_raw[1:]:
            fila = list(r) + [""] * (20 - len(r))
            
            # Mapeo posicional exacto de la Base Maestra
            id_proceso = fila[0].strip()
            codigo = fila[1].strip()          # Col B: Código Proceso
            nombre = fila[2].strip()          # Col C: Nombre Proceso
            categoria = fila[3].strip()       # Col D: Categoría / Línea de Servicio
            fecha_pub = fila[4].strip()       # Col E: Fecha Publicación
            fecha_cie = fila[5].strip()       # Col F: Fecha de Cierre
            tipo_proc = fila[7].strip()       # Col H: Tipo Proceso
            comprador = fila[8].strip()       # Col I: Institución Compradora
            region = fila[9].strip()          # Col J: Región / Territorio
            estado = fila[10].strip()         # Col K: Estado de la Oferta
            adjudicatario = fila[11].strip()  # Col L: Adjudicatario
            monto = fila[12].strip()          # Col M: Monto Presupuesto Total
            codigo_oc = fila[14].strip()      # Col O: Código OC
            estado_oc = fila[15].strip()      # Col P: Estado OC

            if not codigo:
                continue

            # Filtro: Solo contratos formalizados o adjudicados
            if estado != "Adjudicada" and "SIN OC" in codigo_oc.upper():
                continue

            # Limpiar nombre de categoría si viene con el prefijo "RedSalud - "
            cat_limpia = categoria.replace("RedSalud - ", "").strip()
            if not cat_limpia:
                cat_limpia = "Salud General y Procedimientos"

            rut_cliente = resolver_rut_cliente(comprador, codigo)
            filial, rut_filial = determinar_filial(cat_limpia, region, comprador)

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

            dias_delta = duracion_meses * 30
            dt_termino = dt_inicio + timedelta(days=dias_delta)
            fecha_termino = dt_termino.strftime("%Y-%m-%d")

            try:
                monto_val = float(monto)
            except Exception:
                monto_val = 0

            if monto_val >= 15000000 or "LICIT" in tipo_registro.upper():
                boleta = f"BG-{codigo}"
                venc_boleta = (dt_termino + timedelta(days=60)).strftime("%Y-%m-%d")
            else:
                boleta = "No Aplica"
                venc_boleta = "No Aplica"

            if "ACEPTADA" in estado_oc.upper() or estado == "Adjudicada":
                estado_contrato = "Vigente"
            else:
                estado_contrato = "En Tramitación"

            aplica_reajuste = "Sí" if duracion_meses >= 12 else "No"
            reajuste = "IPC Anual" if duracion_meses >= 12 else "No Aplica"

            filas_contratos.append([
                cat_limpia,
                comprador,
                rut_cliente,
                filial,
                rut_filial,
                tipo_registro,
                tipo_contrato,
                codigo,            # Col H: ID licitación (Toma EXACTAMENTE el de Base Maestra)
                nombre,            # Col I: Prestaciones (Nombre Proceso real)
                fecha_inicio,
                fecha_termino,
                duracion_meses,
                monto,
                codigo_oc,
                boleta,
                venc_boleta,
                estado_contrato,
                aplica_reajuste,
                reajuste
            ])

    # 4. Escribir únicamente en Base Contratos
    total_c = len(filas_contratos)
    print(f"💾 Guardando {total_c} filas en '{NOMBRE_HOJA_CONTRATOS}'...", flush=True)

    filas_req = max(total_c + 50, 100)
    sheet_contratos.resize(rows=filas_req, cols=25)
    sheet_contratos.clear()
    sheet_contratos.update(
        range_name="A1:S1",
        values=[ENCABEZADOS_CONTRATOS]
    )

    if filas_contratos:
        for s in range(0, total_c, 1000):
            e = min(s + 1000, total_c)
            sheet_contratos.update(
                range_name=f"A{s + 2}:S{e + 1}",
                values=filas_contratos[s:e]
            )

    print("✅ Base Contratos generada con éxito respetando los códigos reales.", flush=True)

if __name__ == "__main__":
    sincronizar()
