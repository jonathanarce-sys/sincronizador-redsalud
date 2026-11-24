import os
import re
import glob
import json
import time
import base64
import unicodedata
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 1. CONFIGURACIÓN Y ESQUEMA DE 23 COLUMNAS
# ==========================================
CARPETA_RAW = os.environ.get("CARPETA_RAW", "data/raw").strip()
HOJA_DESTINO = "RAW_Data_Ingesta"
TAMANO_LOTE = 20000  # Filas por bloque para evitar error 500 de Google Sheets API

SPREADSHEET_ID_ARANCELES = os.environ.get("SPREADSHEET_ID_ARANCELES", "").strip()

ENCABEZADOS_RAW_INGESTA = [
    "filial",
    "sociedad",
    "cliente",
    "contrato",
    "id_licitación",
    "centro",
    "año",
    "tipo_arancel [origen]",
    "código_redsalud [no TC]",
    "código_cliente",
    "código_fonasa",
    "glosa_prestación",
    "tipo_prestación",
    "Indexador",
    "precio_total",
    "ámbito",
    "recargo",
    "%_recargo",
    "vigencia_desde",
    "vigencia_hasta",
    "id_convenio_cliente",
    "Convenio_redsalud",
    "código_lugar_his",
]

ROLES_HMQ = [
    ("1º CIR", ["1º CIR", "1° CIR", "1ER CIR", "PRIMER CIRUJANO", "CIRUJANO 1"]),
    ("2º CIR", ["2º CIR", "2° CIR", "2DO CIR", "SEGUNDO CIRUJANO", "CIRUJANO 2"]),
    ("3º CIR", ["3º CIR", "3° CIR", "3ER CIR", "TERCER CIRUJANO", "CIRUJANO 3"]),
    ("4º CIR", ["4º CIR", "4° CIR", "4TO CIR", "CUARTO CIRUJANO", "CIRUJANO 4"]),
    ("ANEST", ["ANEST", "ANESTESIA", "ANESTESISTA", "ANESTESIOLOGO"]),
    ("ARSENALERA", ["ARSENALERA", "ARSENALERIA", "ARSENALERO"]),
]

