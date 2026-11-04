import os
import re
import json
import base64
import time
import requests
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 1. IDENTIFICADORES Y CONFIGURACIÓN
# ==========================================
SPREADSHEET_ID_MAESTRA = os.environ.get(
    "SPREADSHEET_ID_MAESTRA", 
    "1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek"
).strip()

SPREADSHEET_ID_CONSOLIDADO = os.environ.get(
    "SPREADSHEET_ID_CONSOLIDADO", 
    "1kiOFcktRWHeXAOzCwLqPMzu1py0mGlANmvNogFCDbRE"
).strip()

HOJA_DESTINO_CONSOLIDADO = os.environ.get("HOJA_DESTINO_CONSOLIDADO", "Consolidado").strip()

# El único cambio solicitado: Nuevos registros parten estrictamente desde la fila 434
FILA_INICIO_CONSOLIDADO = 434

LICITALAB_TOKEN = (
    os.environ.get("LICITALAB_TOKEN") or 
    os.environ.get("LICITALAB_API_KEY") or 
    os.environ.get("TOKEN_LICITALAB") or 
    ""
).strip()

# 20 RUTs oficiales de las filiales y clínicas de RedSalud
RUTS_REDSALUD_DICT = {
    "96.942.400-2": "RS Santiago",
    "99.533.790-8": "RS Providencia",
    "96.598.850-0": "Megasalud",
    "76.542.910-2": "RS Magallanes",
    "96.567.920-0": "RS Valparaíso",
    "78.040.520-0": "RS Valparaíso",
    "76.046.416-3": "Megasalud",
    "96.774.580-4": "RS Vitacura",
    "78.053.560-1": "RS Vitacura",
    "76.906.480-K": "RS Vitacura",
    "99.568.700-3": "RS Santiago",
    "76.181.326-9": "Instituto del Cáncer",
    "76.207.967-4": "RS Rancagua",
    "78.918.290-6": "RS Rancagua",
    "96.885.930-7": "RS Iquique",
    "88.611.600-4": "RS Temuco",
    "76.124.062-5": "RS Temuco",
    "99.568.720-8": "RS Santiago",
    "96.680.980-9": "RS Santiago",
    "76.110.809-3": "RS Santiago"
}

# Set de RUTs normalizados (sin puntos ni guiones) para búsqueda rápida
RUTS_NORMALIZADOS = {re.sub(r"[^\dkK]", "", r).upper() for r in RUTS_REDSALUD_DICT.keys()}

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
            if any(x in ek.upper() for x in ["GCP", "GOOGLE_CRED", "SERVICE_ACCOUNT"]) and ev.strip():
                val = ev.strip()
                break
    if not val:
        raise ValueError("Sin credenciales GCP en el entorno.")
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

def deducir_categoria_cliente(nombre_org):
    nom = str(nombre_org or "").upper()
    if any(x in nom for x in ["HOSPITAL", "CLINICO", "CLÍNICO", "CRS"]):
        return "Hospital"
    elif any(x in nom for x in ["SERVICIO DE SALUD", "SS"]):
        return "Servicio de Salud"
    elif any(x in nom for x in ["MUNICIPAL", "CORP", "DISAM", "DESAMU"]):
        return "Municipalidad"
    elif any(x in nom for x in ["ARMADA", "EJERCITO", "FUERZA AEREA", "DIPRECA", "CAPREDENA"]):
        return "Fuerzas Armadas"
    return "Institución Pública"

def es_licitacion_no_compra_agil(codigo, tipo_proceso):
    """Excluye compras ágiles (COT, COTI, CO) y valida que sea licitación pública o privada."""
    cod = str(codigo or "").strip().upper()
    tip = str(tipo_proceso or "").strip().upper()
    if any(x in tip for x in ["ÁGIL", "AGIL", "COTIZACI"]):
        return False
    partes = cod.split("-")
    if len(partes) >= 3:
        sufijo = partes[2]
        if "COT" in sufijo or "CO" in sufijo:
            return False
        if any(x in sufijo for x in ["LP", "LR", "LE", "LQ", "L1", "LS", "E2", "B2"]):
            return True
    return "LICITA" in tip

