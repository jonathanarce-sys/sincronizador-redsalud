import os
import re
import json
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1qxeY4CQN-g-bHqbfEpr2MjQXzObpNG5fSxThqexbXHo"
TARGET_WORKSHEET = "RAW_Data_Ingesta"
TEMPLATE_WORKSHEET = "Propuesta"  # Pestaña molde para los encabezados

def clean_text(text):
    if pd.isna(text):
        return ""
    return re.sub(r'\s+', ' ', str(text)).strip()

def procesar_archivos_raw(folder_path="data/raw"):
    if not os.path.exists(folder_path):
        print(f"La carpeta {folder_path} no existe.")
        return pd.DataFrame()

    files = [f for f in os.listdir(folder_path) if f.endswith('.xls') or f.endswith('.xlsx') or f.endswith('.csv')]
    all_dfs = []

    for f in sorted(files):
        if f.startswith('.') or f == '.gitkeep':
            continue

        file_path = os.path.join(folder_path, f)
        try:
            if f.endswith('.csv'):
                try:
                    df = pd.read_csv(file_path, encoding='utf-8')
                except UnicodeDecodeError:
                    df = pd.read_csv(file_path, encoding='latin-1')
            else:
                dfs = pd.read_html(file_path)
                df = dfs[0]

            filename_clean = f.replace('.xls', '').replace('.xlsx', '').replace('.csv', '')
            
            if 'GES' in filename_clean.upper():
                tipo_reporte = 'GES_NOGES'
                centro = filename_clean.upper().replace('GESNOGES', '').replace('GESNOGE', '').replace('GES', '').strip()
            elif 'GRD' in filename_clean.upper():
                tipo_reporte = 'GRD'
                centro = filename_clean.upper().replace('GRD', '').strip()
            else:
                tipo_reporte = 'OTRO'
                centro = filename_clean.strip()

            centro = clean_text(centro)

            df.insert(0, 'Tipo_Reporte', tipo_reporte)
            df.insert(0, 'Filial_Centro', centro)
            df.insert(0, 'Archivo_Origen', f)

            all_dfs.append(df)
            print(f"✔ Procesado: {f} ({len(df)} filas)")
        except Exception as e:
            print(f"✖ Error procesando {f}: {e}")

    if all_dfs:
        master_df = pd.concat(all_dfs, ignore_index=True)
        for col in master_df.select_dtypes(include='object').columns:
            master_df[col] = master_df[col].apply(clean_text)
        return master_df
    return pd.DataFrame()

def obtener_cliente_gspread():
    sa_key_env = os.getenv("GCP_SA_KEY")
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]

    if sa_key_env:
        creds_dict = json.loads(sa_key_env)
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    elif os.path.exists("credentials.json"):
        creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
    else:
        raise FileNotFoundError("No se encontraron credenciales de Google Service Account en GCP_SA_KEY.")

    return gspread.authorize(creds)

def main():
    print("Iniciando consolidación desde data/raw...")
    df_master = procesar_archivos_raw("data/raw")
    
    if df_master.empty:
        print("No se encontraron archivos válidos en data/raw.")
        return

    print("Conectando a Google Sheets...")
    gc = obtener_cliente_gspread()
    sh = gc.open_by_key(SPREADSHEET_ID)

    # Búsqueda insensible a mayúsculas y espacios para la pestaña 'Propuesta'
    encabezados_propuesta = []
    try:
        all_worksheets = sh.worksheets()
        target_sheet = None
        for ws in all_worksheets:
            if ws.title.strip().lower() == TEMPLATE_WORKSHEET.lower():
                target_sheet = ws
                break

        if target_sheet:
            encabezados_propuesta = target_sheet.row_values(1)
            print(f"✔ Encabezados obtenidos de '{target_sheet.title}': {len(encabezados_propuesta)} columnas.")
        else:
            print(f"⚠ No se encontró la pestaña '{TEMPLATE_WORKSHEET}'. Pestañas disponibles: {[ws.title for ws in all_worksheets]}")
    except Exception as e:
        print(f"⚠ Error leyendo encabezados de '{TEMPLATE_WORKSHEET}': {e}")

    # Filtrar y reordenar columnas si se obtuvieron encabezados
    if encabezados_propuesta:
        df_master = df_master.reindex(columns=encabezados_propuesta)

    # Buscar o crear pestaña RAW_Data_Ingesta
    try:
        worksheet = sh.worksheet(TARGET_WORKSHEET)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = sh.add_worksheet(title=TARGET_WORKSHEET, rows=100, cols=len(encabezados_propuesta) or 20)

    df_master = df_master.fillna("")
    data_to_upload = [df_master.columns.tolist()] + df_master.astype(str).values.tolist()

    worksheet.clear()
    # Sintaxis actualizada para evitar DeprecationWarning
    worksheet.update(range_name="A1", values=data_to_upload)
    print(f"✔ Ingesta finalizada con éxito: {len(df_master)} filas alineadas y subidas a '{TARGET_WORKSHEET}'.")

if __name__ == "__main__":
    main()