ALIAS_COLUMNAS = {
    "filial": ["FILIAL", "CLINICA", "CLÍNICA", "SEDE_FILIAL"],
    "sociedad": ["SOCIEDAD", "RAZON SOCIAL", "RAZÓN SOCIAL", "RUT SOCIEDAD"],
    "cliente": ["CLIENTE", "INSTITUCION", "INSTITUCIÓN", "ORGANISMO", "MANDANTE"],
    "contrato": ["CONTRATO", "NOMBRE CONTRATO", "CONVENIO"],
    "id_licitación": ["ID_LICITACION", "ID_LICITACIÓN", "ID LICITACION", "CODIGO LICITACION", "CÓDIGO LICITACIÓN", "LICITACION"],
    "centro": ["CENTRO", "CENTRO MEDICO", "CENTRO MÉDICO", "SEDE", "SUCURSAL"],
    "año": ["AÑO", "ANO", "PERIODO"],
    "tipo_arancel [origen]": ["TIPO_ARANCEL [ORIGEN]", "TIPO_ARANCEL", "TIPO ARANCEL", "ORIGEN"],
    "código_redsalud [no TC]": ["CODIGO_REDSALUD [NO TC]", "CÓDIGO_REDSALUD [NO TC]", "CODIGO_REDSALUD", "CÓDIGO_REDSALUD", "COD_REDSALUD", "CODIGO REDSALUD", "CODIGO INTERNO"],
    "código_cliente": ["CODIGO_CLIENTE", "CÓDIGO_CLIENTE", "COD_CLIENTE", "CODIGO CLIENTE", "HOMOLOGO"],
    "código_fonasa": ["CODIGO_FONASA", "CÓDIGO_FONASA", "COD_FONASA", "CODIGO FONASA", "FONASA"],
    "glosa_prestación": ["GLOSA_PRESTACION", "GLOSA_PRESTACIÓN", "GLOSA", "PRESTACION", "PRESTACIÓN", "NOMBRE PRESTACION", "DESCRIPCION", "DESCRIPCIÓN"],
    "tipo_prestación": ["TIPO_PRESTACION", "TIPO_PRESTACIÓN", "TIPO PRESTACION", "CATEGORIA", "RUBRO", "GRUPO"],
    "Indexador": ["INDEXADOR", "REAJUSTE", "MONEDA", "FACTOR"],
    "precio_total": ["PRECIO_TOTAL", "PRECIO TOTAL", "VALOR TOTAL", "VALOR", "PRECIO", "ARANCEL", "TARIFA", "MONTO"],
    "ámbito": ["AMBITO", "ÁMBITO", "MODALIDAD", "TIPO ATENCION", "TIPO ATENCIÓN"],
    "recargo": ["RECARGO", "APLICA RECARGO", "TIPO RECARGO"],
    "%_recargo": ["%_RECARGO", "% RECARGO", "PORCENTAJE RECARGO", "PORC_RECARGO"],
    "vigencia_desde": ["VIGENCIA_DESDE", "VIGENCIA DESDE", "FECHA INICIO", "DESDE"],
    "vigencia_hasta": ["VIGENCIA_HASTA", "VIGENCIA HASTA", "FECHA TERMINO", "FECHA TÉRMINO", "HASTA"],
    "id_convenio_cliente": ["ID_CONVENIO_CLIENTE", "ID CONVENIO CLIENTE", "COD CONVENIO CLIENTE"],
    "Convenio_redsalud": ["CONVENIO_REDSALUD", "CONVENIO REDSALUD", "CONVENIO HIS"],
    "código_lugar_his": ["CODIGO_LUGAR_HIS", "CÓDIGO_LUGAR_HIS", "CODIGO LUGAR HIS", "LUGAR HIS", "CENTRO COSTO"],
}

CATALOGO_FILIALES = [
    (["PROVIDENCIA"], "RS Providencia", "96.536.000-8"),
    (["VALPARAISO", "VALPARAÍSO"], "RS Valparaíso", "96.543.000-6"),
    (["MAGALLANES"], "RS Magallanes", "96.541.000-5"),
    (["ELQUI"], "RS Elqui", "99.533.790-8"),
    (["IQUIQUE"], "RS Iquique", "96.598.850-0"),
    (["SANTIAGO"], "RS Santiago", "96.524.000-2"),
    (["RANCAGUA"], "RS Rancagua", "96.542.000-0"),
    (["TEMUCO"], "RS Mayor Temuco", "96.537.000-3"),
    (["VITACURA"], "RS Vitacura", "78.053.560-1"),
    (["CMD"], "Centros Médicos RedSalud", "96.856.000-2"),
]

# ==========================================
# 2. UTILIDADES
# ==========================================
def obtener_cliente_gspread():
    posibles = [
        "GCP_JSON_BASE64", "GCP_SERVICE_ACCOUNT", "GOOGLE_CREDENTIALS",
        "GCP_JSON", "GCP_SA_KEY", "GCP_CREDENTIALS"
    ]
    val = next((os.environ[k].strip() for k in posibles if k in os.environ and os.environ[k].strip()), None)
    if not val:
        raise ValueError("Sin credenciales GCP en el entorno.")
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
    return gspread.authorize(Credentials.from_service_account_info(creds_dict, scopes=scopes)), creds_dict.get("client_email", "SA")

def norm_txt(s):
    s = unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode("utf-8")
    return re.sub(r"\s+", " ", s).strip().upper()

def limpiar_codigo_redsalud(val):
    s = str(val or "").strip()
    s = re.sub(r"[\[\(\-]?\s*\bTC\b\s*[\]\)]?", "", s, flags=re.IGNORECASE).strip()
    return s

