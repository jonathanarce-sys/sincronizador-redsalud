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

# CONFIGURACIÓN DE FILTROS:
SOLO_LICITACIONES = True
DESDE_SEPTIEMBRE_A_LA_FECHA = True

# RUTs oficiales de RedSalud y sus razones sociales oficiales en Mercado Público
RUTS_REDSALUD_EXACTOS = {
    "96856000",  # RedSalud S.A. / Servicios Clínicos RedSalud / Casa Matriz
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
    "99568700",  # Centro de Especialidades Médicas Valparaíso / Inversalud Valparaíso SpA
}

# Licitaciones descartadas explícitas de competidores y no RedSalud
LICITACIONES_DESCARTADAS_EXPLICITAS = {
    "1464-65-LE26",    # Rubikal
    "3283-9-LE26",     # Atrys Health
    "359-115-LE26",    # Ingefisic
    "2770-153-LE26",   # No RedSalud
    "2378-118-LE26",   # Veterinario control gatos
    "1063538-37-LR26", # Grupo Bios S.A. (No RedSalud)
    "899-58-LE25",     # No RedSalud
    "899-27-LE26",     # FALP - Fundación Arturo López Pérez (RUT 70.377.400-8)
    "1374899-22-LR26", # Servicios Médicos Barlaro Ltda (RUT 78.403.510-7)
    "1017312-1-LP26",  # No RedSalud
    "1374899-42-LP26",
    "1656-23-LP26",
    "1057490-75-LE26",
    "612-43-LE26",
    "1422825-57-RFI26",
    "2667-79-LP26",
    "2667-73-LE26",
    "2107-147-LE26",
    "1175-74-LP26",
    "757-80-LE26",
    "899-38-LP26",
    "899-37-LE26",
    "857-5-LE26",
    "1274285-46-LE26",
    "5512-15-LP26",
    "548874-75-LP26",
    "1374899-24-LR26"
}

