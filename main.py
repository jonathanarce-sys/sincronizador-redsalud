import os
import re
import json
import base64
import time
import requests
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 1. IDENTIFICADORES Y CONFIGURACIÓN GLOBAL
# ==========================================
# ID Planilla Base Maestra de Licitaciones:
SPREADSHEET_ID_MAESTRA = os.environ.get(
    "SPREADSHEET_ID_MAESTRA", 
    "1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek"
).strip()

# ID Planilla Consolidado Sector Público:
SPREADSHEET_ID_CONSOLIDADO = os.environ.get(
    "SPREADSHEET_ID_CONSOLIDADO", 
    "1kiOFcktRWHeXAOzCwLqPMzu1py0mGlANmvNogFCDbRE"
).strip()

HOJA_DESTINO_CONSOLIDADO = os.environ.get("HOJA_DESTINO_CONSOLIDADO", "Consolidado").strip()

# LÍMITE DE SEGURIDAD ESTRICTO:
# Las filas 1 a 433 son registros históricos validados y auditados.
# La escritura comenzará estrictamente desde la fila 434 en adelante.
FILA_INICIO_CONSOLIDADO = 434

LICITALAB_TOKEN = (
    os.environ.get("LICITALAB_TOKEN") or 
    os.environ.get("LICITALAB_API_KEY") or 
    os.environ.get("TOKEN_LICITALAB") or 
    ""
).strip()

TICKET_MERCADOPUBLICO = os.environ.get("MP_TICKET") or "F8537A18-6766-4DEF-9E59-426B4FEE5844"

# 20 RUTs oficiales de filiales y clínicas RedSalud
RUTS_REDSALUD = [
    "96.942.400-2", "99.533.790-8", "96.598.850-0", "76.542.910-2",
    "96.567.920-0", "78.040.520-0", "76.046.416-3", "96.774.580-4",
    "78.053.560-1", "76.906.480-K", "99.568.700-3", "76.181.326-9",
    "76.207.967-4", "78.918.290-6", "96.885.930-7", "88.611.600-4",
    "76.124.062-5", "99.568.720-8", "96.680.980-9", "76.110.809-3"
]

def obtener_cliente_gspread():
    """Autentica con la cuenta de servicio de Google Cloud."""
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

def consultar_licitalab_recientes(limit=500):
    """Consulta las oportunidades más recientes desde LicitaLAB BI API."""
    if not LICITALAB_TOKEN:
        print("Aviso: LICITALAB_TOKEN no configurado en entorno.")
        return []
    
    headers = {
        "x-api-key": LICITALAB_TOKEN,
        "Accept": "application/json",
        "User-Agent": "RedSalud-Sincronizador/1.0"
    }
    url = f"https://biapi.licitalab.cl/bi/v2/opportunities?limit={limit}"
    try:
        r = requests.get(url, headers=headers, timeout=25)
        if r.status_code == 200:
            d = r.json()
            items = d if isinstance(d, list) else (d.get("data") or d.get("opportunities") or [])
            print(f"LicitaLAB BI API: {len(items)} oportunidades recuperadas.")
            return items
    except Exception as e:
        print(f"Error consultando LicitaLAB BI API: {e}")
    return []

def extraer_adjudicadas_de_maestra(ss_maestra):
    """
    Lee las licitaciones en estado 'Adjudicada' de la Base Maestra existente.
    """
    filas_adjudicadas = []
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
        idx_est = -1
        for idx, col in enumerate(cabecera):
            if ("CÓDIGO" in col or "CODIGO" in col) and not any(x in col for x in ["OC", "CLIENTE"]):
                if idx_cod == -1: idx_cod = idx
            elif "ESTADO" in col and "OFERTA" in col:
                idx_est = idx

        for fila in datos[1:]:
            cod = fila[idx_cod].strip().upper() if idx_cod != -1 and idx_cod < len(fila) else ""
            if not cod:
                for celda in fila[:5]:
                    m = re.findall(r"\b\d{3,8}-\d{1,5}-[A-Za-z0-9]+\b", str(celda))
                    if m:
                        cod = m[0].upper()
                        break
            if not cod or cod in codigos_vistos:
                continue

            est = fila[idx_est].strip().upper() if idx_est != -1 and idx_est < len(fila) else ""
            # Considerar procesos adjudicados
            if "ADJUDICAD" in est or any("ADJUDICAD" in str(x).upper() for x in fila):
                codigos_vistos.add(cod)
                filas_adjudicadas.append(fila)

    print(f"Base Maestra: {len(filas_adjudicadas)} licitaciones adjudicadas identificadas.")
    return filas_adjudicadas

