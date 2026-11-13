import os
import re
import glob
import json
import base64
import math
import zipfile
import unicodedata
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

# 1. Configuración de destinos en Google Sheets
SPREADSHEET_ID_PRESTACIONES = "1qxeY4CQN-g-bHqbfEpr2MjQXzObpNG5fSxThqexbXHo"
HOJA_PRESTACIONES = "RAW_DATA_INGESTA"
HOJA_MAESTRO_HIS = "MAESTRO_HOMOLOGACION_HIS"

# Opcional: ID de un segundo Google Sheet para Materiales e Insumos (M&I)
SPREADSHEET_ID_INSUMOS = "" 
HOJA_INSUMOS = "RAW_DATA_MI"

CARPETA_RAW = "data/raw"
BATCH_SIZE = 3000

# Filtrar solo año vigente (True = descarta vigencias vencidas 2023-2025 de ISL para ahorrar celdas)
SOLO_VIGENCIA_2026 = True

# 2. Esquema estándar calibrado de 39 columnas (incluye código_fonasa, código_dipreca y código_prestador separados)
COLUMNAS_CALIBRADAS = [
    "filial",
    "sociedad",
    "cliente",
    "contrato",
    "id_licitación",
    "centro",
    "año",
    "tipo_arancel [origen]",
    "código_redsalud [no TC]",
    "código",
    "_cliente",
    "código_fonasa",
    "código_dipreca",
    "código_prestador",
    "glosa prestación",
    "tipo prestación",
    "Indexador",
    "precio_total",
    "ámbito",
    "recargo",
    "%_recargo",
    "vigencia desde",
    "vigencia_hasta",
    "id_convenio",
    "cliente Convenio_redsalud",
    "códig",
    "lugar_his",
    "Valor Ambulatorio Hábil 2026",
    "Tipo de arancel ambulatorio Hábil",
    "Valor Ambulatorio Inhábil 2026",
    "Tipo de arancel ambulatorio Inhábil",
    "Valor Hospitalizado Hábil 2026",
    "Tipo de arancel hospitalizado Hábil",
    "Valor Hospitalizado Inhábil 2026",
    "Tipo de arancel hospitalizado Inhábil",
    "Valor de Urgencia Hábil 2026",
    "Tipo de arancel urgencia Hábil",
    "Valor de Urgencia Inhábil 2026",
    "Tipo de arancel urgencia Inhábil"
]

HOJAS_DIPRECA = ["2026_Prestaciones", "2026_Paquetes", "2026_HMQ"]

def normalizar_texto(texto):
    s = str(texto).strip().lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s)

def obtener_cliente_gspread():
    posibles = ["GCP_SA_KEY", "GCP_JSON_BASE64", "GCP_SERVICE_ACCOUNT", "GOOGLE_CREDENTIALS", "GCP_JSON"]
    val = None
    for k in posibles:
        if k in os.environ and os.environ[k].strip():
            val = os.environ[k].strip()
            break
            
    if not val:
        raise ValueError("No se encontraron credenciales de Google Cloud en GitHub Secrets.")

    try:
        pad = len(val) % 4
        if pad:
            val += "=" * (4 - pad)
        creds_dict = json.loads(base64.b64decode(val).decode("utf-8"))
    except Exception:
        creds_dict = json.loads(val)

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    return gspread.authorize(Credentials.from_service_account_info(creds_dict, scopes=scopes))

def limpiar_celda(v):
    if v is None:
        return ""
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return ""
    if isinstance(v, (pd.Timestamp, pd.DatetimeIndex)):
        return v.strftime("%d-%m-%Y")
    txt = str(v).strip()
    if txt.lower() in ("nan", "nat", "none", "<na>", "inf", "-inf"):
        return ""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})\s+00:00:00", txt)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return txt

def extraer_filial_isl(nombre_archivo):
    base = os.path.splitext(nombre_archivo)[0]
    if " - " in base:
        return base.split(" - ")[-1].strip().upper()
    if "_" in base:
        return base.split("_")[-1].strip().upper()
    return ""

