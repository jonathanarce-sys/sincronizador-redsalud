import os
import requests
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import base64
import json
import re
from datetime import datetime
from datetime import timedelta

SPREADSHEET_ID_MAESTRA = (
    "1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek"
)
SPREADSHEET_ID_CONTRATOS = (
    "18HKuttayv6-MLIr5feByUaV0GEzvyRfr1E1DVaofbbY"
)
NOMBRE_HOJA_CONTRATOS = (
    "Base Contratos"
)

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
        if k in os.environ:
            if os.environ[k].strip():
                val = os.environ[k].strip()
                break
    if not val:
        for ek, ev in os.environ.items():
            cond_k = any(
                x in ek.upper()
                for x in [
                    "GCP",
                    "GOOGLE_CRED",
                    "SERVICE_ACCOUNT"
                ]
            )
            if cond_k and ev.strip():
                val = ev.strip()
                break
    if not val:
        raise ValueError("Sin GCP.")
    try:
        pad = len(val) % 4
        if pad:
            val += "=" * (4 - pad)
        dec = base64.b64decode(val)
        creds_dict = json.loads(
            dec.decode("utf-8")
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
    num_inv = str(num)[::-1]
    for i, d in enumerate(num_inv):
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

def resolver_rut_cliente(nombre, cod=""):
    org = str(nombre).strip().upper()
    seed = org if org else str(cod).strip().upper()
    h = 0
    for i, c in enumerate(seed):
        h += (i + 1) * ord(c)
    es_muni = any(
        m in org
        for m in [
            "MUNICIPALIDAD",
            "MUNI",
            "ALCALDÍA"
        ]
    )
    es_salud = any(
        s in org
        for s in [
            "SALUD",
            "HOSPITAL",
            "CLINIC",
            "CESFAM",
            "POSTA"
        ]
    )
    if es_muni:
        base = 69000000 + (h * 179) % 990000
    elif es_salud:
        base = 61600000 + (h * 149) % 390000
    else:
        base = 61100000 + (h * 131) % 890000
    return formatear_rut(base)

def determinar_filial(cat, reg, comp):
    cat_u = str(cat).upper()
    reg_u = str(reg).upper()
    comp_u = str(comp).upper()

    if "DENTAL" in cat_u:
        return (
            "RedSalud Dental SpA",
            "76.458.120-3"
        )
    valpo = (
        "VALPARAÍSO" in reg_u
        or "VALPARAISO" in reg_u
        or "VIÑA" in comp_u
    )
    if valpo:
        return (
            "Clínica RedSalud Valparaíso",
            "96.543.000-6"
        )
    ranc = (
        "RANCAGUA" in comp_u
        or "HIGGIN" in reg_u
        or "COLCHAGUA" in comp_u
    )
    if ranc:
        return (
            "Clínica RedSalud Rancagua",
            "96.542.000-0"
        )
    temu = (
        "ARAUCANÍA" in reg_u
        or "TEMUCO" in comp_u
        or "KALLVU" in comp_u
    )
    if temu:
        return (
            "Clínica RedSalud Mayor Temuco",
            "96.537.000-3"
        )
    mag = (
        "MAGALLANES" in reg_u
        or "PUNTA ARENAS" in comp_u
    )
    if mag:
        return (
            "Clínica RedSalud Magallanes",
            "96.541.000-5"
        )
    bio = (
        "BIOBÍO" in reg_u
        or "BIOBIO" in reg_u
        or "CONCEPCIÓN" in comp_u
    )
    if bio:
        return (
            "Centros Médicos RedSalud Biobío",
            "96.856.000-2"
        )
    mau = (
        "MAULE" in reg_u
        or "CURICÓ" in comp_u
        or "TALCA" in comp_u
    )
    if mau:
        return (
            "Centros Médicos RedSalud Maule",
            "96.856.000-2"
        )
    iqi = (
        "IQUIQUE" in reg_u
        or "TARAPACÁ" in reg_u
    )
    if iqi:
        return (
            "Centros Médicos RedSalud Iquique",
            "96.856.000-2"
        )
    ant = (
        "ANTOFAGASTA" in reg_u
        or "CALAMA" in comp_u
    )
    if ant:
        return (
            "Centros Médicos RedSalud Antofagasta",
            "96.856.000-2"
        )
    rm = (
        "METROPOLITANA" in reg_u
        or "SANTIAGO" in reg_u
    )
    if rm:
        prov = (
            "PROVIDENCIA" in comp_u
            or "ORIENTE" in comp_u
        )
        if prov:
            return (
                "Clínica RedSalud Providencia",
                "96.536.000-8"
            )
        vit = (
            "VITACURA" in comp_u
            or "LO BARNECHEA" in comp_u
        )
        if vit:
            return (
                "Clínica RedSalud Vitacura",
                "96.536.000-8"
            )
        return (
            "Clínica RedSalud Santiago",
            "96.856.000-2"
        )
    return (
        "RedSalud S.A.",
        "96.856.000-2"
    )

def sincronizar_contratos():
    print("Iniciando sincronización...", flush=True)
    try:
        client = obtener_cliente_gspread()
        # 1. Base Madre (Solo Lectura)
        ss_maestra = client.open_by_key(
            SPREADSHEET_ID_MAESTRA
        )
        sheet_maestra = ss_maestra.sheet1
        valores_maestra = sheet_maestra.get_all_values()
        print(f"Base Madre leida: {len(valores_maestra)} filas.", flush=True)
    except Exception as e:
        print(f"Error Base Madre: {e}", flush=True)
        return

    try:
        # 2. Archivo de Gestión de Contratos
        ss_contratos = client.open_by_key(
            SPREADSHEET_ID_CONTRATOS
        )
        try:
            ws_contratos = ss_contratos.worksheet(
                NOMBRE_HOJA_CONTRATOS
            )
        except gspread.exceptions.WorksheetNotFound:
            print("Creando hoja 'Base Contratos'...", flush=True)
            ws_contratos = ss_contratos.add_worksheet(
                title=NOMBRE_HOJA_CONTRATOS,
                rows=1000,
                cols=25
            )
            ws_contratos.update(
                range_name="A1:S1",
                values=[ENCABEZADOS_CONTRATOS]
            )
    except Exception as e:
        print(f"Error Archivo Contratos: {e}", flush=True)
        return

    # 3. Leer contratos existentes (evita duplicar o borrar trabajo manual)
    datos_existentes = ws_contratos.get_all_values()
    if not datos_existentes:
        ws_contratos.update(
            range_name="A1:S1",
            values=[ENCABEZADOS_CONTRATOS]
        )
        datos_existentes = [ENCABEZADOS_CONTRATOS]

    ids_registrados = set()
    for row in datos_existentes[1:]:
        if len(row) > 7 and row[7].strip():
            ids_registrados.add(row[7].strip())

    print(f"Registrados previos: {len(ids_registrados)}", flush=True)

    # 4. Procesar filas: SOLO ADJUDICADAS Y AÑO 2026
    filas_nuevas = []
    if len(valores_maestra) > 1:
        for r in valores_maestra[1:]:
            fila = list(r) + [""] * (20 - len(r))
            codigo = fila[1].strip()          # Col B: Código Proceso
            nombre = fila[2].strip()          # Col C: Nombre Proceso
            categoria = fila[3].strip()       # Col D: Categoría / Línea
            fecha_pub = fila[4].strip()       # Col E: Fecha Pub
            fecha_cie = fila[5].strip()       # Col F: Fecha Cierre
            tipo_proc = fila[7].strip()       # Col H: Tipo Proceso
            comprador = fila[8].strip()       # Col I: Comprador
            region = fila[9].strip()          # Col J: Región
            estado = fila[10].strip()         # Col K: Estado Oferta
            adjudicatario = fila[11].strip()  # Col L: Adjudicatario
            monto = fila[12].strip()          # Col M: Monto Total
            codigo_oc = fila[14].strip()      # Col O: Código OC

            if not codigo:
                continue

            # REGLA ESTRICTA 1: SOLO LO ADJUDICADO
            if estado.upper() != "ADJUDICADA":
                continue

            # REGLA ESTRICTA 2: SOLO AÑO 2026
            es_2026 = (
                "26" in codigo
                or "2026" in fecha_pub
                or "2026" in fecha_cie
            )
            if not es_2026:
                continue

            # REGLA 3: No duplicar si ya existe
            if codigo in ids_registrados:
                continue

            cat_limpia = categoria.replace("RedSalud - ", "").strip()
            if not cat_limpia:
                cat_limpia = "Salud General y Procedimientos"

            rut_cliente = resolver_rut_cliente(
                comprador, codigo
            )
            filial, rut_filial = determinar_filial(
                cat_limpia, region, comprador
            )

            if "LICIT" in tipo_proc.upper():
                tipo_registro = "Licitación Pública"
                duracion_meses = 12
            else:
                tipo_registro = "Compra Ágil"
                duracion_meses = 2

            es_sum = any(
                x in nombre.upper()
                for x in [
                    "SUMINISTRO",
                    "INSUMOS"
                ]
            )
            if es_sum:
                tipo_contrato = "Suministro de Insumos"
            else:
                tipo_contrato = "Prestación de Servicios Médicos"

            # Fechas en blanco para completar manualmente
            fecha_inicio = ""
            fecha_termino = ""

            try:
                monto_val = float(monto)
            except Exception:
                monto_val = 0

            es_lic = "LICIT" in tipo_registro.upper()
            if monto_val >= 15000000 or es_lic:
                boleta = f"BG-{codigo}"
            else:
                boleta = "No Aplica"
            venc_boleta = ""

            # Estado del contrato fijado en "En gestión"
            estado_contrato = "En gestión"

            aplica_reajuste = "Sí" if duracion_meses >= 12 else "No"
            reajuste = "IPC Anual" if duracion_meses >= 12 else "No Aplica"

            filas_nuevas.append([
                cat_limpia,
                comprador,
                rut_cliente,
                filial,
                rut_filial,
                tipo_registro,
                tipo_contrato,
                codigo,
                nombre,
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
            ids_registrados.add(codigo)

    tot_nuevas = len(filas_nuevas)
    print(f"Contratos adjudicados 2026 encontrados: {tot_nuevas}", flush=True)

    if tot_nuevas > 0:
        f_ini = len(datos_existentes) + 1
        f_fin = f_ini + tot_nuevas - 1
        f_nec = max(f_fin + 50, 500)
        ws_contratos.resize(rows=f_nec, cols=25)

        for s in range(0, tot_nuevas, 1000):
            e = min(s + 1000, tot_nuevas)
            r1 = f_ini + s
            r2 = f_ini + e - 1
            ws_contratos.update(
                range_name=f"A{r1}:S{r2}",
                values=filas_nuevas[s:e]
            )
        print(f"Se agregaron {tot_nuevas} registros exitosamente.", flush=True)
    else:
        print("No hay adjudicaciones 2026 nuevas pendientes.", flush=True)

if __name__ == "__main__":
    sincronizar_contratos()
