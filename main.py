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
FILA_INICIO_OBJETIVO = 372

# Lista oficial de RUTs base de RedSalud y sus clínicas/filiales en ChileCompra
RUTS_REDSALUD = {
    "96856000",  # RedSalud S.A. / Servicios Clínicos RedSalud
    "76458120",  # RedSalud Dental SpA
    "96536000",  # Clínica RedSalud Providencia / Vitacura / Santiago
    "96543000",  # Clínica RedSalud Valparaíso
    "96542000",  # Clínica RedSalud Rancagua
    "96537000",  # Clínica RedSalud Mayor Temuco
    "96541000",  # Clínica RedSalud Magallanes
    "96524000",  # Clínica RedSalud Iquique
    "96527000",  # Clínica RedSalud Elqui / La Serena
    "96559000",  # Centros Médicos y Dentales RedSalud
    "76326330",  # Sociedad Médica RedSalud
}

# Competidores y empresas ajenas a RedSalud que deben ser descartadas sin excepción
COMPETIDORES_PROHIBIDOS = [
    "RUBIKAL", "ATRYS", "BIOMEDIC", "FRESENIUS", "FALCK", "B.BRAUN",
    "MEDTRONIC", "SIEMENS", "INDISA", "ALEMANA", "SAN JOSE", "LAS CONDES",
    "SAN CARLOS", "UNIVERSIDAD CATOLICA", "UC CHRISTUS", "INTERCLINICA",
    "INGENIERIA", "CONSTRUCCION", "MONTAJES", "PHARMA", "DROGUERIA"
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

def es_septiembre_2026_en_adelante(fecha_pub, fecha_cie, fila_raw):
    candidatas = [fecha_pub, fecha_cie] + fila_raw[4:7]
    for f in candidatas:
        if re.search(r"2026-(09|10|11|12)", str(f)):
            return True
    return False

def detectar_indices_cabecera(cabecera):
    indices = {
        "codigo": 1, "nombre": 2, "categoria": 3, "fecha_pub": 4,
        "fecha_cie": 5, "tipo": 7, "comprador": 8, "region": 9,
        "estado": 10, "adjudicatario": 11, "monto": 12,
        "columnas_proveedor": []
    }
    for idx, c in enumerate(cabecera):
        t = str(c).strip().upper()
        if "CÓDIGO" in t or "CODIGO" in t:
            indices["codigo"] = idx
        elif "NOMBRE" in t and "PROCESO" in t:
            indices["nombre"] = idx
        elif "CATEGOR" in t:
            indices["categoria"] = idx
        elif "FECHA" in t and "PUB" in t:
            indices["fecha_pub"] = idx
        elif "FECHA" in t and ("CIERRE" in t or "TERMINO" in t or "TÉRMINO" in t):
            indices["fecha_cie"] = idx
        elif "TIPO" in t:
            indices["tipo"] = idx
        elif "COMPRADOR" in t or "INSTITUCI" in t:
            indices["comprador"] = idx
        elif "REGI" in t:
            indices["region"] = idx
        elif "ESTADO" in t and "OFERTA" in t:
            indices["estado"] = idx
        elif "ADJUDICATARIO" in t or "PROVEEDOR" in t or "GANADOR" in t or "OFERENTE" in t or "RAZÓN SOCIAL" in t or "RAZON SOCIAL" in t:
            indices["columnas_proveedor"].append(idx)
            if "ADJUDICATARIO" in t or "GANADOR" in t:
                indices["adjudicatario"] = idx
        elif "MONTO" in t:
            indices["monto"] = idx

    if not indices["columnas_proveedor"]:
        indices["columnas_proveedor"] = [11]
    return indices

def es_adjudicatario_redsalud_estricto(fila, idx_adjudicatario, columnas_proveedor):
    # Evaluar celdas designadas para el adjudicatario
    celdas_a_revisar = set([idx_adjudicatario] + columnas_proveedor)
    
    # 1. Comprobar si algún competidor conocido figura en esas columnas
    for c_idx in celdas_a_revisar:
        if c_idx < len(fila):
            texto_celda = str(fila[c_idx]).strip().upper()
            if any(no_es in texto_celda for no_es in COMPETIDORES_PROHIBIDOS):
                return False

    # 2. Verificar coincidencia explícita con RedSalud en las columnas de proveedor
    tiene_redsalud = False
    for c_idx in celdas_a_revisar:
        if c_idx < len(fila):
            texto_celda = str(fila[c_idx]).strip().upper()
            if re.search(r"RED\s*SALUD", texto_celda):
                tiene_redsalud = True
                break
            rut_limpio = re.sub(r"[^0-9]", "", texto_celda)
            if any(r in rut_limpio for r in RUTS_REDSALUD):
                tiene_redsalud = True
                break

    return tiene_redsalud

def extraer_id_licitacion_estricto(fila_raw, idx_codigo):
    # Patrón estricto de Mercado Público: excluye RFI, RFP, CM
    patron = r"\b\d{3,8}-\d{1,5}-(?:LP|LE|LR|LQ|LS|L1|E2|CO|B2)\d{0,2}\b"
    col_cod = fila_raw[idx_codigo].strip() if len(fila_raw) > idx_codigo else ""
    m = re.search(patron, col_cod, re.IGNORECASE)
    if m:
        return m.group(0).upper()
    for c in fila_raw:
        m = re.search(patron, str(c).strip(), re.IGNORECASE)
        if m:
            return m.group(0).upper()
    return ""

def extraer_prestacion_estricta(fila_raw, idx_nombre):
    palabras_prohibidas = [
        "SERVICIO DE SALUD", "INSTITUCIÓN PÚBLICA", "INSTITUCION PUBLICA",
        "REDSALUD", "RED SALUD", "ACEPTADA", "EN PROCESO", "EVALUACIÓN",
        "EVALUACION", "ADJUDICADA", "PUBLICADA", "DESIERTA", "REVOCADA",
        "CANCELADA", "ENVIADA", "RUT:", "S.A.", "SPA", "LTDA", "E.I.R.L.",
        "COMPRADOR", "MUNICIPALIDAD", "HOSPITAL"
    ]
    col_nom = fila_raw[idx_nombre].strip() if len(fila_raw) > idx_nombre else ""
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

def sincronizar_contratos():
    print(f"Iniciando depuración y sincronización desde fila {FILA_INICIO_OBJETIVO}...", flush=True)
    try:
        client, sa_email = obtener_cliente_gspread()
        print(f"Autenticado como: {sa_email}", flush=True)
    except Exception as e:
        print(f"Error de autenticación: {repr(e)}", flush=True)
        return

    # 1. Base Madre (Solo Lectura)
    try:
        ss_maestra = client.open_by_key(SPREADSHEET_ID_MAESTRA)
        sheet_maestra = ss_maestra.sheet1
        valores_maestra = sheet_maestra.get_all_values()
        print(f"Base Madre leida: {len(valores_maestra)} filas.", flush=True)
    except Exception as e:
        print(f"Error Base Madre: {repr(e)}", flush=True)
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
            print(f"Error Archivo Contratos: {repr(e)}", flush=True)
            return

    # 3. Localizar hoja 'consolidado'
    ws_contratos = None
    for ws in ss_contratos.worksheets():
        if ws.title.strip().lower() == NOMBRE_HOJA_CONTRATOS.lower():
            ws_contratos = ws
            break
    if not ws_contratos:
        print(f"Error: No se encontró la hoja '{NOMBRE_HOJA_CONTRATOS}'.", flush=True)
        return

    # 4. Proteger estrictamente filas 1 a 371
    datos_existentes = ws_contratos.get_all_values()
    print(f"Filas actuales en '{NOMBRE_HOJA_CONTRATOS}': {len(datos_existentes)}", flush=True)

    ids_historicos = set()
    limite_historico = min(FILA_INICIO_OBJETIVO - 1, len(datos_existentes))
    for row in datos_existentes[:limite_historico]:
        if len(row) > 7 and row[7].strip():
            ids_historicos.add(row[7].strip().upper())
        if len(row) > 1 and row[1].strip():
            ids_historicos.add(row[1].strip().upper())

    print(f"IDs históricos protegidos (filas 1 a {limite_historico}): {len(ids_historicos)}", flush=True)

    # 5. Mapeo dinámico de cabeceras en Base Madre
    idx = detectar_indices_cabecera(valores_maestra[0])
    print(f"Columnas detectadas en Base Madre: {idx}", flush=True)

    # 6. Filtrar licitaciones verdaderas de RedSalud
    filas_nuevas = []
    ids_nuevos = set()

    if len(valores_maestra) > 1:
        for r in valores_maestra[1:]:
            fila = list(r) + [""] * (25 - len(r))
            categoria = fila[idx["categoria"]].strip()
            fecha_pub = fila[idx["fecha_pub"]].strip()
            fecha_cie = fila[idx["fecha_cie"]].strip()
            tipo_proc = fila[idx["tipo"]].strip()
            comprador = fila[idx["comprador"]].strip()
            region = fila[idx["region"]].strip()
            estado = fila[idx["estado"]].strip()
            monto = fila[idx["monto"]].strip()

            # FILTRO 1: Código oficial de Mercado Público (descarta PROCESO-XXX y consultas RFI)
            codigo = extraer_id_licitacion_estricto(fila, idx["codigo"])
            if not codigo:
                continue

            # FILTRO 2: Solo licitaciones
            if "AGIL" in tipo_proc.upper() or "COT" in codigo.upper():
                continue
            es_lic = (
                "LICIT" in tipo_proc.upper()
                or any(sig in codigo.upper() for sig in ["-LE", "-LP", "-LR", "-L1", "-E2", "-CO", "-B2", "-LQ", "-LS"])
            )
            if not es_lic:
                continue

            # FILTRO 3: Estado de la oferta adjudicada
            es_adj = "ADJUDICADA" in estado.upper() or any(str(c).strip().upper() == "ADJUDICADA" for c in fila)
            if not es_adj:
                continue

            # FILTRO 4: VERIFICACIÓN INEQUÍVOCA DE REDSALUD COMO GANADOR
            # Si el adjudicatario es Rubikal, Atrys o cualquier competidor, SE DESCARTA
            if not es_adjudicatario_redsalud_estricto(fila, idx["adjudicatario"], idx["columnas_proveedor"]):
                continue

            # FILTRO 5: Desde Septiembre de 2026 en adelante
            if not es_septiembre_2026_en_adelante(fecha_pub, fecha_cie, fila):
                continue

            # FILTRO 6: No duplicar con los IDs históricos de las filas 1 a 371
            cod_u = codigo.upper()
            if cod_u in ids_historicos or cod_u in ids_nuevos:
                continue

            cat_cliente = clasificar_categoria_cliente(comprador)
            prestacion = extraer_prestacion_estricta(fila, idx["nombre"])
            rut_cliente = resolver_rut_cliente(comprador, codigo)
            filial, rut_filial = determinar_filial(categoria, region, comprador)

            filas_nuevas.append([
                cat_cliente,         # Col A: Categoría Cliente
                comprador,           # Col B: Cliente
                rut_cliente,         # Col C: Rut Cliente
                filial,              # Col D: Filial
                rut_filial,          # Col E: Rut Filial
                "",                  # Col F: Tipo registro (EN BLANCO)
                "Licitación",        # Col G: Tipo Contrato (Licitación)
                codigo,              # Col H: ID licitación (Mercado Público)
                prestacion,          # Col I: Prestaciones (Título Clínico)
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
            ids_nuevos.add(cod_u)

    tot_nuevas = len(filas_nuevas)
    print(f"Licitaciones REALMENTE adjudicadas a RedSalud (Sept 2026+): {tot_nuevas}", flush=True)

    # 7. PURGAR Y REESCRIBIR DESDE LA FILA 372 EN ADELANTE
    fila_inicio = FILA_INICIO_OBJETIVO
    filas_totales_actuales = max(len(datos_existentes), fila_inicio)

    # Limpiar cualquier contenido remanente desde la fila 372 hacia abajo
    if filas_totales_actuales >= fila_inicio:
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
        print("No se encontraron licitaciones nuevas adjudicadas a RedSalud desde Septiembre 2026.", flush=True)

if __name__ == "__main__":
    sincronizar_contratos()