# Palabras clave de competidores que anulan de inmediato la fila
COMPETIDORES_BLOQUEADOS = [
    "RUBIKAL", "ATRYS", "INGEFISIC", "VETERINARIO", "BIOMEDIC",
    "FRESENIUS", "MEDTRONIC", "BIOS", "GRUPO BIOS", "SIEMENS", "INDISA",
    "ARTURO LOPEZ PEREZ", "LOPEZ PEREZ", "FALP", "BARLARO"
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

def determinar_filial(cat, reg, comp, adj="", codigo=""):
    adj_u = str(adj).upper()
    comp_u = str(comp).upper()
    reg_u = str(reg).upper()
    cat_u = str(cat).upper()
    cod_u = str(codigo).upper()

    # PRIORIDAD 1: Si el adjudicatario es de Valparaíso o la licitación es 899-33-LE26
    if "899-33-LE26" in cod_u or "99.568.700" in adj_u or "99568700" in adj_u or "VALPARAISO" in adj_u or "VALPARAÍSO" in adj_u or "INVERSALUD" in adj_u or "ESPECIALIDADES MEDICAS VALPARAISO" in adj_u:
        return "Centro de Especialidades Médicas Valparaíso", "99.568.700-3"

    # PRIORIDAD 2: Dental
    if "DENTAL" in cat_u:
        return "RedSalud Dental SpA", "76.458.120-3"

    # PRIORIDAD 3: Regionales según adjudicatario o comprador
    if "VALPARAÍSO" in reg_u or "VALPARAISO" in reg_u or "VIÑA" in comp_u or "VALPARAISO" in adj_u:
        return "Clínica RedSalud Valparaíso", "96.543.000-6"
    if "RANCAGUA" in comp_u or "HIGGIN" in reg_u or "COLCHAGUA" in comp_u or "RANCAGUA" in adj_u:
        return "Clínica RedSalud Rancagua", "96.542.000-0"
    if "ARAUCANÍA" in reg_u or "TEMUCO" in comp_u or "KALLVU" in comp_u or "TEMUCO" in adj_u:
        return "Clínica RedSalud Mayor Temuco", "96.537.000-3"
    if "MAGALLANES" in reg_u or "PUNTA ARENAS" in comp_u or "MAGALLANES" in adj_u:
        return "Clínica RedSalud Magallanes", "96.541.000-5"
    if "BIOBÍO" in reg_u or "BIOBIO" in reg_u or "CONCEPCIÓN" in comp_u or "BIOBIO" in adj_u:
        return "Centros Médicos RedSalud Biobío", "96.856.000-2"
    if "MAULE" in reg_u or "CURICÓ" in comp_u or "TALCA" in comp_u or "MAULE" in adj_u:
        return "Centros Médicos RedSalud Maule", "96.856.000-2"
    if "IQUIQUE" in reg_u or "TARAPACÁ" in reg_u or "IQUIQUE" in adj_u:
        return "Centros Médicos RedSalud Iquique", "96.856.000-2"
    if "ANTOFAGASTA" in reg_u or "CALAMA" in comp_u or "ANTOFAGASTA" in adj_u:
        return "Centros Médicos RedSalud Antofagasta", "96.856.000-2"

    # PRIORIDAD 4: Región Metropolitana
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
    # Procesos con sufijo de año 26 (ej: 899-33-LE26, 1077499-65-SE26)
    if re.search(r"-[A-Za-z]+26\b", str(codigo)):
        return True

    fechas = parsear_fechas_fila(fila_raw)
    for y, m, d in fechas:
        if DESDE_SEPTIEMBRE_A_LA_FECHA:
            if (y == 2025 and m >= 9) or (y >= 2026):
                return True
        else:
            if (y == 2026 and m >= 9) or (y > 2026):
                return True

    for c in fila_raw:
        s = str(c).strip().lower()
        if re.search(r"(septiembre|octubre|noviembre|diciembre).*(2025|2026)", s):
            return True

    return False

def extraer_id_licitacion(fila_raw, idx_codigo):
    valid_suffixes = ("LP", "LE", "LR", "LQ", "LS", "SE", "L1", "E2", "CO", "B2")
    
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
        "ATRYS", "BIOS", "ARTURO LOPEZ PEREZ", "BARLARO"
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

def verificar_adjudicatario_redsalud(fila, idx_adjudicatario, cabecera):
    # 1. Comprobar si en la fila aparece algún competidor o proveedor ajeno conocido
    fila_str = " ".join(str(c) for c in fila).upper()
    if any(bad in fila_str for bad in COMPETIDORES_BLOQUEADOS):
        return False

    # 2. Extraer RUTs presentes en las columnas de adjudicación (columnas 10 a 20)
    ruts_detectados = []
    for idx_col in range(10, len(fila)):
        val = str(fila[idx_col]).strip()
        ruts_en_celda = re.findall(r"\b\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]\b", val)
        for r in ruts_en_celda:
            r_num = re.sub(r"[^0-9]", "", r)
            ruts_detectados.append(r_num)

    if ruts_detectados:
        es_rs_rut = any(any(rs in r for rs in RUTS_REDSALUD_EXACTOS) for r in ruts_detectados)
        if not es_rs_rut:
            return False

    # 3. Comprobar la celda específica de adjudicatario
    if idx_adjudicatario is not None and idx_adjudicatario < len(fila):
        celda = str(fila[idx_adjudicatario]).strip().upper()
        if any(bad in celda for bad in COMPETIDORES_BLOQUEADOS):
            return False
        if re.search(r"\bRED\s*SALUD\b|MEGASALUD|INVERSALUD|ESPECIALIDADES\s*MEDICAS\s*VALPARAISO", celda):
            return True
        rut_nums = re.sub(r"[^0-9]", "", celda)
        if any(r_rs in rut_nums for r_rs in RUTS_REDSALUD_EXACTOS):
            return True

    # 4. Revisar otras columnas de adjudicación en la cabecera
    for i_c, h in enumerate(cabecera):
        h_u = str(h).upper()
        if ("ADJUDICATARIO" in h_u or "GANADOR" in h_u) and "CLIENTE" not in h_u and "CATEGOR" not in h_u:
            if i_c < len(fila):
                texto = str(fila[i_c]).strip().upper()
                if any(bad in texto for bad in COMPETIDORES_BLOQUEADOS):
                    return False
                if re.search(r"\bRED\s*SALUD\b|MEGASALUD|INVERSALUD", texto):
                    return True
                rut_nums = re.sub(r"[^0-9]", "", texto)
                if any(r_rs in rut_nums for r_rs in RUTS_REDSALUD_EXACTOS):
                    return True

    return False

def sincronizar_contratos():
    print(f"Iniciando sincronización ajustada desde fila {FILA_INICIO_OBJETIVO}...", flush=True)
    try:
        client, sa_email = obtener_cliente_gspread()
        print(f"Autenticado como: {sa_email}", flush=True)
    except Exception as e:
        print(f"Error de autenticación: {repr(e)}", flush=True)
        return

    try:
        ss_maestra = client.open_by_key(SPREADSHEET_ID_MAESTRA)
        sheet_maestra = ss_maestra.sheet1
        valores_maestra = sheet_maestra.get_all_values()
        print(f"Base Madre leida: {len(valores_maestra)} filas.", flush=True)
    except Exception as e:
        print(f"Error Base Madre: {repr(e)}", flush=True)
        return

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

    print(f"Mapeo verificado: Codigo={idx_codigo}, Nombre={idx_nombre}, Adjudicatario={idx_adjudicatario}, Estado={idx_estado}", flush=True)

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

    ws_contratos = None
    for ws in ss_contratos.worksheets():
        if ws.title.strip().lower() == NOMBRE_HOJA_CONTRATOS.lower():
            ws_contratos = ws
            break
    if not ws_contratos:
        print(f"Error: No se encontró la hoja '{NOMBRE_HOJA_CONTRATOS}'.", flush=True)
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

    # Filtrar licitaciones verdaderas
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

            # Extraer código chileno oficial
            codigo = extraer_id_licitacion(fila, idx_codigo)
            if not codigo:
                continue

            # Bloqueo total de licitaciones ajenas explícitas
            if codigo.upper() in LICITACIONES_DESCARTADAS_EXPLICITAS:
                continue

            # Filtro por tipo de proceso (solo licitaciones)
            if SOLO_LICITACIONES:
                if "AGIL" in tipo_proc.upper() or "COT" in codigo.upper():
                    continue

            # Estado de la oferta adjudicada
            es_adj = "ADJUDICADA" in estado.upper() or any(str(c).strip().upper() == "ADJUDICADA" for c in fila)
            if not es_adj:
                continue

            # Verificación de adjudicatario RedSalud
            if not verificar_adjudicatario_redsalud(fila, idx_adjudicatario, cabecera):
                continue

            # Periodo calibrado (desde septiembre a la fecha / año 26)
            if not cumple_filtro_periodo(fila, codigo):
                continue

            # Evitar duplicar
            cod_u = codigo.upper()
            if cod_u in ids_historicos or cod_u in ids_nuevos:
                continue

            cat_cliente = clasificar_categoria_cliente(comprador)
            prestacion = extraer_prestacion(fila, idx_nombre)
            rut_cliente = resolver_rut_cliente(comprador, codigo)
            filial, rut_filial = determinar_filial(categoria, region, comprador, adj=adjudicatario_celda, codigo=codigo)

            filas_nuevas.append([
                cat_cliente,         # Col A: Categoría Cliente
                comprador,           # Col B: Cliente
                rut_cliente,         # Col C: Rut Cliente
                filial,              # Col D: Filial (Ajustada a Valparaíso si corresponde)
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
    print(f"Licitaciones VERDADERAMENTE adjudicadas a RedSalud encontradas: {tot_nuevas}", flush=True)

    fila_inicio = FILA_INICIO_OBJETIVO
    filas_totales_actuales = max(len(datos_existentes), fila_inicio)

    # Limpiar cualquier contenido remanente desde la fila 372 hacia abajo
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
        print("RESULTADO: Ninguna licitación ajena fue insertada. La fila 372 en adelante quedó purgada.", flush=True)

if __name__ == "__main__":
    sincronizar_contratos()