def es_adjudicado_a_redsalud(fila):
    """
    Verifica que la licitación haya sido adjudicada a RedSalud o alguna de sus clínicas/filiales.
    Descarta a terceros adjudicados.
    """
    texto_fila = " ".join(str(c) for c in fila).upper()
    
    # 1. Si dice 'PROVEEDOR TERCERO ADJUDICADO', descartar inmediatamente
    if "TERCERO ADJUDICADO" in texto_fila or "PROVEEDOR TERCERO" in texto_fila:
        return False, "", ""

    # 2. Buscar por RUT en las celdas
    for celda in fila:
        c_clean = re.sub(r"[^\dkK]", "", str(celda)).upper()
        if c_clean in RUTS_NORMALIZADOS:
            for rut_fmt, fil in RUTS_REDSALUD_DICT.items():
                if re.sub(r"[^\dkK]", "", rut_fmt).upper() == c_clean:
                    return True, fil, rut_fmt

    # 3. Buscar por palabras clave de RedSalud
    if any(k in texto_fila for k in ["REDSALUD", "RED SALUD", "MEGASALUD", "INSTITUTO DEL CANCER", "INSTITUTO DEL CÁNCER"]):
        filial_asig = "RS Santiago"
        rut_asig = "96.942.400-2"
        for rut_fmt, fil in RUTS_REDSALUD_DICT.items():
            if fil.upper() in texto_fila:
                filial_asig = fil
                rut_asig = rut_fmt
                break
        return True, filial_asig, rut_asig

    return False, "", ""

def extraer_licitaciones_adjudicadas_redsalud(ss_maestra):
    """
    Extrae únicamente las Licitaciones Adjudicadas A REDSALUD desde la Base Maestra.
    """
    filas_consolidadas = []
    codigos_vistos = set()

    for ws in ss_maestra.worksheets():
        if ws.title.strip().lower() in ["reporte_consumo_oc", "raw_data_ingesta"]:
            continue
        try:
            datos = ws.get_all_values()
        except Exception:
            continue
        if not datos or len(datos) < 2:
            continue

        cabecera = [str(c).strip().upper() for c in datos[0]]
        
        idx_cod = -1
        idx_nom = -1
        idx_org = -1
        idx_est = -1
        idx_tipo = -1
        idx_linea = -1
        idx_rut_cli = -1

        for idx, col in enumerate(cabecera):
            if ("CÓDIGO" in col or "CODIGO" in col) and not any(x in col for x in ["OC", "CLIENTE", "PRESTADOR"]):
                if idx_cod == -1: idx_cod = idx
            elif "NOMBRE" in col and "PROCESO" in col:
                idx_nom = idx
            elif any(x in col for x in ["ORGANISMO", "COMPRADOR", "INSTITUCIÓN", "INSTITUCION"]):
                idx_org = idx
            elif "ESTADO" in col and "OFERTA" in col:
                idx_est = idx
            elif "TIPO" in col and "PROCESO" in col:
                idx_tipo = idx
            elif any(x in col for x in ["CATEGORÍA", "CATEGORIA", "LÍNEA", "LINEA", "PRESTACION"]):
                idx_linea = idx
            elif "RUT" in col and "CLIENTE" in col:
                idx_rut_cli = idx

        for fila in datos[1:]:
            cod = fila[idx_cod].strip().upper() if idx_cod != -1 and idx_cod < len(fila) else ""
            if not cod:
                for celda in fila[:4]:
                    m = re.findall(r"\b\d{3,8}-\d{1,5}-[A-Za-z0-9]+\b", str(celda))
                    if m:
                        cod = m[0].upper()
                        break
            if not cod or cod in codigos_vistos:
                continue

            est = fila[idx_est].strip().upper() if idx_est != -1 and idx_est < len(fila) else ""
            tipo = fila[idx_tipo].strip().upper() if idx_tipo != -1 and idx_tipo < len(fila) else ""

            # FILTRO 1: Debe ser Adjudicada
            if not ("ADJUDICAD" in est or any("ADJUDICAD" in str(x).upper() for x in fila)):
                continue

            # FILTRO 2: No debe ser Compra Ágil
            if not es_licitacion_no_compra_agil(cod, tipo):
                continue

            # FILTRO 3: SOLO ADJUDICADAS A REDSALUD O SUS CLÍNICAS (Descarta terceros)
            es_rs, filial_rs, rut_filial_rs = es_adjudicado_a_redsalud(fila)
            if not es_rs:
                continue

            codigos_vistos.add(cod)

            org = fila[idx_org].strip() if idx_org != -1 and idx_org < len(fila) else ""
            if not org or "INSTITUCIÓN" in org.upper():
                org = "Servicio de Salud / Hospital Público"

            cat_cliente = deducir_categoria_cliente(org)
            rut_cli = fila[idx_rut_cli].strip() if idx_rut_cli != -1 and idx_rut_cli < len(fila) else ""

            prestaciones = fila[idx_linea].strip() if idx_linea != -1 and idx_linea < len(fila) else ""
            if not prestaciones:
                prestaciones = fila[idx_nom].strip() if idx_nom != -1 and idx_nom < len(fila) else "Prestaciones Médicas"
            prestaciones = prestaciones.replace("['", "").replace("']", "").replace('["', "").replace('"]', "")

            fila_consolidada = [
                cat_cliente,          # Col A: Categoria Cliente
                org,                  # Col B: Cliente
                rut_cli,              # Col C: Rut Cliente
                filial_rs,            # Col D: Filial RedSalud
                rut_filial_rs,        # Col E: Rut Filial
                "Contrato Base",      # Col F: Tipo registro
                "Licitación",         # Col G: Tipo Contrato
                cod,                  # Col H: ID licitación
                prestaciones          # Col I: Prestaciones
            ]

            filas_consolidadas.append(fila_consolidada)

    print(f"Base Maestra: {len(filas_consolidadas)} Licitaciones adjudicadas exclusivamente a RedSalud / Clínicas.", flush=True)
    return filas_consolidadas

