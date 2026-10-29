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
    Alinea estrictamente las columnas de los reportes ingresados al esquema base oficial:
    1. Traspasa 'Valor Ambulatorio Hábil' a 'Valor Neto' y elimina la primera.
    2. Traspasa 'Inicio Vigencia' a 'Vigencia Desde' y elimina 'Inicio Vigencia'.
    3. Asigna 'ARMADA' en la columna Cliente cuando el archivo corresponda a este organismo.
    4. Elimina la columna 'Contrato'.
    5. Restringe la salida estrictamente a los encabezados maestros, eliminando columnas huérfanas (AW a BH).
    """
    if not lista_dfs_con_nombre:
        return pd.DataFrame()

    # Identificar el archivo Maestro / Trazabilidad como la plantilla canónica oficial
    idx_maestro = 0
    for i, (df, nombre) in enumerate(lista_dfs_con_nombre):
        if "TRAZABILIDAD" in nombre.upper() or "MAESTRO" in nombre.upper():
            idx_maestro = i
            break

    df_base, nombre_base = lista_dfs_con_nombre[idx_maestro]
    print(f"Estructura maestra tomada de: {nombre_base} ({len(df_base.columns)} columnas)", flush=True)

    # 1. Base de columnas canónicas del archivo maestro original
    columnas_canonicas = list(df_base.columns)
    
    # Eliminar columna 'Contrato' si venía en el archivo maestro
    columnas_canonicas = [c for c in columnas_canonicas if normalizar_nombre_columna(c) not in ["CONTRATO", "NUMERO CONTRATO", "N CONTRATO"]]

    # Mapa de nombres normalizados del archivo maestro
    mapa_normalizado = {normalizar_nombre_columna(c): c for c in columnas_canonicas}

    # Ubicar los nombres exactos en el maestro para 'VIGENCIA DESDE', 'VALOR NETO' y 'CLIENTE'
    col_vigencia_desde = None
    col_valor_neto = None
    col_cliente = None

    for c in columnas_canonicas:
        cn = normalizar_nombre_columna(c)
        if "VIGENCIA DESDE" in cn or "DESDE" in cn or "FECHA INICIO" in cn:
            col_vigencia_desde = c
        elif "VALOR NETO" in cn or "NETO" in cn:
            col_valor_neto = c
        elif "CLIENTE" in cn or "INSTITUCION" in cn:
            col_cliente = c

    # Si no existieran explícitas, asegurar sus encabezados oficiales en el esquema
    if not col_vigencia_desde:
        col_vigencia_desde = "Vigencia Desde"
        columnas_canonicas.append(col_vigencia_desde)
        mapa_normalizado[normalizar_nombre_columna(col_vigencia_desde)] = col_vigencia_desde

    if not col_valor_neto:
        col_valor_neto = "Valor Neto"
        columnas_canonicas.append(col_valor_neto)
        mapa_normalizado[normalizar_nombre_columna(col_valor_neto)] = col_valor_neto

    if not col_cliente:
        col_cliente = "Cliente"
        columnas_canonicas.append(col_cliente)
        mapa_normalizado[normalizar_nombre_columna(col_cliente)] = col_cliente

    # Mapeo semántico obligatorio según instrucciones del usuario:
    # A) 'Inicio Vigencia' -> 'Vigencia Desde'
    mapa_normalizado["INICIO VIGENCIA"] = col_vigencia_desde
    mapa_normalizado["INICIO DE VIGENCIA"] = col_vigencia_desde
    mapa_normalizado["FECHA INICIO VIGENCIA"] = col_vigencia_desde

    # B) 'Valor Ambulatorio Hábil' -> 'Valor Neto'
    mapa_normalizado["VALOR AMBULATORIO HABIL"] = col_valor_neto
    mapa_normalizado["VALOR AMBULATORIO HABIL CLP"] = col_valor_neto
    mapa_normalizado["VALOR AMBULATORIO"] = col_valor_neto

    # C) Equivalencias estándar de codificación y glosa
    equivalencias_adicionales = {
        "CODIGO FONASA": ["CODIGO", "COD FONASA", "COD_FONASA", "CODIGO DE PRESTACION"],
        "GLOSA PRESTACION": ["GLOSA", "DESCRIPCION", "PRESTACION", "NOMBRE PRESTACION"],
        "CODIGO PRESTADOR": ["COD PRESTADOR", "COD_PRESTADOR", "CODIGO INTERNO"],
        "FILIAL": ["CLINICA", "SUCURSAL", "CENTRO MEDICO"]
    }
    for col_std, variantes in equivalencias_adicionales.items():
        norm_std = normalizar_nombre_columna(col_std)
        if norm_std in mapa_normalizado:
            real_col = mapa_normalizado[norm_std]
            for var in variantes:
                mapa_normalizado[normalizar_nombre_columna(var)] = real_col

    dfs_calibrados = []

    for df, nombre in lista_dfs_con_nombre:
        df_trabajo = df.copy()

        # Eliminar columna Contrato si viene en el archivo
        cols_a_eliminar = [c for c in df_trabajo.columns if normalizar_nombre_columna(c) in ["CONTRATO", "NUMERO CONTRATO", "N CONTRATO"]]
        if cols_a_eliminar:
            df_trabajo = df_trabajo.drop(columns=cols_a_eliminar)

        # Regla: Asignar 'ARMADA' en Cliente si el archivo corresponde a la Armada
        if "ARMADA" in nombre.upper():
            df_trabajo[col_cliente] = "ARMADA"

        # Mapear nombres de columnas
        renombramiento = {}
        for col in df_trabajo.columns:
            cn = normalizar_nombre_columna(col)
            if cn in mapa_normalizado:
                target_col = mapa_normalizado[cn]
                # Si la columna ya existe en el dataframe (ej. ya había valor neto), combinarla
                renombramiento[col] = target_col

        df_renombrado = df_trabajo.rename(columns=renombramiento)

        # Si tras renombrar existen columnas duplicadas (por ejemplo si traía Valor Neto y Valor Ambulatorio Hábil), consolidar
        if df_renombrado.columns.duplicated().any():
            df_renombrado = df_renombrado.groupby(lambda x: x, axis=1).first()

        df_renombrado["ORIGEN_ARCHIVO"] = nombre
        dfs_calibrados.append(df_renombrado)

    # Añadir 'ORIGEN_ARCHIVO' a las columnas maestras
    if "ORIGEN_ARCHIVO" not in columnas_canonicas:
        columnas_canonicas.append("ORIGEN_ARCHIVO")

    # Concatenar todos los dataframes
    df_consolidado = pd.concat(dfs_calibrados, ignore_index=True)

    # FILTRO ESTRICTO: NO permitir columnas fuera del esquema maestro (Elimina columnas AW a BH)
    columnas_finales = [c for c in columnas_canonicas if c in df_consolidado.columns]
    df_final = df_consolidado[columnas_finales].fillna("")

    print(f"Columnas finales calibradas: {len(df_final.columns)} columnas estrictamente maestras.", flush=True)
    return df_final

def sincronizar_aranceles():
    print("=== INICIANDO SINCRONIZADOR DE ARANCELES (CALIBRACIÓN OFICIAL) ===", flush=True)

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

    # Alinear y aplicar calibraciones estrictas
    df_final = alinear_dataframes(lista_dfs)
    print(f"Resultado calibrado: {len(df_final)} filas, {len(df_final.columns)} columnas.", flush=True)

    # Preparar valores para Google Sheets
    headers = df_final.columns.tolist()
    valores = [headers] + df_final.values.tolist()

    filas_necesarias = max(len(valores) + 50, 100)
    cols_necesarias = max(len(headers) + 2, 25)

    print(f"Redimensionando hoja '{HOJA_DESTINO}' a {filas_necesarias} filas y {cols_necesarias} columnas...", flush=True)
    ws_ingesta.resize(rows=filas_necesarias, cols=cols_necesarias)

    print(f"Limpiando contenido previo en '{HOJA_DESTINO}' para eliminar columnas AW:BH...", flush=True)
    ws_ingesta.clear()

    print(f"Escribiendo {len(valores)} filas limpias y calibradas en '{HOJA_DESTINO}'...", flush=True)
    tamano_lote = 5000
    for i in range(0, len(valores), tamano_lote):
        lote = valores[i:i + tamano_lote]
        fila_inicio = i + 1
        fila_fin = i + len(lote)
        col_fin_letra = gspread.utils.rowcol_to_a1(1, len(headers)).replace("1", "")
        rango = f"A{fila_inicio}:{col_fin_letra}{fila_fin}"
        ws_ingesta.update(range_name=rango, values=lote)
        print(f"  -> Lote escrito: filas {fila_inicio} a {fila_fin}", flush=True)

    print(f"=== ÉXITO: Ingesta de Aranceles calibrada correctamente ({len(valores) - 1} filas) ===", flush=True)

if __name__ == "__main__":
    sincronizar_aranceles()
