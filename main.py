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

# Las filas 1 a 434 son el histórico original validado (fila 434: Hospital Dr. Luis Tisné Brousse).
# La escritura comenzará estrictamente desde la fila 435 en adelante.
FILA_INICIO_CONSOLIDADO = 435

LICITALAB_TOKEN = (
    os.environ.get("LICITALAB_TOKEN") or 
    os.environ.get("LICITALAB_API_KEY") or 
    os.environ.get("TOKEN_LICITALAB") or 
    ""
).strip()

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
    if "HOSPITAL" in nom or "CLINICO" in nom or "CLÍNICO" in nom or "CRS" in nom:
        return "Hospital"
    elif "SERVICIO DE SALUD" in nom or "SS" in nom:
        return "Servicio de Salud"
    elif "MUNICIPAL" in nom or "CORP" in nom or "DISAM" in nom or "DESAMU" in nom:
        return "Municipalidad"
    elif "ARMADA" in nom or "EJERCITO" in nom or "FUERZA AEREA" in nom or "DIPRECA" in nom or "CAPREDENA" in nom:
        return "Fuerzas Armadas"
    return "Institución Pública"

def es_licitacion_real(codigo, tipo_proceso):
    """
    Excluye estrictamente Compras Ágiles (COT, COTI, CO, etc.).
    Solo admite licitaciones públicas y privadas (LP, LR, LE, LQ, L1, LS, etc.).
    """
    cod = str(codigo or "").strip().upper()
    tip = str(tipo_proceso or "").strip().upper()

    # Si dice explícitamente compra ágil o cotización, rechazar
    if "ÁGIL" in tip or "AGIL" in tip or "COTIZACI" in tip or "COMPRA AGIL" in tip:
        return False

    # Analizar el sufijo del código de Mercado Público:
    # Ejemplo: 1057402-41-LE26 -> Sufijo: LE26 -> Tipo: LE
    partes = cod.split("-")
    if len(partes) >= 3:
        sufijo = partes[2]
        # Si el sufijo contiene COT o CO, es compra ágil
        if "COT" in sufijo or "CO" in sufijo:
            return False
        # Si tiene LP, LR, LE, LQ, L1, LS, E2, B2, etc. es licitación
        if any(x in sufijo for x in ["LP", "LR", "LE", "LQ", "L1", "LS", "E2", "B2"]):
            return True

    # Si el tipo proceso dice Licitación
    if "LICITA" in tip:
        return True

    return False