def actualizar_consolidado(ss_consolidado, filas_nuevas):
    """
    Escribe los nuevos casos estrictamente desde la fila 434 en adelante,
    protegiendo intactas las filas 1 a 433.
    """
    ws_destino = None
    for ws in ss_consolidado.worksheets():
        if ws.title.strip().lower() == HOJA_DESTINO_CONSOLIDADO.lower():
            ws_destino = ws
            break
    if not ws_destino:
        ws_destino = ss_consolidado.sheet1
        print(f"Usando hoja '{ws_destino.title}' para Consolidado.", flush=True)

    if not filas_nuevas:
        print("Aviso: No se encontraron nuevas licitaciones adjudicadas a RedSalud para agregar.", flush=True)
        return

    num_cols = 9
    col_fin = "I"

    # Asegurar dimensión de la hoja
    total_filas = FILA_INICIO_CONSOLIDADO + len(filas_nuevas) + 50
    if ws_destino.row_count < total_filas:
        print(f"Ampliando Consolidado a {total_filas} filas...", flush=True)
        ws_destino.resize(rows=total_filas, cols=max(ws_destino.col_count, num_cols))

    # Limpiar únicamente desde la fila 434 hacia abajo (FILAS 1 A 433 PROTEGIDAS)
    max_filas_actual = max(ws_destino.row_count, total_filas)
    rango_limpieza = f"A{FILA_INICIO_CONSOLIDADO}:{col_fin}{max_filas_actual}"
    print(f"Limpiando rango desde fila {FILA_INICIO_CONSOLIDADO} (rango {rango_limpieza}). Filas 1 a 433 intactas...", flush=True)
    try:
        ws_destino.batch_clear([rango_limpieza])
    except Exception:
        pass

    # Escribir por lotes a partir de la fila 434
    fila_fin = FILA_INICIO_CONSOLIDADO + len(filas_nuevas) - 1
    rango_total = f"A{FILA_INICIO_CONSOLIDADO}:{col_fin}{fila_fin}"
    print(f"Escribiendo {len(filas_nuevas)} Licitaciones de RedSalud en {rango_total}...", flush=True)

    tamano_lote = 300
    for offset in range(0, len(filas_nuevas), tamano_lote):
        lote = filas_nuevas[offset:offset + tamano_lote]
        f_ini = FILA_INICIO_CONSOLIDADO + offset
        f_fin_lote = f_ini + len(lote) - 1
        rango_lote = f"A{f_ini}:{col_fin}{f_fin_lote}"
        ws_destino.update(range_name=rango_lote, values=lote)
        print(f"  -> Lote escrito: filas {f_ini} a {f_fin_lote}", flush=True)

    print(f"\n=== Sincronización exitosa: Consolidado actualizado desde la fila {FILA_INICIO_CONSOLIDADO} con {len(filas_nuevas)} licitaciones de RedSalud ===", flush=True)

def main():
    print("=== SINCRONIZADOR PRINCIPAL REDSALUD (MAIN.PY - FILTRO EXCLUSIVO REDSALUD) ===", flush=True)
    try:
        client, sa_email = obtener_cliente_gspread()
        print(f"Autenticado en Google Sheets como: {sa_email}", flush=True)
    except Exception as e:
        print(f"Error crítico de autenticación: {e}", flush=True)
        return

    # 1. Base Maestra
    try:
        ss_maestra = client.open_by_key(SPREADSHEET_ID_MAESTRA)
        print(f"Base Maestra conectada: '{ss_maestra.title}'", flush=True)
        licitaciones_rs = extraer_licitaciones_adjudicadas_redsalud(ss_maestra)
    except Exception as e:
        print(f"Error accediendo a Base Maestra: {e}", flush=True)
        licitaciones_rs = []

    # 2. Consolidado Sector Público
    try:
        ss_consolidado = client.open_by_key(SPREADSHEET_ID_CONSOLIDADO)
        print(f"Consolidado Sector Público conectado: '{ss_consolidado.title}'", flush=True)
        actualizar_consolidado(ss_consolidado, licitaciones_rs)
    except Exception as e:
        print(f"Error actualizando Consolidado: {e}", flush=True)

    print("=== SINCRONIZACIÓN FINALIZADA CON ÉXITO ===", flush=True)

if __name__ == "__main__":
    main()
