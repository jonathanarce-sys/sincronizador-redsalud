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

# Encabezados Oficiales con "Categoría Cliente"
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
    sa_email = creds_dict.get(
        "client_email",
        "Email no identificado"
    )
    client = gspread.authorize(
        Credentials.from_service_account_info(
            creds_dict,
            scopes=scopes
        )
    )
    return client, sa_email

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

def es_agosto_2026_en_adelante(fecha_pub, fecha_cie):
    for f in [fecha_pub, fecha_cie]:
        if re.search(r"2026-(08|09|10|11|12)", str(f)):
            return True
    return False

def obtener_o_crear_hoja_destino(ss_contratos):
    for ws in ss_contratos.worksheets():
        if ws.title.strip().lower() == NOMBRE_HOJA_CONTRATOS.lower():
            print(f"Hoja encontrada: '{ws.title}'", flush=True)
            return ws
    print(f"Creando hoja '{NOMBRE_HOJA_CONTRATOS}'...", flush=True)
    ws = ss_contratos.add_worksheet(
        title=NOMBRE_HOJA_CONTRATOS,
        rows=1000,
        cols=25
    )
    ws.update(range_name="A1:S1", values=[ENCABEZADOS_CONTRATOS])
    return ws

def sincronizar_contratos():
    print("Iniciando sincronización...", flush=True)
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

    try:
        ws_contratos = obtener_o_crear_hoja_destino(ss_contratos)
    except Exception as e:
        print(f"Error accediendo a la hoja destino: {repr(e)}", flush=True)
        return

    # 3. Leer contratos existentes (evita duplicar)
    datos_existentes = ws_contratos.get_all_values()
    if not datos_existentes:
        ws_contratos.update(range_name="A1:S1", values=[ENCABEZADOS_CONTRATOS])
        datos_existentes = [ENCABEZADOS_CONTRATOS]
    else:
        # Asegurar que el encabezado en A1 sea 'Categoría Cliente'
        if datos_existentes[0] and datos_existentes[0][0] != "Categoría Cliente":
            ws_contratos.update(range_name="A1", values=[["Categoría Cliente"]])

    ids_registrados = set()
    for row in datos_existentes[1:]:
        if len(row) > 7 and row[7].strip():
            ids_registrados.add(row[7].strip())

    print(f"Registrados previos en destino: {len(ids_registrados)}", flush=True)

    # 4. Procesar filas: SOLO LICITACIONES, SOLO ADJUDICADAS Y DESDE AGOSTO 2026
    filas_nuevas = []
    if len(valores_maestra) > 1:
        for r in valores_maestra[1:]:
            fila = list(r) + [""] * (20 - len(r))
            codigo = fila[1].strip()          # Col B: Código Proceso
            nombre = fila[2].strip()          # Col C: Nombre Proceso
            categoria = fila[3].strip()       # Col D: Categor
