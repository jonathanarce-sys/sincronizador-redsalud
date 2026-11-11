import os
import glob
import json
import base64
import math
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID_MAESTRA = "1qxeY4CQN-g-bHqbfEpr2MjQXzObpNG5fSxThqexbXHo"
HOJA_DESTINO = "RAW_DATA_INGESTA"
CARPETA_RAW = "data/raw"
BATCH_SIZE = 3000

# 1. Esquema exacto de columnas solicitado para calibrar la hoja
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
    "lugar_his"
]

HOJAS_DIPRECA = ["2026_Prestaciones", "2026_Paquetes", "2026_HMQ"]

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
    return txt

def mapear_a_esquema(df_raw, cliente_nombre, origen_etiqueta, tipo_prestacion=""):
    """
    Homologa y traspasa automáticamente las columnas del archivo original 
    hacia las 25 columnas maestras calibradas.
    """
    df_out = pd.DataFrame("", index=range(len(df_raw)), columns=COLUMNAS_CALIBRADAS)
    
    # Metadatos fijos
    df_out["cliente"] = cliente_nombre
    df_out["año"] = "2026"
    df_out["tipo_arancel [origen]"] = origen_etiqueta
    df_out["tipo prestación"] = tipo_prestacion
    
    # Mapeo inteligente según coincidencias en los encabezados del insumo
    cols_origen = {str(c).strip().lower(): c for c in df_raw.columns}

    for col_orig_lower, col_orig_real in cols_origen.items():
        # Código Fonasa
        if "fonasa" in col_orig_lower:
            df_out["código_fonasa"] = df_raw[col_orig_real]
        # Código RedSalud
        elif "redsalud" in col_orig_lower and ("cod" in col_orig_lower or "código" in col_orig_lower):
            df_out["código_redsalud [no TC]"] = df_raw[col_orig_real]
        # Código Cliente / Prestación
        elif any(k in col_orig_lower for k in ["codigo", "código", "cod_"]):
            if "cliente" in col_orig_lower:
                df_out["_cliente"] = df_raw[col_orig_real]
            elif df_out["código"].replace("", pd.NA).isna().all():
                df_out["código"] = df_raw[col_orig_real]
        # Glosa / Descripción de la prestación
        elif any(k in col_orig_lower for k in ["glosa", "prestacion", "prestación", "descripcion", "descripción"]):
            df_out["glosa prestación"] = df_raw[col_orig_real]
        # Precio / Valor / Arancel
        elif any(k in col_orig_lower for k in ["precio", "total", "arancel", "valor", "tarifa"]):
            if df_out["precio_total"].replace("", pd.NA).isna().all():
                df_out["precio_total"] = df_raw[col_orig_real]
        # Ámbito
        elif "ambito" in col_orig_lower or "ámbito" in col_orig_lower:
            df_out["ámbito"] = df_raw[col_orig_real]
        # Recargos
        elif "%" in col_orig_lower and "recargo" in col_orig_lower:
            df_out["%_recargo"] = df_raw[col_orig_real]
        elif "recargo" in col_orig_lower:
            df_out["recargo"] = df_raw[col_orig_real]
        # Fechas de vigencia
        elif "desde" in col_orig_lower or "inicio" in col_orig_lower:
            df_out["vigencia desde"] = df_raw[col_orig_real]
        elif "hasta" in col_orig_lower or "fin" in col_orig_lower or "termino" in col_orig_lower:
            df_out["vigencia_hasta"] = df_raw[col_orig_real]

    return df_out

