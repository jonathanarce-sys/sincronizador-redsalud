import os
import glob
import json
import base64
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

# 1. Parámetros Google Sheets
SPREADSHEET_ID_MAESTRA = "1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek".strip()
HOJA_DESTINO = "RAW_Data_Ingesta"
CARPETA_RAW = "data/raw"
FILA_INICIO = 19019  # Celda exacta donde se anexa la nueva información

def obtener_cliente_gspread():
    posibles = ["GCP_JSON_BASE64", "GCP_SERVICE_ACCOUNT", "GOOGLE_CREDENTIALS", "GCP_JSON"]
    val = None
    for k in posibles:
        if k in os.environ and os.environ[k].strip():
            val = os.environ[k].strip()
            break
    if not val:
        raise ValueError("No se encontraron credenciales de Google Cloud en GitHub Secrets.")
    try:
        pad = len(val) % 4
        if pad: val += "=" * (4 - pad)
        creds_dict = json.loads(base64.b64decode(val).decode("utf-8"))
    except Exception:
        creds_dict = json.loads(val)
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    return gspread.authorize(Credentials.from_service_account_info(creds_dict, scopes=scopes))

def leer_archivo(ruta):
    """Lee archivos .csv o .xlsx manejando separadores y encodings habituales."""
    nombre = ruta.lower()
    if nombre.endswith(".csv"):
        for sep in [",", ";", "\t"]:
            try:
                df = pd.read_csv(ruta, sep=sep, encoding="utf-8")
                if len(df.columns) > 1:
                    return df
            except Exception:
                try:
                    df = pd.read_csv(ruta, sep=sep, encoding="latin1")
                    if len(df.columns) > 1:
                        return df
                except Exception:
                    pass
        return pd.read_csv(ruta, engine="python", encoding="latin1")
    else:
        return pd.read_excel(ruta)

def sincronizar_aranceles():
    print("Conectando con Google Sheets...")
    client = obtener_cliente_gspread()
    ss = client.open_by_key(SPREADSHEET_ID_MAESTRA)
    
    # Buscar pestaña RAW_Data_Ingesta
    ws = None
    for w in ss.worksheets():
        if w.title.strip().lower() == HOJA_DESTINO.lower():
            ws = w
            break
    if not ws:
        raise ValueError(f"No se encontró la hoja '{HOJA_DESTINO}' en el Google Sheet.")

    # 2. Localizar archivos en data/raw (excluyendo .gitkeep)
    patron = os.path.join(CARPETA_RAW, "*")
    archivos = [f for f in glob.glob(patron) if not os.path.basename(f).startswith(".")]
    print(f"Archivos encontrados en {CARPETA_RAW}: {archivos}")

    if not archivos:
        print("No hay archivos nuevos en data/raw para procesar.")
        return

    registros_a_insertar = []

    for f in archivos:
        print(f"Procesando: {f}")
        df = leer_archivo(f)
        
        # Llenar nulos para evitar errores JSON en la API de Google Sheets
        df = df.fillna("")
        
        # Convertir a matriz de texto/valores sin cabecera (solo la data)
        datos = df.values.tolist()
        registros_a_insertar.extend(datos)
        print(f" -> {len(datos)} filas extraídas de {os.path.basename(f)}")

    if not registros_a_insertar:
        print("No se encontraron registros para anexar.")
        return

    print(f"Total filas a anexar: {len(registros_a_insertar)}")
    
    # 3. Determinar rango de escritura exacto desde FILA_INICIO
    total_filas = len(registros_a_insertar)
    fila_fin = FILA_INICIO + total_filas - 1
    total_cols = len(registros_a_insertar[0])
    col_fin = gspread.utils.rowcol_to_a1(1, total_cols).replace("1", "")
    
    # Asegurar que la hoja tenga suficientes filas disponibles
    filas_actuales = ws.row_count
    if filas_actuales < fila_fin:
        ws.add_rows(fila_fin - filas_actuales + 100)

    # 4. Actualizar ÚNICAMENTE el bloque desde la fila 19019 (sin tocar 1:19018)
    rango_actualizacion = f"A{FILA_INICIO}:{col_fin}{fila_fin}"
    print(f"Escribiendo en Google Sheets en el rango: {rango_actualizacion}...")
    
    ws.update(range_name=rango_actualizacion, values=registros_a_insertar)
    print(f"Completado con éxito. Se anexaron {total_filas} filas desde la fila {FILA_INICIO} hasta la {fila_fin}.")

if __name__ == "__main__":
    sincronizar_aranceles()
