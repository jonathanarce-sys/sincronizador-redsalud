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

VALORES_AMBITO_VALIDOS = ["URGENCIA", "AMBULATORIO", "HOSPITALARIO", "TRANSVERSAL", "INDIFERENCIADO"]

def normalizar_nombre_columna(col):
    """Elimina tildes, mayúsculas/minúsculas y espacios duplicados para emparejar encabezados."""
    c = str(col).strip()
    c_norm = unicodedata.normalize('NFKD', c)
    c_clean = "".join([ch for ch in c_norm if not unicodedata.combining(ch)])
    c_clean = c_clean.upper()
    c_clean = re.sub(r'[\s_]+', ' ', c_clean).strip()
    return c_clean

def normalizar_valor_ambito(val_raw, glosa=""):
    """Normaliza el valor del ámbito para que coincida exactamente con la lista desplegable."""
    v = str(val_raw).strip().upper()
    g = str(glosa).strip().upper()
    
    for opt in VALORES_AMBITO_VALIDOS:
        if opt in v:
            return opt
            
    # Si viene vacío o no coincide, deducir por contexto de glosa o arancel
    if any(k in g for k in ["URGENCIA", "URG"]):
        return "URGENCIA"
    elif any(k in g for k in ["HOSPITAL", "CAMA", "DIA CAMA", "PABELLON", "INTERNACION"]):
        return "HOSPITALARIO"
    elif any(k in g for k in ["CONSULTA", "AMBULATORIO", "EXAMEN", "LABORATORIO", "IMAGEN"]):
        return "AMBULATORIO"
    elif v:
        return "INDIFERENCIADO"
    return "AMBULATORIO"

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
    Alinea estrictamente las columnas al esquema maestro:
    1. Asigna 'ARMADA' con precisión quirúrgica en la columna 'cliente' (NO en id_convenio_cliente).
    2. Elimina completamente las columnas 'contrato' y 'feedback_client'.
    3. Normaliza y rellena la columna 'ámbito' según la lista desplegable permitida.
    4. Traspasa 'Valor Ambulatorio Hábil' a 'Valor Neto' y 'Inicio Vigencia' a 'Vigencia Desde'.
    5. Restringe las columnas al esquema oficial sin desbordamientos hacia la derecha.
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

    columnas_canonicas = list(df_base.columns)
    
    # Columnas prohibidas que deben ser eliminadas del esquema
    prohibidas = [
        "CONTRATO", "NUMERO CONTRATO", "N CONTRATO",
        "FEEDBACK CLIENT", "FEEDBACK CLIENTE", "FEEDBACK"
    ]
    columnas_canonicas = [c for c in columnas_canonicas if normalizar_nombre_columna(c) not in prohibidas]

    mapa_normalizado = {normalizar_nombre_columna(c): c for c in columnas_canonicas}

    # Identificar las columnas clave exactas
    col_cliente_exacta = None
    col_ambito_exacta = None
    col_vigencia_desde = None
    col_valor_neto = None

    for c in columnas_canonicas:
        cn = normalizar_nombre_columna(c)
        # Búsqueda exacta de 'CLIENTE' evitando 'ID CONVENIO CLIENTE'
        if cn == "CLIENTE" or cn == "NOMBRE CLIENTE":
            col_cliente_exacta = c
        elif cn in ["AMBITO", "AMBITO ATENCION"]:
            col_ambito_exacta = c
        elif "VIGENCIA DESDE" in cn or cn == "DESDE":
            col_vigencia_desde = c
        elif cn in ["VALOR NETO", "NETO", "VALOR"]:
            col_valor_neto = c

    # Garantizar columnas obligatorias en la cabecera
    if not col_cliente_exacta:
        col_cliente_exacta = "cliente"
        columnas_canonicas.append(col_cliente_exacta)
        mapa_normalizado["CLIENTE"] = col_cliente_exacta

    if not col_ambito_exacta:
        col_ambito_exacta = "ámbito"
        columnas_canonicas.append(col_ambito_exacta)
        mapa_normalizado["AMBITO"] = col_ambito_exacta

    if not col_vigencia_desde:
        col_vigencia_desde = "Vigencia Desde"
        columnas_canonicas.append(col_vigencia_desde)
        mapa_normalizado["VIGENCIA DESDE"] = col_vigencia_desde

    if not col_valor_neto:
        col_valor_neto = "Valor Neto"
        columnas_canonicas.append(col_valor_neto)
        mapa_normalizado["VALOR NETO"] = col_valor_neto

    # Mapeo semántico directo
    mapa_normalizado["INICIO VIGENCIA"] = col_vigencia_desde
    mapa_normalizado["INICIO DE VIGENCIA"] = col_vigencia_desde
    mapa_normalizado["VALOR AMBULATORIO HABIL"] = col_valor_neto
    mapa_normalizado["VALOR AMBULATORIO HABIL CLP"] = col_valor_neto

    dfs_calibrados = []

    for df, nombre in lista_dfs_con_nombre:
        df_trabajo = df.copy()

        # Eliminar columnas no deseadas (Contrato y Feedback_client)
        cols_drop = [c for c in df_trabajo.columns if normalizar_nombre_columna(c) in prohibidas]
        if cols_drop:
            df_trabajo = df_trabajo.drop(columns=cols_drop)

        # Mapear nombres de columnas
        renombramiento = {}
        for col in df_trabajo.columns:
            cn = normalizar_nombre_columna(col)
            if cn in mapa_normalizado:
                renombramiento[col] = mapa_normalizado[cn]

        df_renombrado = df_trabajo.rename(columns=renombramiento)

        if df_renombrado.columns.duplicated().any():
            df_renombrado = df_renombrado.groupby(lambda x: x, axis=1).first()

        # REGLA 1: 'ARMADA' debe ir exclusivamente en la columna 'cliente'
        if "ARMADA" in nombre.upper():
            df_renombrado[col_cliente_exacta] = "ARMADA"
            # Si id_convenio_cliente contenía 'ARMADA' por error, limpiarlo o conservar ID numérico
            for col in df_renombrado.columns:
                if normalizar_nombre_columna(col) in ["ID CONVENIO CLIENTE", "ID CLIENTE"]:
                    df_renombrado[col] = df_renombrado[col].replace({"ARMADA": ""})

        # REGLA 2: Normalizar y poblar 'ámbito'
        glosa_col = None
        for col in df_renombrado.columns:
            if "GLOSA" in normalizar_nombre_columna(col):
                glosa_col = col
                break

        if col_ambito_exacta not in df_renombrado.columns:
            df_renombrado[col_ambito_exacta] = ""

        # Aplicar validación de ámbito para cada fila
        df_renombrado[col_ambito_exacta] = [
            normalizar_valor_ambito(val, glosa=row.get(glosa_col, "") if glosa_col else "")
            for val, row in zip(df_renombrado[col_ambito_exacta], df_renombrado.to_dict("records"))
        ]

        df_renombrado["ORIGEN_ARCHIVO"] = nombre
        dfs_calibrados.append(df_renombrado)

    if "ORIGEN_ARCHIVO" not in columnas_canonicas:
        columnas_canonicas.append("ORIGEN_ARCHIVO")

    df_consolidado = pd.concat(dfs_calibrados, ignore_index=True)

    # Restringir estrictamente a columnas del esquema oficial (evita desbordes AW a BH)
    columnas_finales = [c for c in columnas_canonicas if c in df_consolidado.columns]
    df_final = df_consolidado[columnas_finales].fillna("")

    print(f"Columnas finales calibradas: {len(df_final.columns)} columnas.", flush=True)
    return df_final

def sincronizar_aranceles():
    print("=== INICIANDO SINCRONIZADOR DE ARANCELES (CALIBRACIÓN V4) ===", flush=True)

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

    print(f"Limpiando contenido previo en '{HOJA_DESTINO}'...", flush=True)
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

    print(f"=== ÉXITO: Ingesta de Aranceles calibrada con éxito en '{HOJA_DESTINO}' ({len(valores) - 1} filas) ===", flush=True)

if __name__ == "__main__":
    sincronizar_aranceles()
