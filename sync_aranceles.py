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
CARPETA_REF = os.environ.get("CARPETA_REF", "data/ref").strip()
NOMBRE_ARCHIVO_CALIBRACION = "Calibración de información - Datos_Verticales.csv"

HOJA_DESTINO = "RAW_Data_Ingesta"
TAMANO_LOTE = 20000

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
    "tipo_arancel [origen]": ["TIPO_ARANCEL [ORIGEN]", "TIPO_ARANCEL", "TIPO ARANCEL", "ORIGEN ARANCEL", "MODALIDAD ARANCEL"],
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
    "código_lugar_his": ["CODIGO_LUGAR_HIS", "CÓDIGO_LUGAR_HIS", "CODIGO LUGAR HIS", "LUGAR HIS", "CENTRO COSTO", "CODIGO_ITEM_HIS"],
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

def normalizar_codigo_fonasa(val):
    """Normaliza códigos Fonasa a 7 dígitos con cero a la izquierda (ej. '101001' -> '0101001')."""
    s = re.sub(r"[^\d]", "", str(val or "").strip())
    if not s:
        return ""
    if len(s) == 6:
        return "0" + s
    return s

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

# ==========================================
# 3. CATÁLOGO DE HOMOLOGACIÓN HIS (Datos_Verticales.csv)
# ==========================================
def cargar_catalogo_homologacion_his():
    """
    Carga 'Calibración de información - Datos_Verticales.csv' como diccionario de búsqueda
    para completar Codigo_Item_HIS, Unidad de Negocio (tipo_prestación) y Sede/Centro.
    """
    posibles_rutas = [
        os.path.join(CARPETA_REF, NOMBRE_ARCHIVO_CALIBRACION),
        os.path.join(CARPETA_RAW, NOMBRE_ARCHIVO_CALIBRACION),
        NOMBRE_ARCHIVO_CALIBRACION,
    ]
    ruta_encontrada = next((p for p in posibles_rutas if os.path.exists(p)), None)

    catalogo = {
        "por_fonasa_y_glosa": {},  # (fonasa_7d, glosa_norm) -> {his, unidad, sede}
        "por_fonasa_unico": {},    # fonasa_7d -> {his, unidad}
        "por_glosa": {},           # glosa_norm -> {his, unidad, fonasa}
        "sedes_validas": set(),
    }

    if not ruta_encontrada:
        print(f"[INFO] No se encontró '{NOMBRE_ARCHIVO_CALIBRACION}'. Se continuará sin homologación externa HIS.", flush=True)
        return catalogo

    print(f"Cargando catálogo maestro de homologación HIS desde: '{ruta_encontrada}'...", flush=True)
    df_cal = leer_csv_robusto(ruta_encontrada)

    # Normalizar nombres de columnas
    cols_map = {norm_txt(c): c for c in df_cal.columns}
    col_un = cols_map.get("UNIDAD_NEGOCIO")
    col_glosa = cols_map.get("GLOSA PRESTACION") or cols_map.get("GLOSA_PRESTACION")
    col_fon = cols_map.get("CODIGO FONASA") or cols_map.get("CODIGO_FONASA")
    col_his = cols_map.get("CODIGO_ITEM_HIS") or cols_map.get("CODIGO ITEM HIS")
    col_sede = cols_map.get("SEDE")

    fonasa_candidatos = {}

    for _, r in df_cal.iterrows():
        glosa_raw = str(r.get(col_glosa, "")).strip() if col_glosa else ""
        glosa_n = norm_txt(glosa_raw)
        fon_raw = str(r.get(col_fon, "")).strip() if col_fon else ""
        fon_7d = "" if "SIN CODIGO" in norm_txt(fon_raw) else normalizar_codigo_fonasa(fon_raw)
        his_val = str(r.get(col_his, "")).strip() if col_his else ""
        un_val = str(r.get(col_un, "")).strip() if col_un else ""
        sede_val = str(r.get(col_sede, "")).strip() if col_sede else ""

        if his_val.lower() in ("nan", "none"):
            his_val = ""
        if un_val.lower() in ("nan", "none"):
            un_val = ""
        if sede_val:
            catalogo["sedes_validas"].add(norm_txt(sede_val))

        if not his_val and not un_val:
            continue

        info = {"his": his_val, "unidad": un_val, "fonasa": fon_7d, "sede": sede_val}

        if fon_7d and glosa_n:
            clave_fg = (fon_7d, glosa_n)
            if clave_fg not in catalogo["por_fonasa_y_glosa"] or his_val:
                catalogo["por_fonasa_y_glosa"][clave_fg] = info

        if glosa_n:
            if glosa_n not in catalogo["por_glosa"] or his_val:
                catalogo["por_glosa"][glosa_n] = info

        if fon_7d and his_val:
            fonasa_candidatos.setdefault(fon_7d, set()).add((his_val, un_val))

    # Guardar homologación por Fonasa cuando apunta de forma unívoca a un solo Codigo_Item_HIS
    for fon_7d, pares in fonasa_candidatos.items():
        his_distintos = {p[0] for p in pares if p[0]}
        un_distintas = [p[1] for p in pares if p[1]]
        if len(his_distintos) == 1:
            catalogo["por_fonasa_unico"][fon_7d] = {
                "his": next(iter(his_distintos)),
                "unidad": un_distintas[0] if un_distintas else ""
            }

    print(
        f"  -> Catálogo HIS cargado: {len(catalogo['por_fonasa_y_glosa'])} pares Fonasa+Glosa | "
        f"{len(catalogo['por_fonasa_unico'])} Fonasa unívocos | {len(catalogo['por_glosa'])} glosas.",
        flush=True
    )
    return catalogo