def mapear_a_esquema(df_raw, cliente_nombre, origen_etiqueta, nombre_archivo="", tipo_prestacion_fijo=""):
    df_out = pd.DataFrame("", index=range(len(df_raw)), columns=COLUMNAS_CALIBRADAS)
    
    df_out["cliente"] = cliente_nombre
    df_out["año"] = "2026"
    df_out["tipo_arancel [origen]"] = origen_etiqueta
    if tipo_prestacion_fijo:
        df_out["tipo prestación"] = tipo_prestacion_fijo

    if cliente_nombre == "ISL" and nombre_archivo:
        df_out["filial"] = extraer_filial_isl(nombre_archivo)

    dest_norm = {normalizar_texto(col): col for col in COLUMNAS_CALIBRADAS}
    cols_raw_norm = {normalizar_texto(c): c for c in df_raw.columns}

    # Reglas específicas para los archivos de ISL
    if cliente_nombre == "ISL":
        if "razon_social" in cols_raw_norm:
            df_out["sociedad"] = df_raw[cols_raw_norm["razon_social"]]
        if "codigo_prestacion" in cols_raw_norm:
            col_cod = cols_raw_norm["codigo_prestacion"]
            df_out["código"] = df_raw[col_cod]
            df_out["código_prestador"] = df_raw[col_cod]
            if "tipo_arancel" in cols_raw_norm:
                col_ta = cols_raw_norm["tipo_arancel"]
                mask_fonasa = df_raw[col_ta].astype(str).str.upper().str.contains("FONASA")
                df_out.loc[mask_fonasa, "código_fonasa"] = df_raw.loc[mask_fonasa, col_cod]
        if "glosa" in cols_raw_norm:
            df_out["glosa prestación"] = df_raw[cols_raw_norm["glosa"]]
        if "tipo_arancel" in cols_raw_norm:
            col_ta = cols_raw_norm["tipo_arancel"]
            df_out["tipo prestación"] = df_raw[col_ta]
            df_out["Tipo de arancel ambulatorio Hábil"] = df_raw[col_ta]
            df_out["Tipo de arancel hospitalizado Hábil"] = df_raw[col_ta]
        if "valor_nuevo" in cols_raw_norm:
            df_out["precio_total"] = df_raw[cols_raw_norm["valor_nuevo"]]
            df_out["Valor Ambulatorio Hábil 2026"] = df_raw[cols_raw_norm["valor_nuevo"]]
        if "valor_hospitalizado" in cols_raw_norm:
            df_out["Valor Hospitalizado Hábil 2026"] = df_raw[cols_raw_norm["valor_hospitalizado"]]
            if df_out["precio_total"].replace("", pd.NA).isna().all():
                df_out["precio_total"] = df_raw[cols_raw_norm["valor_hospitalizado"]]
        if "tipo_recargo" in cols_raw_norm and "recargo" in cols_raw_norm:
            col_tr = cols_raw_norm["tipo_recargo"]
            col_rec = cols_raw_norm["recargo"]
            mask_pct = df_raw[col_tr].astype(str).str.strip() == "%"
            df_out.loc[mask_pct, "%_recargo"] = df_raw.loc[mask_pct, col_rec]
            df_out.loc[~mask_pct, "recargo"] = df_raw.loc[~mask_pct, col_rec]
        if "desde" in cols_raw_norm:
            df_out["vigencia desde"] = df_raw[cols_raw_norm["desde"]]
        if "hasta" in cols_raw_norm:
            col_hasta = cols_raw_norm["hasta"]
            df_out["vigencia_hasta"] = df_raw[col_hasta]
            years = df_raw[col_hasta].astype(str).str.extract(r"^(\d{4})")[0].fillna("")
            df_out["año"] = years.replace("", "2026")
        if "id_convenio" in cols_raw_norm:
            df_out["id_convenio"] = df_raw[cols_raw_norm["id_convenio"]].astype(str).str.replace(r"\.0$", "", regex=True)
        return df_out

    # Reglas generales para DIPRECA, ARMADA y Maestro RedSalud
    for col_orig_real in df_raw.columns:
        c_norm = normalizar_texto(col_orig_real)

        # 1. Separación explícita en 3 encabezados independientes: código_fonasa, código_dipreca y código_prestador
        if "fonasa" in c_norm and any(k in c_norm for k in ["cod", "código"]):
            df_out["código_fonasa"] = df_raw[col_orig_real]
            continue
        elif "dipreca" in c_norm and any(k in c_norm for k in ["cod", "código"]):
            df_out["código_dipreca"] = df_raw[col_orig_real]
            if df_out["código"].replace("", pd.NA).isna().all():
                df_out["código"] = df_raw[col_orig_real]
            continue
        elif "prestador" in c_norm and any(k in c_norm for k in ["cod", "código"]):
            df_out["código_prestador"] = df_raw[col_orig_real]
            if df_out["código"].replace("", pd.NA).isna().all():
                df_out["código"] = df_raw[col_orig_real]
            continue

        # 2. Coincidencia exacta tras normalizar
        if c_norm in dest_norm:
            df_out[dest_norm[c_norm]] = df_raw[col_orig_real]
            continue

        # 3. Coincidencia flexible para los 12 campos de Valor / Tipo de arancel por ámbito y horario
        if "ambulatorio" in c_norm and "inhabil" in c_norm:
            if "tipo" in c_norm:
                df_out["Tipo de arancel ambulatorio Inhábil"] = df_raw[col_orig_real]
            else:
                df_out["Valor Ambulatorio Inhábil 2026"] = df_raw[col_orig_real]
            continue
        elif "ambulatorio" in c_norm and "habil" in c_norm:
            if "tipo" in c_norm:
                df_out["Tipo de arancel ambulatorio Hábil"] = df_raw[col_orig_real]
            else:
                df_out["Valor Ambulatorio Hábil 2026"] = df_raw[col_orig_real]
            continue
        elif "hospitalizado" in c_norm and "inhabil" in c_norm:
            if "tipo" in c_norm:
                df_out["Tipo de arancel hospitalizado Inhábil"] = df_raw[col_orig_real]
            else:
                df_out["Valor Hospitalizado Inhábil 2026"] = df_raw[col_orig_real]
            continue
        elif "hospitalizado" in c_norm and "habil" in c_norm:
            if "tipo" in c_norm:
                df_out["Tipo de arancel hospitalizado Hábil"] = df_raw[col_orig_real]
            else:
                df_out["Valor Hospitalizado Hábil 2026"] = df_raw[col_orig_real]
            continue
        elif "urgencia" in c_norm and "inhabil" in c_norm:
            if "tipo" in c_norm:
                df_out["Tipo de arancel urgencia Inhábil"] = df_raw[col_orig_real]
            else:
                df_out["Valor de Urgencia Inhábil 2026"] = df_raw[col_orig_real]
            continue
        elif "urgencia" in c_norm and "habil" in c_norm:
            if "tipo" in c_norm:
                df_out["Tipo de arancel urgencia Hábil"] = df_raw[col_orig_real]
            else:
                df_out["Valor de Urgencia Hábil 2026"] = df_raw[col_orig_real]
            continue

        # 4. Coincidencia para los campos base
        if any(k in c_norm for k in ["filial", "sede"]):
            df_out["filial"] = df_raw[col_orig_real]
        elif "sociedad" in c_norm or "razon" in c_norm:
            df_out["sociedad"] = df_raw[col_orig_real]
        elif "contrato" in c_norm:
            df_out["contrato"] = df_raw[col_orig_real]
        elif "licitacion" in c_norm:
            df_out["id_licitación"] = df_raw[col_orig_real]
        elif "centro" in c_norm or "unidad_negocio" in c_norm:
            df_out["centro"] = df_raw[col_orig_real]
        elif "fonasa" in c_norm:
            df_out["código_fonasa"] = df_raw[col_orig_real]
        elif "redsalud" in c_norm and ("cod" in c_norm or "no tc" in c_norm or "item" in c_norm):
            df_out["código_redsalud [no TC]"] = df_raw[col_orig_real]
        elif "convenio" in c_norm and "id" in c_norm:
            df_out["id_convenio"] = df_raw[col_orig_real]
        elif "convenio" in c_norm and "redsalud" in c_norm:
            df_out["cliente Convenio_redsalud"] = df_raw[col_orig_real]
        elif "lugar" in c_norm or "his" in c_norm:
            df_out["lugar_his"] = df_raw[col_orig_real]
        elif "indexador" in c_norm:
            df_out["Indexador"] = df_raw[col_orig_real]
        elif ("tipo" in c_norm and ("prestacion" in c_norm or "arancel" in c_norm)) and not tipo_prestacion_fijo:
            df_out["tipo prestación"] = df_raw[col_orig_real]
        elif any(k in c_norm for k in ["codigo", "cod_"]):
            if "cliente" in c_norm:
                df_out["_cliente"] = df_raw[col_orig_real]
            elif df_out["código"].replace("", pd.NA).isna().all():
                df_out["código"] = df_raw[col_orig_real]
        elif any(k in c_norm for k in ["glosa", "prestacion", "descripcion"]):
            if df_out["glosa prestación"].replace("", pd.NA).isna().all():
                df_out["glosa prestación"] = df_raw[col_orig_real]
        elif any(k in c_norm for k in ["precio", "total", "arancel", "valor", "tarifa"]):
            if df_out["precio_total"].replace("", pd.NA).isna().all():
                df_out["precio_total"] = df_raw[col_orig_real]
        elif "ambito" in c_norm:
            df_out["ámbito"] = df_raw[col_orig_real]
        elif "%" in c_norm and "recargo" in c_norm:
            df_out["%_recargo"] = df_raw[col_orig_real]
        elif "recargo" in c_norm:
            df_out["recargo"] = df_raw[col_orig_real]
        elif "desde" in c_norm or "inicio" in c_norm:
            df_out["vigencia desde"] = df_raw[col_orig_real]
        elif "hasta" in c_norm or "fin" in c_norm or "termino" in c_norm:
            df_out["vigencia_hasta"] = df_raw[col_orig_real]

    df_out["tipo_arancel [origen]"] = origen_etiqueta
    if df_out["cliente"].replace("", pd.NA).isna().all():
        df_out["cliente"] = cliente_nombre
    if df_out["año"].replace("", pd.NA).isna().all():
        df_out["año"] = "2026"

    return df_out