def parsear_monto(val):
    if val is None or val == "":
        return 0
    if isinstance(val, (int, float)):
        if pd.isna(val):
            return 0
        return int(round(val))
    limpio = re.sub(r"[^\d]", "", str(val))
    return int(limpio) if limpio else 0

def inferir_metadatos_fuente(nombre_fuente):
    u = norm_txt(nombre_fuente)
    cliente_def = ""
    if u.startswith("ISL"):
        cliente_def = "ISL"
    elif "DIPRECA" in u:
        cliente_def = "DIPRECA"
    elif "ARMADA" in u:
        cliente_def = "Armada de Chile"
    elif "JEAFOSALE" in u:
        cliente_def = "JEAFOSALE"

    filial_def, soc_def = "", ""
    for claves, nom_f, rut_f in CATALOGO_FILIALES:
        if any(c in u for c in claves):
            filial_def, soc_def = nom_f, rut_f
            break

    anio_match = re.search(r"\b(202[4-9])\b", u)
    anio_def = anio_match.group(1) if anio_match else ""

    tipo_prest_def = ""
    if "PAQUETE" in u:
        tipo_prest_def = "Paquete"
    elif "HMQ" in u:
        tipo_prest_def = "HMQ"

    return {
        "cliente": cliente_def,
        "filial": filial_def,
        "sociedad": soc_def,
        "año": anio_def,
        "tipo_prestación": tipo_prest_def
    }

def mapear_columnas_df(columnas):
    col_norm = [norm_txt(c) for c in columnas]
    mapa = {}

    for col_dest, aliases in ALIAS_COLUMNAS.items():
        aliases_norm = [norm_txt(a) for a in aliases]
        encontrada = None
        for a in aliases_norm:
            if a in col_norm:
                encontrada = columnas[col_norm.index(a)]
                break
        if encontrada is None:
            for a in aliases_norm:
                if len(a) >= 5:
                    for i, c in enumerate(col_norm):
                        if a in c:
                            encontrada = columnas[i]
                            break
                if encontrada is not None:
                    break
        if encontrada is not None:
            mapa[col_dest] = encontrada

    cols_hmq = {}
    for rol_std, aliases_rol in ROLES_HMQ:
        aliases_r_norm = [norm_txt(a) for a in aliases_rol]
        for i, c in enumerate(col_norm):
            if any(ar == c or ar in c for ar in aliases_r_norm):
                cols_hmq[rol_std] = columnas[i]
                break

    return mapa, cols_hmq

def leer_csv_robusto(ruta_csv):
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        for sep in (None, ";", ",", "\t"):
            try:
                kwargs = {"dtype": str, "encoding": enc, "keep_default_na": False}
                if sep is None:
                    kwargs["sep"] = None
                    kwargs["engine"] = "python"
                else:
                    kwargs["sep"] = sep
                df = pd.read_csv(ruta_csv, **kwargs)
                if len(df.columns) >= 3:
                    return df
            except Exception:
                continue
    return pd.read_csv(ruta_csv, dtype=str, encoding="latin-1", keep_default_na=False)

def ajustar_fila_encabezado_df(df):
    linea_cols = " ".join(norm_txt(c) for c in df.columns)
    if any(k in linea_cols for k in ("FONASA", "GLOSA", "PRESTACION", "CODIGO", "PRECIO", "ARANCEL")):
        return df

    for idx in range(min(5, len(df))):
        fila_vals = [str(v).strip() for v in df.iloc[idx].tolist()]
        linea_u = " ".join(norm_txt(x) for x in fila_vals)
        if any(k in linea_u for k in ("FONASA", "GLOSA", "PRESTACION", "CODIGO", "PRECIO", "ARANCEL")):
            nuevo_df = df.iloc[idx + 1:].copy()
            nuevo_df.columns = fila_vals
            nuevo_df.reset_index(drop=True, inplace=True)
            return nuevo_df
    return df