def sincronizar_aranceles():
    print("Conectando con Google Sheets...")
    client = obtener_cliente_gspread()
    ss = client.open_by_key(SPREADSHEET_ID_MAESTRA)
    
    ws = None
    objetivo = HOJA_DESTINO.strip().lower()
    for w in ss.worksheets():
        if w.title.strip().lower() == objetivo:
            ws = w
            break

    if not ws:
        raise ValueError(f"No se encontro la hoja '{HOJA_DESTINO}'.")

    print(f"Pestaña identificada con exito: '{ws.title}'")

    patron = os.path.join(CARPETA_RAW, "*")
    archivos = [f for f in glob.glob(patron) if not os.path.basename(f).startswith(".")]
    print(f"Archivos encontrados: {[os.path.basename(x) for x in archivos]}")

    if not archivos:
        print("No hay archivos en data/raw para procesar.")
        return

    dataframes_calibrados = []

    for f in archivos:
        nombre_base = os.path.basename(f)
        nombre_lower = nombre_base.lower()

        # 1. Caso DIPRECA Excel (3 pestañas requeridas)
        if "dipreca" in nombre_lower and nombre_lower.endswith((".xlsx", ".xls")):
            print(f"Procesando Excel DIPRECA: {nombre_base}")
            xl = pd.ExcelFile(f)
            hojas_disponibles = xl.sheet_names

            for h_req in HOJAS_DIPRECA:
                h_real = next((s for s in hojas_disponibles if s.strip().lower() == h_req.strip().lower()), None)
                if h_real:
                    print(f"  -> Extrayendo hoja DIPRECA: '{h_real}'...")
                    df = pd.read_excel(xl, sheet_name=h_real, dtype=object)
                    
                    # Identificar tipo según pestaña
                    tipo = "HMQ" if "hmq" in h_real.lower() else ("Paquetes" if "paquetes" in h_real.lower() else "Prestaciones")
                    df_cal = mapear_a_esquema(df, cliente_nombre="DIPRECA", origen_etiqueta=f"DIPRECA_{h_real}", tipo_prestacion=tipo)
                    dataframes_calibrados.append(df_cal)
                    print(f"     {len(df_cal)} filas mapeadas al esquema.")
                else:
                    print(f"  -> AVISO: Pestaña '{h_req}' no encontrada.")

        # 2. Caso ARMADA y Maestro Aranceles
        else:
            print(f"Procesando insumo: {nombre_base}")
            if nombre_lower.endswith(".csv"):
                try:
                    df = pd.read_csv(f, sep=None, engine="python", encoding="utf-8", dtype=object)
                except Exception:
                    df = pd.read_csv(f, sep=None, engine="python", encoding="latin1", dtype=object)
            else:
                df = pd.read_excel(f, dtype=object)

            cliente = "ARMADA" if "armada" in nombre_lower else ("Maestro RedSalud" if "maestro" in nombre_lower else nombre_base)
            etiqueta = os.path.splitext(nombre_base)[0]
            df_cal = mapear_a_esquema(df, cliente_nombre=cliente, origen_etiqueta=etiqueta)
            dataframes_calibrados.append(df_cal)
            print(f"     {len(df_cal)} filas mapeadas al esquema.")

    if not dataframes_calibrados:
        print("No hay registros para consolidar.")
        return

    # Consolidar todas las tablas bajo el mismo estándar de 25 columnas
    df_final = pd.concat(dataframes_calibrados, ignore_index=True)
    df_final = df_final.fillna("")

    filas_sanitizadas = []
    for fila in df_final.values.tolist():
        filas_sanitizadas.append([limpiar_celda(c) for c in fila])

    # Fila 1: Encabezados exactos; Fila 2+: Datos mapeados
    matriz_final = [COLUMNAS_CALIBRADAS] + filas_sanitizadas
    total_filas = len(matriz_final)
    col_fin = gspread.utils.rowcol_to_a1(1, len(COLUMNAS_CALIBRADAS)).replace("1", "")

    print(f"Limpiando hoja '{ws.title}'...")
    ws.clear()

    if ws.row_count < total_filas:
        ws.add_rows(total_filas - ws.row_count + 100)

    print(f"Insertando {total_filas} filas calibradas (encabezado + datos) en la hoja...")

    for i in range(0, total_filas, BATCH_SIZE):
        bloque = matriz_final[i:i + BATCH_SIZE]
        f_inicio = 1 + i
        f_termino = f_inicio + len(bloque) - 1
        rango_bloque = f"A{f_inicio}:{col_fin}{f_termino}"
        print(f"  Escribiendo bloque: {rango_bloque} ({len(bloque)} registros)...")
        ws.update(range_name=rango_bloque, values=bloque)

    print(f"Carga finalizada con éxito: {total_filas - 1} registros calibrados bajo los 25 encabezados solicitados.")

if __name__ == "__main__":
    sincronizar_aranceles()