def escribir_en_sheet(client, spreadsheet_id, nombre_hoja, df_datos, columnas_header=None):
    if df_datos.empty:
        print(f"Sin datos para escribir en '{nombre_hoja}'.")
        return

    ss = client.open_by_key(spreadsheet_id)
    celdas_otras = sum(w.row_count * w.col_count for w in ss.worksheets() if w.title.strip().lower() != nombre_hoja.strip().lower())
    print(f"Celdas ocupadas por otras pestañas en el libro: {celdas_otras:,}")

    ws = None
    objetivo = nombre_hoja.strip().lower()
    for w in ss.worksheets():
        if w.title.strip().lower() == objetivo:
            ws = w
            break
            
    cols = columnas_header if columnas_header else list(df_datos.columns)
    num_cols = len(cols)
    if not ws:
        ws = ss.add_worksheet(title=nombre_hoja, rows=10, cols=num_cols)

    df_datos = df_datos.fillna("")
    filas_sanitizadas = [[limpiar_celda(c) for c in fila] for fila in df_datos.values.tolist()]
    matriz_final = [cols] + filas_sanitizadas

    total_filas = len(matriz_final)
    col_fin = gspread.utils.rowcol_to_a1(1, num_cols).replace("1", "")

    print(f"Limpiando '{nombre_hoja}' y ajustando dimensiones ({total_filas} filas x {num_cols} cols)...")
    ws.clear()
    ws.resize(rows=2, cols=1)
    ws.resize(rows=total_filas + 5, cols=num_cols)

    for i in range(0, total_filas, BATCH_SIZE):
        bloque = matriz_final[i:i + BATCH_SIZE]
        f_inicio = 1 + i
        f_termino = f_inicio + len(bloque) - 1
        rango_bloque = f"A{f_inicio}:{col_fin}{f_termino}"
        print(f"  [{nombre_hoja}] Escribiendo bloque {rango_bloque}...")
        ws.update(range_name=rango_bloque, values=bloque)