# ==========================================
# 4. METADATOS Y MAPEO DE COLUMNAS
# ==========================================
def inferir_metadatos_fuente(nombre_fuente, nombre_archivo_padre=""):
    u = norm_txt(f"{nombre_archivo_padre} {nombre_fuente}")
    u_fuente = norm_txt(nombre_fuente)

    cliente_def = ""
    es_hoja_dipreca = any(k in u_fuente for k in ("2026_HMQ", "2026_PAQUETE", "2026_PRESTACION"))
    if "DIPRECA" in u or es_hoja_dipreca:
        cliente_def = "DIPRECA"
    elif u_fuente.startswith("ISL") or "ISL_" in u:
        cliente_def = "ISL"
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
    if "PAQUETE" in u_fuente:
        tipo_prest_def = "Paquete"
    elif "HMQ" in u_fuente:
        tipo_prest_def = "HMQ"
    elif "PRESTACION" in u_fuente:
        tipo_prest_def = "Prestación"

    tipo_arancel_def = "Arancel Consolidado"
    if "HMQ" in u_fuente:
        tipo_arancel_def = "Arancel HMQ"
    elif "PAQUETE" in u_fuente:
        tipo_arancel_def = "Arancel Paquetes"
    elif "PRESTACION" in u_fuente:
        tipo_arancel_def = "Arancel Prestaciones"
    elif "MAESTRO" in u_fuente or "TRAZABILIDAD" in u_fuente:
        tipo_arancel_def = "Maestro Trazabilidad"

    return {
        "cliente": cliente_def,
        "filial": filial_def,
        "sociedad": soc_def,
        "año": anio_def,
        "tipo_prestación": tipo_prest_def,
        "tipo_arancel_def": tipo_arancel_def,
        "forzar_cliente": es_hoja_dipreca
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
# 5. PROCESAMIENTO DE DATAFRAME + ENRIQUECIMIENTO HIS
# ==========================================
def procesar_dataframe(df_raw, etiqueta_origen, catalogo_his, nombre_archivo_padre=""):
    df = ajustar_fila_encabezado_df(df_raw)
    if df.empty:
        return [], 0

    mapa_cols, cols_hmq = mapear_columnas_df(list(df.columns))
    meta = inferir_metadatos_fuente(etiqueta_origen, nombre_archivo_padre)
    es_hmq = ("HMQ" in norm_txt(etiqueta_origen)) or (len(cols_hmq) >= 2)

    registros = []
    homologados_his = 0

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
        cod_fon_raw = val("código_fonasa")
        cod_fon_7d = normalizar_codigo_fonasa(cod_fon_raw)

        if not glosa_base and not cod_rs and not cod_fon_raw and not cod_cli:
            continue
        if norm_txt(glosa_base) in ("TOTAL", "SUBTOTAL", "GLOSA", "GLOSA_PRESTACION"):
            continue

        # Cruce con Catálogo Maestro HIS (Datos_Verticales.csv)
        glosa_n = norm_txt(glosa_base)
        match_his = None
        if cod_fon_7d and glosa_n and (cod_fon_7d, glosa_n) in catalogo_his["por_fonasa_y_glosa"]:
            match_his = catalogo_his["por_fonasa_y_glosa"][(cod_fon_7d, glosa_n)]
        elif cod_fon_7d and cod_fon_7d in catalogo_his["por_fonasa_unico"]:
            match_his = catalogo_his["por_fonasa_unico"][cod_fon_7d]
        elif glosa_n and glosa_n in catalogo_his["por_glosa"]:
            match_his = catalogo_his["por_glosa"][glosa_n]

        his_catalogo = match_his.get("his", "") if match_his else ""
        unidad_catalogo = match_his.get("unidad", "") if match_his else ""

        # Rellenar código_redsalud [no TC] si venía vacío y hay Codigo_Item_HIS homologado
        if not cod_rs and his_catalogo:
            cod_rs = his_catalogo
            homologados_his += 1

        # Rellenar código_lugar_his con Codigo_Item_HIS si viene vacío en la hoja de gestión
        cod_lugar_his = val("código_lugar_his")
        if not cod_lugar_his and his_catalogo:
            cod_lugar_his = his_catalogo

        filial = val("filial", meta["filial"])
        sociedad = val("sociedad", meta["sociedad"])
        cliente = "DIPRECA" if meta["forzar_cliente"] else val("cliente", meta["cliente"])

        contrato_raw = val("contrato")
        contrato = contrato_raw if contrato_raw else etiqueta_origen

        id_lic = val("id_licitación")
        centro = val("centro")
        anio = val("año", meta["año"])
        tipo_arancel_val = val("tipo_arancel [origen]", meta["tipo_arancel_def"])

        # Priorizar tipo_prestación de la hoja -> luego UNIDAD_NEGOCIO del catálogo -> luego metadato de hoja
        tipo_prest = val("tipo_prestación") or unidad_catalogo or meta["tipo_prestación"]

        indexador = val("Indexador")
        ambito = val("ámbito")
        recargo = val("recargo")
        porc_recargo = val("%_recargo")
        vig_desde = val("vigencia_desde")
        vig_hasta = val("vigencia_hasta")
        id_conv_cli = val("id_convenio_cliente")
        conv_rs_raw = val("Convenio_redsalud")
        conv_rs = conv_rs_raw if conv_rs_raw else etiqueta_origen

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
                        tipo_arancel_val, cod_rs, cod_cli, cod_fon_raw, glosa_rol,
                        "HMQ", indexador, monto_rol, ambito, recargo, porc_recargo,
                        vig_desde, vig_hasta, id_conv_cli, conv_rs, cod_lugar_his
                    ])
                continue

        precio = parsear_monto(val("precio_total"))
        registros.append([
            filial, sociedad, cliente, contrato, id_lic, centro, anio,
            tipo_arancel_val, cod_rs, cod_cli, cod_fon_raw, glosa_base,
            tipo_prest, indexador, precio, ambito, recargo, porc_recargo,
            vig_desde, vig_hasta, id_conv_cli, conv_rs, cod_lugar_his
        ])

    return registros, homologados_his

