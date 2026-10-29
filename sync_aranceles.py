import os
import glob
import base64
import json
import unicodedata
import re
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 1. CONFIGURACIÓN DEL MAESTRO DE ARANCELES
# ==========================================
SPREADSHEET_ID_ARANCELES = "1qxeY4CQN-g-bHqbfEpr2MjQXzObpNG5fSxThqexbXHo".strip()
HOJA_DESTINO = "RAW_Data_Ingesta"
CARPETA_RAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "raw")

def normalizar_nombre_columna(col):
    """Elimina tildes, mayúsculas/minúsculas y espacios duplicados para emparejar encabezados."""
    c = str(col).strip()
    c_norm = unicodedata.normalize('NFKD', c)
    c_clean = "".join([ch for ch in c_norm if not unicodedata.combining(ch)])
    c_clean = c_clean.upper()
    c_clean = re.sub(r'[\s_]+', ' ', c_clean).strip()
    return c_clean

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
    print(f"-> Leyendo archivo: {nombre_base}...", flush=True)

    if ext in [".xlsx", ".xls"]:
        try:
            df = pd.read_excel(ruta_archivo, dtype=str)
            df = df.dropna(how="all")
            return df, nombre_base
        except Exception as e:
            print(f"Error leyendo Excel {nombre_base}: {repr(e)}", flush=True)
            return None, nombre_base

    elif ext == ".csv":
        for enc in ["utf-8-sig", "utf-8", "latin1", "cp1252"]:
            for sep in [",", ";", "\t", "|"]:
                try:
                    df = pd.read_csv(ruta_archivo, sep=sep, encoding=enc, dtype=str)
                    df = df.dropna(how="all")
                    if len(df.columns) > 1 and len(df) > 0:
                        return df, nombre_base
                except Exception:
                    continue
        print(f"No se pudo determinar el formato del CSV: {nombre_base}", flush=True)
        return None, nombre_base
    else:
        try:
            df = pd.read_excel(ruta_archivo, dtype=str)
            return df.dropna(how="all"), nombre_base
        except Exception:
            try:
                df = pd.read_csv(ruta_archivo, sep=None, engine="python", encoding="latin1", dtype=str)
                return df.dropna(how="all"), nombre_base
            except Exception as e:
                print(f"Formato no reconocido para {nombre_base}: {repr(e)}", flush=True)
                return None, nombre_base