def leer_archivo_generico(ruta):
    nombre_lower = ruta.lower()
    if nombre_lower.endswith(".csv"):
        try:
            return pd.read_csv(ruta, sep=None, engine="python", encoding="utf-8", dtype=object)
        except Exception:
            return pd.read_csv(ruta, sep=None, engine="python", encoding="latin1", dtype=object)
    elif nombre_lower.endswith(".parquet"):
        return pd.read_parquet(ruta)
    else:
        return pd.read_excel(ruta, dtype=object)

def sincronizar_aranceles():
    print("Iniciando consolidación calibrada de aranceles (39 columnas)...")
    client = obtener_cliente_gspread()

    for z in glob.glob(os.path.join(CARPETA_RAW, "*.zip")):
        print(f"Descomprimiendo: {os.path.basename(z)}")
        with zipfile.ZipFile(z, "r") as zip_ref:
            zip_ref.extractall(CARPETA_RAW)
        os.remove(z)

    patron = os.path.join(CARPETA_RAW, "*")
    archivos = [f for f in glob.glob(patron) if not os.path.basename(f).startswith(".") and os.path.isfile(f)]
    print(f"Total archivos a procesar ({len(archivos)}): {[os.path.basename(x) for x in archivos]}")

    if not archivos:
        print("No hay archivos en data/raw para procesar.")
        return

    lista_dfs_convenios = []
    lista_dfs_maestro_his = []

    for f in archivos:
        nombre_base = os.path.basename(f)
        nombre_lower = nombre_base.lower()

        if "consolidado_master" in nombre_lower or "master_2026" in nombre_lower:
            print(f"Procesando Maestro HIS-FONASA: {nombre_base}")
            df_m = leer_archivo_generico(f).drop_duplicates().fillna("")
            lista_dfs_maestro_his.append(df_m)
            print(f"  -> {len(df_m)} registros únicos preparados para '{HOJA_MAESTRO_HIS}'.")
            continue

        if "dipreca" in nombre_lower and nombre_lower.endswith((".xlsx", ".xls")):
            print(f"Procesando Excel DIPRECA: {nombre_base}")
            xl = pd.ExcelFile(f)
            for h_req in HOJAS_DIPRECA:
                h_real = next((s for s in xl.sheet_names if s.strip().lower() == h_req.strip().lower()), None)
                if h_real:
                    df = pd.read_excel(xl, sheet_name=h_real, dtype=object)
                    tipo = "HMQ" if "hmq" in h_real.lower() else ("Paquetes" if "paquetes" in h_real.lower() else "Prestaciones")
                    df_cal = mapear_a_esquema(df, "DIPRECA", f"DIPRECA_{h_real}", nombre_base, tipo)
                    lista_dfs_convenios.append(df_cal)
                    print(f"  -> {h_real}: {len(df_cal)} filas mapeadas.")
        else:
            print(f"Procesando insumo: {nombre_base}")
            df = leer_archivo_generico(f)
            cliente = "ISL" if "isl" in nombre_lower else ("ARMADA" if "armada" in nombre_lower else ("Maestro RedSalud" if "maestro" in nombre_lower else nombre_base))
            etiqueta = os.path.splitext(nombre_base)[0]
            df_cal = mapear_a_esquema(df, cliente, etiqueta, nombre_base)
            lista_dfs_convenios.append(df_cal)
            filial_det = df_cal["filial"].iloc[0] if len(df_cal) > 0 and df_cal["filial"].iloc[0] else "General"
            print(f"  -> {cliente} ({filial_det}): {len(df_cal)} filas mapeadas.")

    if lista_dfs_convenios:
        df_total = pd.concat(lista_dfs_convenios, ignore_index=True)
        
        if SOLO_VIGENCIA_2026:
            antes = len(df_total)
            df_total = df_total[df_total["año"].astype(str).str.strip().isin(["2026", ""])].copy()
            print(f"Filtro vigencia 2026 aplicado: {antes} -> {len(df_total)} filas activas.")

        mascara_insumos = df_total["tipo prestación"].astype(str).str.upper().str.contains("M&I|INSUMO|FARMACO", regex=True)
        
        df_prestaciones = df_total[~mascara_insumos].copy()
        df_insumos = df_total[mascara_insumos].copy()

        print("=== RESUMEN CONSOLIDACIÓN ===")
        print(f"Prestaciones Clínicas (destinado a {HOJA_PRESTACIONES}): {len(df_prestaciones)} filas")
        print(f"Materiales e Insumos M&I (separados): {len(df_insumos)} filas")

        escribir_en_sheet(client, SPREADSHEET_ID_PRESTACIONES, HOJA_PRESTACIONES, df_prestaciones, COLUMNAS_CALIBRADAS)

        if SPREADSHEET_ID_INSUMOS.strip():
            escribir_en_sheet(client, SPREADSHEET_ID_INSUMOS.strip(), HOJA_INSUMOS, df_insumos, COLUMNAS_CALIBRADAS)
        else:
            print("Nota: SPREADSHEET_ID_INSUMOS vacío; los ítems M&I se mantuvieron excluidos de la hoja principal.")

    if lista_dfs_maestro_his:
        df_maestro_final = pd.concat(lista_dfs_maestro_his, ignore_index=True).drop_duplicates()
        escribir_en_sheet(client, SPREADSHEET_ID_PRESTACIONES, HOJA_MAESTRO_HIS, df_maestro_final, list(df_maestro_final.columns))

    print("Consolidación finalizada con éxito.")

if __name__ == "__main__":
    sincronizar_aranceles()