# ==========================================
# 6. ORQUESTADOR DESDE data/raw -> RAW_Data_Ingesta
# ==========================================
def consolidar_aranceles():
    print("=== INICIANDO CONSOLIDACIÓN DE ARANCELES + HOMOLOGACIÓN HIS (23 COLS) ===", flush=True)
    client, sa_email = obtener_cliente_gspread()
    print(f"Autenticado como: {sa_email}", flush=True)

    catalogo_his = cargar_catalogo_homologacion_his()

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

    todas_las_filas = []
    total_homologados = 0

    for ruta in archivos:
        nombre_archivo = os.path.basename(ruta)
        # Excluir el archivo de calibración para no duplicarlo como arancel
        if norm_txt(nombre_archivo) == norm_txt(NOMBRE_ARCHIVO_CALIBRACION) or "DATOS_VERTICALES" in norm_txt(nombre_archivo):
            continue

        nombre_sin_ext = os.path.splitext(nombre_archivo)[0].strip()

        if ruta.lower().endswith(".csv"):
            df_csv = leer_csv_robusto(ruta)
            filas_f, hom_f = procesar_dataframe(df_csv, nombre_sin_ext, catalogo_his, nombre_sin_ext)
            print(f"  -> [CSV] {nombre_sin_ext}: {len(filas_f)} registros ({hom_f} homologados con HIS)", flush=True)
            todas_las_filas.extend(filas_f)
            total_homologados += hom_f
        else:
            xls = pd.ExcelFile(ruta)
            for hoja_xls in xls.sheet_names:
                df_xls = pd.read_excel(xls, sheet_name=hoja_xls, dtype=str, keep_default_na=False)
                filas_h, hom_h = procesar_dataframe(df_xls, hoja_xls.strip(), catalogo_his, nombre_sin_ext)
                print(f"  -> [XLSX] {nombre_archivo} [{hoja_xls}]: {len(filas_h)} registros ({hom_h} homologados con HIS)", flush=True)
                todas_las_filas.extend(filas_h)
                total_homologados += hom_h

    matriz_final = [ENCABEZADOS_RAW_INGESTA] + todas_las_filas
    total_filas = len(matriz_final)
    print(f"Total acumulado: {len(todas_las_filas)} registros | Total homologados con HIS: {total_homologados}", flush=True)

    ws_dest.clear()
    ws_dest.resize(rows=total_filas + 20, cols=len(ENCABEZADOS_RAW_INGESTA))

    col_fin = gspread.utils.rowcol_to_a1(1, len(ENCABEZADOS_RAW_INGESTA)).replace("1", "")
    escribir_en_lotes_con_reintento(ws_dest, matriz_final, col_fin, tamano_lote=TAMANO_LOTE)

    print(f"=== CONSOLIDACIÓN COMPLETADA: {len(todas_las_filas)} registros en '{HOJA_DESTINO}' (23 columnas: A:{col_fin}) ===", flush=True)

if __name__ == "__main__":
    consolidar_aranceles()