def actualizar_consolidado(ss_consolidado, filas_nuevas):
    """
    Actualiza la hoja Consolidado protegiendo las filas 1 a 433 y
    escribiendo los datos nuevos a partir de la fila 434.
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
        print("No hay filas nuevas para actualizar en el Consolidado.")
        return

    # Leer cabecera oficial del Consolidado para determinar ancho
    cabecera = ws_destino.row_values(1)
    num_cols = len(cabecera) if cabecera else len(filas_nuevas[0])
    col_fin = gspread.utils.rowcol_to_a1(1, num_cols).replace("1", "")

    # Normalizar longitud de columnas por fila
    filas_ajustadas = []
    for f in filas_nuevas:
        if len(f) < num_cols:
            f_ext = f + [""] * (num_cols - len(f))
        else:
            f_ext = f[:num_cols]
        filas_ajustadas.append(f_ext)

    # Asegurar dimensión de la planilla
    total_filas = FILA_INICIO_CONSOLIDADO + len(filas_ajustadas) + 50
    if ws_destino.row_count < total_filas:
        print(f"Ampliando Consolidado a {total_filas} filas...")
        ws_destino.resize(rows=total_filas, cols=max(ws_destino.col_count, num_cols))

    # Limpiar rango desde 434 (Filas 1 a 433 totalmente blindadas)
    max_filas_actual = max(ws_destino.row_count, total_filas)
    rango_limpieza = f"A{FILA_INICIO_CONSOLIDADO}:{col_fin}{max_filas_actual}"
    print(f"Protegiendo filas 1 a {FILA_INICIO_CONSOLIDADO - 1}. Limpiando rango de actualización: {rango_limpieza}")
    try:
        ws_destino.batch_clear([rango_limpieza])
    except Exception:
        pass

    # Escritura por lotes desde la fila 434
    fila_fin = FILA_INICIO_CONSOLIDADO + len(filas_ajustadas) - 1
    rango_total = f"A{FILA_INICIO_CONSOLIDADO}:{col_fin}{fila_fin}"
    print(f"Escribiendo {len(filas_ajustadas)} registros adjudicados en {rango_total}...")

    tamano_lote = 500
    for offset in range(0, len(filas_ajustadas), tamano_lote):
        lote = filas_ajustadas[offset:offset + tamano_lote]
        f_ini = FILA_INICIO_CONSOLIDADO + offset
        f_fin_lote = f_ini + len(lote) - 1
        rango_lote = f"A{f_ini}:{col_fin}{f_fin_lote}"
        ws_destino.update(range_name=rango_lote, values=lote)
        print(f"  -> Lote guardado: filas {f_ini} a {f_fin_lote}")

    print(f"=== Éxito: Consolidado actualizado desde la fila {FILA_INICIO_CONSOLIDADO} ({len(filas_ajustadas)} registros) ===")

def main():
    print("=== INICIANDO SINCRONIZADOR PRINCIPAL REDSALUD (MAIN.PY) ===")
    try:
        client, sa_email = obtener_cliente_gspread()
        print(f"Autenticado en Google Sheets como: {sa_email}")
    except Exception as e:
        print(f"Error crítico de autenticación: {e}")
        return

    # 1. Conexión a Base Maestra
    try:
        ss_maestra = client.open_by_key(SPREADSHEET_ID_MAESTRA)
        print(f"Base Maestra conectada: '{ss_maestra.title}'")
        adjudicadas_maestra = extraer_adjudicadas_de_maestra(ss_maestra)
    except Exception as e:
        print(f"Error accediendo a Base Maestra: {e}")
        adjudicadas_maestra = []

    # 2. Conexión a Consolidado Sector Público
    try:
        ss_consolidado = client.open_by_key(SPREADSHEET_ID_CONSOLIDADO)
        print(f"Consolidado Sector Público conectado: '{ss_consolidado.title}'")
        actualizar_consolidado(ss_consolidado, adjudicadas_maestra)
    except Exception as e:
        print(f"Error actualizando Consolidado: {e}")

    print("=== SINCRONIZACIÓN FINALIZADA CON ÉXITO ===")

if __name__ == "__main__":
    main()