def extraer_licitaciones_adjudicadas_mapeadas(ss_maestra):
    """
    Lee la Base Maestra, filtra SOLAMENTE licitaciones adjudicadas (NO compras ágiles)
    y mapea al esquema de 9 columnas del Consolidado.
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
        idx_filial = -1
        idx_rut_filial = -1

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
            elif "FILIAL" in col and "RUT" not in col:
                idx_filial = idx
            elif "RUT" in col and "FILIAL" in col:
                idx_rut_filial = idx

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

            # FILTRO 1: DEBE SER ADJUDICADA
            es_adjudicada = "ADJUDICAD" in est or any("ADJUDICAD" in str(x).upper() for x in fila)
            if not es_adjudicada:
                continue

            # FILTRO 2: EXCLUIR COMPRAS ÁGILES (SOLO LICITACIONES)
            if not es_licitacion_real(cod, tipo):
                continue

            codigos_vistos.add(cod)

            # Mapeo a las columnas del Consolidado:
            # Col A: Categoria Cliente
            # Col B: Cliente
            # Col C: Rut Cliente
            # Col D: Filial
            # Col E: Rut Filial
            # Col F: Tipo registro
            # Col G: Tipo Contrato
            # Col H: ID licitación
            # Col I: Prestaciones

            org = fila[idx_org].strip() if idx_org != -1 and idx_org < len(fila) else ""
            if not org or "INSTITUCIÓN" in org.upper():
                org = "Servicio de Salud / Hospital Público"

            cat_cliente = deducir_categoria_cliente(org)
            rut_cli = fila[idx_rut_cli].strip() if idx_rut_cli != -1 and idx_rut_cli < len(fila) else ""

            # Filial y RUT filial
            rut_filial = fila[idx_rut_filial].strip() if idx_rut_filial != -1 and idx_rut_filial < len(fila) else ""
            filial = fila[idx_filial].strip() if idx_filial != -1 and idx_filial < len(fila) else ""
            if not filial and rut_filial in RUTS_REDSALUD_DICT:
                filial = RUTS_REDSALUD_DICT[rut_filial]
            elif not filial:
                filial = "RS Santiago"

            tipo_reg = "Contrato Base"
            tipo_cont = "Licitación"

            prestaciones = fila[idx_linea].strip() if idx_linea != -1 and idx_linea < len(fila) else ""
            if not prestaciones:
                prestaciones = fila[idx_nom].strip() if idx_nom != -1 and idx_nom < len(fila) else "Servicios Asistenciales Médicos"
            prestaciones = prestaciones.replace("['", "").replace("']", "").replace('["', "").replace('"]', "")

            fila_consolidada = [
                cat_cliente,      # Col A: Categoria Cliente
                org,              # Col B: Cliente
                rut_cli,          # Col C: Rut Cliente
                filial,           # Col D: Filial
                rut_filial,       # Col E: Rut Filial
                tipo_reg,         # Col F: Tipo registro
                tipo_cont,        # Col G: Tipo Contrato ("Licitación")
                cod,              # Col H: ID licitación
                prestaciones      # Col I: Prestaciones
            ]

            filas_consolidadas.append(fila_consolidada)

    print(f"Base Maestra: {len(filas_consolidadas)} Licitaciones Públicas Adjudicadas (Compras Ágiles excluidas).")
    return filas_consolidadas

def actualizar_consolidado(ss_consolidado, filas_nuevas):
    """
    Actualiza la hoja Consolidado a partir de la fila 435, preservando intactas
    las filas históricas 1 a 434 y alineando estrictamente las 9 columnas oficiales.
    """
    ws_destino = None
    for ws in ss_consolidado.worksheets():
        if ws.title.strip().lower() == HOJA_DESTINO_CONSOLIDADO.lower():
            ws_destino = ws
            break
    if not ws_destino:
        ws_destino = ss_consolidado.sheet1
        print(f"Usando hoja '{ws_destino.title}' para Consolidado.")

    if not filas_nuevas:
        print("Aviso: No se encontraron nuevas licitaciones adjudicadas para agregar.")
        return

    num_cols = 9
    col_fin = "I"

    # 1. Dimensionar la hoja
    total_filas = FILA_INICIO_CONSOLIDADO + len(filas_nuevas) + 50
    if ws_destino.row_count < total_filas:
        print(f"Ampliando Consolidado a {total_filas} filas...")
        ws_destino.resize(rows=total_filas, cols=max(ws_destino.col_count, num_cols))

    # 2. Limpiar registros antiguos desde 435 en adelante (PRESERVANDO FILAS 1 A 434)
    max_filas_actual = max(ws_destino.row_count, total_filas)
    rango_limpieza = f"A{FILA_INICIO_CONSOLIDADO}:{col_fin}{max_filas_actual}"
    print(f"Limpiando datos incorrectos en rango: {rango_limpieza} (Filas 1 a 434 totalmente protegidas)...")
    try:
        ws_destino.batch_clear([rango_limpieza])
    except Exception:
        pass

    # 3. Escritura por lotes a partir de la fila 435
    fila_fin = FILA_INICIO_CONSOLIDADO + len(filas_nuevas) - 1
    rango_total = f"A{FILA_INICIO_CONSOLIDADO}:{col_fin}{fila_fin}"
    print(f"Escribiendo {len(filas_nuevas)} Licitaciones Adjudicadas en {rango_total}...")

    tamano_lote = 300
    for offset in range(0, len(filas_nuevas), tamano_lote):
        lote = filas_nuevas[offset:offset + tamano_lote]
        f_ini = FILA_INICIO_CONSOLIDADO + offset
        f_fin_lote = f_ini + len(lote) - 1
        rango_lote = f"A{f_ini}:{col_fin}{f_fin_lote}"
        ws_destino.update(range_name=rango_lote, values=lote)
        print(f"  -> Lote guardado con éxito: filas {f_ini} a {f_fin_lote}")

    print(f"=== Éxito: Consolidado actualizado desde la fila {FILA_INICIO_CONSOLIDADO} con {len(filas_nuevas)} Licitaciones Adjudicadas ===")

def main():
    print("=== SINCRONIZADOR PRINCIPAL REDSALUD (MAIN.PY - SOLO LICITACIONES ADJUDICADAS) ===")
    try:
        client, sa_email = obtener_cliente_gspread()
        print(f"Autenticado en Google Sheets como: {sa_email}")
    except Exception as e:
        print(f"Error crítico de autenticación: {e}")
        return

    # 1. Base Maestra
    try:
        ss_maestra = client.open_by_key(SPREADSHEET_ID_MAESTRA)
        print(f"Base Maestra conectada: '{ss_maestra.title}'")
        licitaciones_adjudicadas = extraer_licitaciones_adjudicadas_mapeadas(ss_maestra)
    except Exception as e:
        print(f"Error accediendo a Base Maestra: {e}")
        licitaciones_adjudicadas = []

    # 2. Consolidado Sector Público
    try:
        ss_consolidado = client.open_by_key(SPREADSHEET_ID_CONSOLIDADO)
        print(f"Consolidado Sector Público conectado: '{ss_consolidado.title}'")
        actualizar_consolidado(ss_consolidado, licitaciones_adjudicadas)
    except Exception as e:
        print(f"Error actualizando Consolidado: {e}")

    print("=== SINCRONIZACIÓN FINALIZADA CON ÉXITO ===")

if __name__ == "__main__":
    main()