def escribir_en_lotes_con_reintento(ws, matriz, col_fin, tamano_lote=20000):
    total_filas = len(matriz)
    for inicio in range(0, total_filas, tamano_lote):
        fin = min(inicio + tamano_lote, total_filas)
        lote = matriz[inicio:fin]
        rango = f"A{inicio + 1}:{col_fin}{fin}"

        exito = False
        for intento in range(1, 5):
            try:
                ws.update(range_name=rango, values=lote)
                print(f"  [OK] Lote escrito {rango} ({len(lote)} filas)", flush=True)
                exito = True
                break
            except Exception as e:
                print(f"  [REINTENTO {intento}/4] Error en lote {rango}: {e}", flush=True)
                time.sleep(3 * intento)
        if not exito:
            raise RuntimeError(f"No se pudo escribir el lote {rango} después de 4 intentos.")
        time.sleep(1.0)

# ==========================================
# 3. PROCESAMIENTO DE DATAFRAME -> 23 COLUMNAS
# ==========================================
def procesar_dataframe(df_raw, etiqueta_origen):
    df = ajustar_fila_encabezado_df(df_raw)
    if df.empty:
        return []

    mapa_cols, cols_hmq = mapear_columnas_df(list(df.columns))
    meta = inferir_metadatos_fuente(etiqueta_origen)
    es_hmq = ("HMQ" in norm_txt(etiqueta_origen)) or (len(cols_hmq) >= 2)

    registros = []
    for _, row in df.iterrows():
        def val(clave, default=""):
            col = mapa_cols.get(clave)
            if col is not None:
                v = str(row.get(col, "")).strip()
                if v and v.lower() != "nan":
                    return v
            return default

        glosa_base = val("glosa_prestación")
        cod_rs = limpiar_codigo_redsalud(val("código_redsalud [no TC]"))
        cod_cli = val("código_cliente")
        cod_fon = val("código_fonasa")

        if not glosa_base and not cod_rs and not cod_fon and not cod_cli:
            continue
        if norm_txt(glosa_base) in ("TOTAL", "SUBTOTAL", "GLOSA", "GLOSA_PRESTACION"):
            continue

        filial = val("filial", meta["filial"])
        sociedad = val("sociedad", meta["sociedad"])
        cliente = val("cliente", meta["cliente"])
        contrato = val("contrato")
        id_lic = val("id_licitación")
        centro = val("centro")
        anio = val("año", meta["año"])
        tipo_arancel_origen = val("tipo_arancel [origen]", etiqueta_origen)
        tipo_prest = val("tipo_prestación", meta["tipo_prestación"])
        indexador = val("Indexador")
        ambito = val("ámbito")
        recargo = val("recargo")
        porc_recargo = val("%_recargo")
        vig_desde = val("vigencia_desde")
        vig_hasta = val("vigencia_hasta")
        id_conv_cli = val("id_convenio_cliente")
        conv_rs = val("Convenio_redsalud")
        cod_lugar_his = val("código_lugar_his")

        if es_hmq and cols_hmq:
            roles_con_monto = []
            for rol_nombre, col_rol in cols_hmq.items():
                monto_rol = parsear_monto(row.get(col_rol, 0))
                if monto_rol > 0:
                    roles_con_monto.append((rol_nombre, monto_rol))

            if roles_con_monto:
                for rol_nombre, monto_rol in roles_con_monto:
                    glosa_rol = f"{glosa_base} - {rol_nombre}".strip(" -")
                    registros.append([
                        filial, sociedad, cliente, contrato, id_lic, centro, anio,
                        tipo_arancel_origen, cod_rs, cod_cli, cod_fon, glosa_rol,
                        "HMQ", indexador, monto_rol, ambito, recargo, porc_recargo,
                        vig_desde, vig_hasta, id_conv_cli, conv_rs, cod_lugar_his
                    ])
                continue

        precio = parsear_monto(val("precio_total"))
        registros.append([
            filial, sociedad, cliente, contrato, id_lic, centro, anio,
            tipo_arancel_origen, cod_rs, cod_cli, cod_fon, glosa_base,
            tipo_prest, indexador, precio, ambito, recargo, porc_recargo,
            vig_desde, vig_hasta, id_conv_cli, conv_rs, cod_lugar_his
        ])

    return registros