def alinear_dataframes(lista_dfs_con_nombre):
    """
    Alinea las columnas de todos los archivos al esquema del archivo Maestro/Base.
    Si un archivo nuevo tiene variaciones de mayúsculas, tildes o espacios,
    las mapea exactamente a las columnas originales (de la A a la W).
    Solo las columnas verdaderamente inéditas se agregan al final.
    """
    if not lista_dfs_con_nombre:
        return pd.DataFrame()

    # Priorizar el archivo de Trazabilidad / Maestro como plantilla base
    idx_maestro = 0
    for i, (df, nombre) in enumerate(lista_dfs_con_nombre):
        if "TRAZABILIDAD" in nombre.upper() or "MAESTRO" in nombre.upper():
            idx_maestro = i
            break

    df_base, nombre_base = lista_dfs_con_nombre[idx_maestro]
    print(f"Archivo base para estructura de columnas: {nombre_base} ({len(df_base.columns)} columnas)", flush=True)

    # Columnas canónicas maestras
    columnas_canonicas = list(df_base.columns)
    mapa_normalizado = {normalizar_nombre_columna(c): c for c in columnas_canonicas}

    # Diccionario de equivalencias semánticas frecuentes por si difieren de nombre
    sinonimos = {
        "CODIGO": "CODIGO FONASA",
        "COD FONASA": "CODIGO FONASA",
        "CODIGO DE PRESTACION": "CODIGO FONASA",
        "GLOSA": "GLOSA PRESTACION",
        "DESCRIPCION": "GLOSA PRESTACION",
        "PRESTACION": "GLOSA PRESTACION",
        "VALOR": "ARANCEL",
        "PRECIO": "ARANCEL",
        "VALOR ARANCEL": "ARANCEL"
    }
    for sin, target in sinonimos.items():
        sin_norm = normalizar_nombre_columna(sin)
        target_norm = normalizar_nombre_columna(target)
        if target_norm in mapa_normalizado and sin_norm not in mapa_normalizado:
            mapa_normalizado[sin_norm] = mapa_normalizado[target_norm]

    dfs_alineados = []

    for df, nombre in lista_dfs_con_nombre:
        renombramiento = {}
        for col in df.columns:
            col_norm = normalizar_nombre_columna(col)
            if col_norm in mapa_normalizado:
                # Mapear a la columna existente oficial
                renombramiento[col] = mapa_normalizado[col_norm]
            else:
                # Columna nueva que no existía en el maestro
                print(f"  [+] Nueva columna agregada desde {nombre}: '{col}'", flush=True)
                columnas_canonicas.append(col)
                mapa_normalizado[col_norm] = col
                renombramiento[col] = col

        df_renombrado = df.rename(columns=renombramiento)
        df_renombrado["ORIGEN_ARCHIVO"] = nombre
        dfs_alineados.append(df_renombrado)

    # Concatenar todos con el orden de columnas canónicas
    if "ORIGEN_ARCHIVO" not in columnas_canonicas:
        columnas_canonicas.append("ORIGEN_ARCHIVO")

    df_final = pd.concat(dfs_alineados, ignore_index=True)
    # Reordenar columnas para que las originales queden primero (Cols A..W) y las extras al final
    cols_existentes_final = [c for c in columnas_canonicas if c in df_final.columns]
    resto_cols = [c for c in df_final.columns if c not in cols_existentes_final]
    cols_ordenadas = cols_existentes_final + resto_cols

    df_final = df_final[cols_ordenadas].fillna("")
    return df_final

def sincronizar_aranceles():
    print("=== INICIANDO SINCRONIZADOR DE ARANCELES (data/raw -> RAW_Data_Ingesta) ===", flush=True)

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

    lista_dfs = []
    for f in archivos:
        df, nombre = leer_archivo_raw(f)
        if df is not None and not df.empty:
            lista_dfs.append((df, nombre))

    if not lista_dfs:
        print("Sin datos legibles en los archivos de data/raw/.", flush=True)
        return

    # Alinear columnas inteligentemente
    df_consolidado = alinear_dataframes(lista_dfs)
    print(f"Resultado consolidado con columnas alineadas: {len(df_consolidado)} filas, {len(df_consolidado.columns)} columnas.", flush=True)

    # Escritura por lotes en Google Sheets
    headers = df_consolidado.columns.tolist()
    valores = [headers] + df_consolidado.values.tolist()

    filas_necesarias = max(len(valores) + 50, 100)
    cols_necesarias = max(len(headers) + 2, 25)

    print(f"Redimensionando hoja '{HOJA_DESTINO}' a {filas_necesarias} filas y {cols_necesarias} columnas...", flush=True)
    ws_ingesta.resize(rows=filas_necesarias, cols=cols_necesarias)

    print(f"Limpiando contenido previo desalineado en '{HOJA_DESTINO}'...", flush=True)
    ws_ingesta.clear()

    print(f"Escribiendo {len(valores)} filas ordenadas y alineadas en '{HOJA_DESTINO}'...", flush=True)
    tamano_lote = 5000
    for i in range(0, len(valores), tamano_lote):
        lote = valores[i:i + tamano_lote]
        fila_inicio = i + 1
        fila_fin = i + len(lote)
        col_fin_letra = gspread.utils.rowcol_to_a1(1, len(headers)).replace("1", "")
        rango = f"A{fila_inicio}:{col_fin_letra}{fila_fin}"
        ws_ingesta.update(range_name=rango, values=lote)
        print(f"  -> Lote escrito: filas {fila_inicio} a {fila_fin}", flush=True)

    print(f"=== ÉXITO: Ingesta de Aranceles completada con columnas perfectamente alineadas ({len(valores) - 1} filas) ===", flush=True)

if __name__ == "__main__":
    sincronizar_aranceles()
