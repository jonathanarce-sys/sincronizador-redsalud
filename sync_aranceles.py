import os
import glob
import base64
import json
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 1. CONFIGURACIÓN DEL MAESTRO DE ARANCELES
# ==========================================
SPREADSHEET_ID_ARANCELES = "1qxeY4CQN-g-bHqbfEpr2MjQXzObpNG5fSxThqexbXHo".strip()
HOJA_DESTINO = "RAW_Data_Ingesta"
CARPETA_RAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "raw")

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

def leer_archivo_raw(ruta_archivo):
    """Lee archivos .xlsx, .xls o .csv con detección de separadores y codificación."""
    ext = os.path.splitext(ruta_archivo)[1].lower()
    nombre_base = os.path.basename(ruta_archivo)
    print(f"-> Procesando archivo: {nombre_base}...", flush=True)

    if ext in [".xlsx", ".xls"]:
        try:
            df = pd.read_excel(ruta_archivo, dtype=str)
            df["ORIGEN_ARCHIVO"] = nombre_base
            return df
        except Exception as e:
            print(f"Error leyendo Excel {nombre_base}: {repr(e)}", flush=True)
            return None

    elif ext == ".csv":
        for enc in ["utf-8-sig", "utf-8", "latin1", "cp1252"]:
            for sep in [",", ";", "\t", "|"]:
                try:
                    df = pd.read_csv(ruta_archivo, sep=sep, encoding=enc, dtype=str)
                    if len(df.columns) > 1:
                        df["ORIGEN_ARCHIVO"] = nombre_base
                        return df
                except Exception:
                    continue
        print(f"No se pudo determinar el formato del CSV: {nombre_base}", flush=True)
        return None
    else:
        # En caso de archivos sin extensión reconocible, intentar como Excel y luego como CSV
        try:
            df = pd.read_excel(ruta_archivo, dtype=str)
            df["ORIGEN_ARCHIVO"] = nombre_base
            return df
        except Exception:
            try:
                df = pd.read_csv(ruta_archivo, sep=None, engine="python", encoding="latin1", dtype=str)
                df["ORIGEN_ARCHIVO"] = nombre_base
                return df
            except Exception as e:
                print(f"Archivo omitido o formato desconocido: {nombre_base} ({repr(e)})", flush=True)
                return None

def sincronizar_aranceles():
    print("=== INICIANDO SINCRONIZADOR DE ARANCELES (data/raw -> RAW_Data_Ingesta) ===", flush=True)
    
    # 1. Conexión Google Sheets
    try:
        client, sa_email = obtener_cliente_gspread()
        print(f"Autenticado en Google Sheets como: {sa_email}", flush=True)
    except Exception as e:
        print(f"Error de autenticación Google: {repr(e)}", flush=True)
        return

    try:
        ss_aranceles = client.open_by_key(SPREADSHEET_ID_ARANCELES)
        print(f"Planilla abierta: {ss_aranceles.title}", flush=True)
    except Exception as e:
        print(f"Error abriendo planilla Maestro Aranceles ({SPREADSHEET_ID_ARANCELES}): {repr(e)}", flush=True)
        return

    # Buscar o crear hoja RAW_Data_Ingesta
    ws_ingesta = None
    for ws in ss_aranceles.worksheets():
        if ws.title.strip().lower() == HOJA_DESTINO.lower():
            ws_ingesta = ws
            break
    if not ws_ingesta:
        print(f"Creando pestaña '{HOJA_DESTINO}'...", flush=True)
        ws_ingesta = ss_aranceles.add_worksheet(title=HOJA_DESTINO, rows=1000, cols=30)

    # 2. Explorar carpeta data/raw
    if not os.path.exists(CARPETA_RAW):
        print(f"Aviso: La carpeta '{CARPETA_RAW}' no existe localmente.", flush=True)
        return

    archivos = [
        os.path.join(CARPETA_RAW, f) for f in os.listdir(CARPETA_RAW)
        if not f.startswith(".") and f != ".gitkeep"
    ]
    
    if not archivos:
        print("Fase Aranceles: No se encontraron archivos para procesar en data/raw/.", flush=True)
        return

    print(f"Archivos encontrados en data/raw/: {len(archivos)}", flush=True)
    
    dfs = []
    for f in archivos:
        df = leer_archivo_raw(f)
        if df is not None and not df.empty:
            dfs.append(df)

    if not dfs:
        print("Sin datos legibles en los archivos de data/raw/.", flush=True)
        return

    # Consolidar todos los reportes
    df_consolidado = pd.concat(dfs, ignore_index=True)
    df_consolidado = df_consolidado.fillna("")
    print(f"Total registros consolidados para ingesta: {len(df_consolidado)} filas, {len(df_consolidado.columns)} columnas.", flush=True)

    # 3. Escritura por lotes en Google Sheets
    headers = df_consolidado.columns.tolist()
    valores = [headers] + df_consolidado.values.tolist()

    filas_necesarias = max(len(valores) + 50, 100)
    cols_necesarias = max(len(headers) + 5, 20)
    
    print(f"Redimensionando hoja '{HOJA_DESTINO}' a {filas_necesarias} filas y {cols_necesarias} columnas...", flush=True)
    ws_ingesta.resize(rows=filas_necesarias, cols=cols_necesarias)

    print(f"Limpiando contenido previo en '{HOJA_DESTINO}'...", flush=True)
    ws_ingesta.clear()

    print(f"Escribiendo {len(valores)} filas en '{HOJA_DESTINO}'...", flush=True)
    tamano_lote = 5000
    for i in range(0, len(valores), tamano_lote):
        lote = valores[i:i + tamano_lote]
        fila_inicio = i + 1
        fila_fin = i + len(lote)
        col_fin_letra = gspread.utils.rowcol_to_a1(1, len(headers)).replace("1", "")
        rango = f"A{fila_inicio}:{col_fin_letra}{fila_fin}"
        ws_ingesta.update(range_name=rango, values=lote)
        print(f"  -> Lote escrito: filas {fila_inicio} a {fila_fin}", flush=True)

    print(f"=== ÉXITO: Ingesta de Aranceles completada en '{HOJA_DESTINO}' ({len(valores) - 1} filas) ===", flush=True)

if __name__ == "__main__":
    sincronizar_aranceles()