# ==========================================
# 4. ORQUESTADOR DESDE data/raw -> RAW_Data_Ingesta
# ==========================================
def consolidar_aranceles():
    print("=== INICIANDO CONSOLIDACIÓN DE ARANCELES (data/raw -> RAW_Data_Ingesta | 23 COLS) ===", flush=True)
    client, sa_email = obtener_cliente_gspread()
    print(f"Autenticado como: {sa_email}", flush=True)

    ss_dest = None
    ws_dest = None
    if SPREADSHEET_ID_ARANCELES:
        ss_dest = client.open_by_key(SPREADSHEET_ID_ARANCELES)
        ws_dest = next((w for w in ss_dest.worksheets() if norm_txt(w.title) == norm_txt(HOJA_DESTINO)), None)
    else:
        for lb in client.openall():
            w = next((x for x in lb.worksheets() if norm_txt(x.title) == norm_txt(HOJA_DESTINO)), None)
            if w:
                ss_dest = lb
                ws_dest = w
                break

    if not ss_dest:
        raise ValueError("No se encontró el Google Sheet con la pestaña 'RAW_Data_Ingesta'.")
    if not ws_dest:
        ws_dest = ss_dest.add_worksheet(title=HOJA_DESTINO, rows=500, cols=len(ENCABEZADOS_RAW_INGESTA))

    print(f"Destino Google Sheet: '{ss_dest.title}' -> pestaña '{ws_dest.title}'", flush=True)

    archivos = sorted(
        glob.glob(os.path.join(CARPETA_RAW, "*.csv")) +
        glob.glob(os.path.join(CARPETA_RAW, "*.xlsx")) +
        glob.glob(os.path.join(CARPETA_RAW, "*.xls"))
    )
    print(f"Archivos encontrados en '{CARPETA_RAW}': {len(archivos)}", flush=True)

    todas_las_filas = []
    for ruta in archivos:
        nombre_archivo = os.path.basename(ruta)
        nombre_sin_ext = os.path.splitext(nombre_archivo)[0].strip()

        if ruta.lower().endswith(".csv"):
            df_csv = leer_csv_robusto(ruta)
            filas_f = procesar_dataframe(df_csv, nombre_sin_ext)
            print(f"  -> [CSV] {nombre_sin_ext}: {len(filas_f)} registros", flush=True)
            todas_las_filas.extend(filas_f)
        else:
            xls = pd.ExcelFile(ruta)
            for hoja_xls in xls.sheet_names:
                df_xls = pd.read_excel(xls, sheet_name=hoja_xls, dtype=str, keep_default_na=False)
                filas_h = procesar_dataframe(df_xls, hoja_xls.strip())
                print(f"  -> [XLSX] {nombre_archivo} [{hoja_xls}]: {len(filas_h)} registros", flush=True)
                todas_las_filas.extend(filas_h)

    matriz_final = [ENCABEZADOS_RAW_INGESTA] + todas_las_filas
    total_filas = len(matriz_final)
    print(f"Total acumulado a cargar: {len(todas_las_filas)} registros (+1 encabezado = {total_filas} filas)", flush=True)

    ws_dest.clear()
    ws_dest.resize(rows=total_filas + 20, cols=len(ENCABEZADOS_RAW_INGESTA))

    col_fin = gspread.utils.rowcol_to_a1(1, len(ENCABEZADOS_RAW_INGESTA)).replace("1", "")
    escribir_en_lotes_con_reintento(ws_dest, matriz_final, col_fin, tamano_lote=TAMANO_LOTE)

    print(f"=== CONSOLIDACIÓN COMPLETADA: {len(todas_las_filas)} registros en '{HOJA_DESTINO}' (23 columnas: A:{col_fin}) ===", flush=True)

if __name__ == "__main__":
    consolidar_aranceles()
