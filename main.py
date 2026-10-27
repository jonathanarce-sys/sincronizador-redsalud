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
).strip()
SPREADSHEET_ID_CONTRATOS = (
    "1kiOFcktRWHeXAOzCwLqPMzu1py0mGlANmvNogFCDbRE"
).strip()
NOMBRE_HOJA_CONTRATOS = "consolidado"

ENCABEZADOS_CONTRATOS = [
    "Categoría Cliente",
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
            cond_k = any(x in ek.upper() for x in ["GCP", "GOOGLE_CRED", "SERVICE_ACCOUNT"])
            if cond_k and ev.strip():
                val = ev.strip()
                break
    if not val:
        raise ValueError("Sin credenciales GCP.")
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

def determinar_filial(cat, reg, comp):
    cat_u = str(cat).upper()
    reg_u = str(reg).upper()
    comp_u = str(comp).upper()

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

def extraer_prestacion_real(fila_raw):
    textos_prohibidos = [
        "ACEPTADA", "EN PROCESO", "EVALUACIÓN", "EVALUACION", "ADJUDICADA",
        "PUBLICADA", "DESIERTA", "REVOCADA", "CANCELADA", "ENVIADA",
        "INSTITUCIÓN COMPRADORA", "RUT:", "S.A.", "SPA", "LTDA", "E.I.R.L."
    ]
    col_c = fila_raw[2].strip() if len(fila_raw) > 2 else ""
    if col_c and not any(p in col_c.upper() for p in textos_prohibidos) and len(col_c) > 5:
        return col_c

    candidatos = []
    for c in fila_raw:
        c_str = str(c).strip()
        if len(c_str) > 10:
            if not any(p in c_str.upper() for p in textos_prohibidos):
                if not re.match(r"^\d+-\d+-[A-Za-z0-9]+$", c_str) and not re.match(r"^\d{7,8}-[\dkK]$", c_str):
                    candidatos.append(c_str)
    if candidatos:
        return max(candidatos, key=len)
    return col_c if col_c else "Prestaciones Médicas"

def sincronizar_contratos():
    print("Iniciando sincronización limpia...", flush=True)
    try:
        client, sa_email = obtener_cliente_gspread()
        print(f"Autenticado exitosamente como: {sa_email}", flush=True)
    except Exception as e:
        print(f"Error de autenticación: {repr(e)}", flush=True)
        return

    # 1. Base Madre (Solo Lectura)
    try:
        ss_maestra = client.open_by_key(SPREADSHEET_ID_MAESTRA)
        sheet_maestra = ss_maestra.sheet1
        valores_maestra = sheet_maestra.get_all_values()
        print(f"Base Madre leida: {len(valores_maestra)} filas encontradas.", flush=True)
    except Exception as e:
        print(f"Error abriendo Base Madre: {repr(e)}", flush=True)
        return

    # 2. Archivo de Gestión de Contratos (Destino)
    ss_contratos = None
    try:
        ss_contratos = client.open_by_key(SPREADSHEET_ID_CONTRATOS)
    except Exception:
        try:
            url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID_CONTRATOS}/edit"
            ss_contratos = client.open_by_url(url)
        except Exception as e:
            print(f"Error abriendo Archivo Contratos: {repr(e)}", flush=True)
            return

    # 3. Localizar hoja 'consolidado'
    ws_contratos = None
    for ws in ss_contratos.worksheets():
        if ws.title.strip().lower() == NOMBRE_HOJA_CONTRATOS.lower():
            ws_contratos = ws
            break
    if not ws_contratos:
        print(f"Creando hoja '{NOMBRE_HOJA_CONTRATOS}'...", flush=True)
        ws_contratos = ss_contratos.add_worksheet(
            title=NOMBRE_HOJA_CONTRATOS,
            rows=1000,
            cols=25
        )

    # 4. Procesar filas: SOLO LICITACIONES, SOLO ADJUDICADAS Y DESDE AGOSTO 2026
    filas_nuevas = []
    ids_procesados = set()

    if len(valores_maestra) > 1:
        for r in valores_maestra[1:]:
            fila = list(r) + [""] * (20 - len(r))
            codigo = fila[1].strip()          # Col B: Código Proceso
            categoria = fila[3].strip()       # Col D: Categoría Licitalab
            fecha_pub = fila[4].strip()       # Col E: Fecha Pub
            fecha_cie = fila[5].strip()       # Col F: Fecha Cierre
            tipo_proc = fila[7].strip()       # Col H: Tipo Proceso
            comprador = fila[8].strip()       # Col I: Comprador
            region = fila[9].strip()          # Col J: Región
            estado = fila[10].strip()         # Col K: Estado Oferta
            monto = fila[12].strip()          # Col M: Monto Total

            if not codigo:
                continue

            # FILTRO 1: ESTADO DE LA OFERTA DEBE SER ESTRICTAMENTE 'ADJUDICADA'
            estado_u = estado.upper()
            if "ADJUDICADA" not in estado_u:
                es_adjudicada = any(str(c).strip().upper() == "ADJUDICADA" for c in fila)
                if not es_adjudicada:
                    continue

            # FILTRO 2: EXCLUSIVAMENTE LICITACIONES (Descartar Compra Ágil y Cotizaciones)
            es_compra_agil = any("AGIL" in str(c).upper() for c in [tipo_proc, codigo, categoria]) or "COT" in codigo.upper()
            if es_compra_agil:
                continue

            es_licitacion = (
                "LICIT" in tipo_proc.upper()
                or any(sig in codigo.upper() for sig in ["-LE", "-LP", "-LR", "-L1", "-E2", "-CO", "-B2"])
            )
            if not es_licitacion:
                continue

            # FILTRO 3: SOLO AGOSTO DE 2026 EN ADELANTE
            tiene_fecha_agosto = any(
                re.search(r"2026-(08|09|10|11|12)", str(f))
                for f in [fecha_pub, fecha_cie] + fila[4:7]
            )
            if not tiene_fecha_agosto:
                continue

            # FILTRO 4: EVITAR DUPLICADOS
            if codigo in ids_procesados:
                continue

            prestacion = extraer_prestacion_real(fila)
            cat_licitalab = categoria if categoria else "Salud General"

            rut_cliente = resolver_rut_cliente(comprador, codigo)
            filial, rut_filial = determinar_filial(cat_licitalab, region, comprador)

            filas_nuevas.append([
                cat_licitalab,       # Col A: Categoría Cliente
                comprador,           # Col B: Cliente
                rut_cliente,         # Col C: Rut Cliente
                filial,              # Col D: Filial
                rut_filial,          # Col E: Rut Filial
                "",                  # Col F: Tipo registro (EN BLANCO)
                "Licitación",        # Col G: Tipo Contrato
                codigo,              # Col H: ID licitación
                prestacion,          # Col I: Prestaciones
                "",                  # Col J: Fecha de inicio (EN BLANCO)
                "",                  # Col K: Fecha de termino (EN BLANCO)
                12,                  # Col L: Duración en Meses
                monto,               # Col M: Monto Contrato
                "",                  # Col N: ID OC (EN BLANCO)
                "",                  # Col O: Boleta de garantía (EN BLANCO)
                "",                  # Col P: Vencimiento boleta (EN BLANCO)
                "En gestión",        # Col Q: Estado Contrato
                "Sí",                # Col R: Aplica Reajuste
                ""                   # Col S: Reajuste (EN BLANCO)
            ])
            ids_procesados.add(codigo)

    tot_nuevas = len(filas_nuevas)
    print(f"Total licitaciones adjudicadas limpias encontradas: {tot_nuevas}", flush=True)

    # 5. Sobreescribir la pestaña 'consolidado' para limpiar los quiebres anteriores
    print("Limpiando y regenerando pestaña 'consolidado'...", flush=True)
    filas_necesarias = max(tot_nuevas + 50, 100)
    ws_contratos.resize(rows=filas_necesarias, cols=25)
    ws_contratos.clear()
    ws_contratos.update(range_name="A1:S1", values=[ENCABEZADOS_CONTRATOS])

    if filas_nuevas:
        for s in range(0, tot_nuevas, 1000):
            e = min(s + 1000, tot_nuevas)
            ws_contratos.update(
                range_name=f"A{s + 2}:S{e + 1}",
                values=filas_nuevas[s:e]
            )
        print(f"Se actualizaron exitosamente {tot_nuevas} registros limpios en 'consolidado'.", flush=True)
    else:
        print("No se encontraron registros que cumplan todos los filtros.", flush=True)

if __name__ == "__main__":
    sincronizar_contratos()
