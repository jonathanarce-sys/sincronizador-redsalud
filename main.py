import os
import json
import base64
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

# ID de la planilla Google Sheets: Base Maestra Licitaciones y Compras Agiles
SPREADSHEET_ID = "1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek"

def obtener_credenciales_google():
    """Obtiene las credenciales desde variables de entorno (GitHub Actions / .env / Streamlit)."""
    creds_dict = None
    
    # Intento 1: Cadena Base64
    gcp_b64 = os.getenv("GCP_JSON_BASE64")
    if gcp_b64:
        json_bytes = base64.b64decode(gcp_b64)
        creds_dict = json.loads(json_bytes.decode("utf-8"))
    
    # Intento 2: JSON en bruto
    elif os.getenv("GOOGLE_CREDENTIALS_JSON"):
        raw_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
        creds_dict = json.loads(raw_json, strict=False)
        
    # Intento 3: Archivo local (para ejecución local)
    elif os.path.exists("credentials.json"):
        with open("credentials.json", "r", encoding="utf-8") as f:
            creds_dict = json.load(f)

    if not creds_dict:
        raise ValueError("No se encontraron credenciales de Google válidas.")

    if "private_key" in creds_dict:
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    return Credentials.from_service_account_info(creds_dict, scopes=scopes)


def procesar_y_limpiar_data(df: pd.DataFrame) -> pd.DataFrame:
    """Procesa el DataFrame aplicando las reglas de negocio solicitadas."""
    if df.empty:
        return df

    # 1. Eliminar columna Criterios de Evaluación si existe
    cols_eliminar = [c for c in df.columns if "criterio" in c.lower() or "evaluaci" in c.lower()]
    df = df.drop(columns=cols_eliminar, errors="ignore")

    # 2. Identificar y formatear Fechas
    col_inicio = next((c for c in df.columns if "inicio" in c.lower() or "publica" in c.lower() or "creaci" in c.lower()), None)
    
    if col_inicio:
        df[col_inicio] = pd.to_datetime(df[col_inicio], errors="coerce", dayfirst=True)
        # Filtrar solo registros del 2025 en adelante (eliminar 2024)
        df = df[df[col_inicio].dt.year >= 2025]
        # Formatear a texto legible AAAA-MM-DD
        df[col_inicio] = df[col_inicio].dt.strftime("%Y-%m-%d")

    # 3. Asegurar columna 'Fecha de Cierre' para ambos procesos
    col_cierre = next((c for c in df.columns if "cierre" in c.lower() or "termino" in c.lower() or "limite" in c.lower()), "Fecha de Cierre")
    if col_cierre not in df.columns:
        df["Fecha de Cierre"] = "N/A"

    # 4. Asegurar columna 'Comentarios'
    if "Comentarios" not in df.columns:
        df["Comentarios"] = ""

    # 5. Calcular 'Monto Total + IVA (Adjudicado / Estimado)'
    col_monto = next((c for c in df.columns if "monto" in c.lower() or "estimado" in c.lower() or "adjudic" in c.lower()), None)
    
    def calcular_monto_iva(val):
        try:
            val_clean = float(str(val).replace("$", "").replace(".", "").replace(",", ".").strip())
            monto_iva = val_clean * 1.19
            return f"$ {int(monto_iva):,}".replace(",", ".")
        except Exception:
            return "$ 0"

    if col_monto:
        df["Monto Total + IVA (Adjudicado / Estimado)"] = df[col_monto].apply(calcular_monto_iva)
    else:
        df["Monto Total + IVA (Adjudicado / Estimado)"] = "$ 0"

    # 6. Reordenar encabezados estándar
    encabezados_deseados = [
        "Código Proceso",
        "Tipo Proceso",
        "Nombre Proceso",
        "Estado",
        "Fecha de Inicio",
        "Fecha de Cierre",
        "Monto Estimado / Neto",
        "Monto Total + IVA (Adjudicado / Estimado)",
        "Comentarios"
    ]

    # Conservar columnas existentes y reordenar manteniendo coherencia
    columnas_finales = [c for c in encabezados_deseados if c in df.columns] + \
                       [c for c in df.columns if c not in encabezados_deseados]

    return df[columnas_finales]


def actualizar_google_sheets():
    """Conecta a Google Sheets y actualiza la Base Maestra."""
    print("🔄 Iniciando proceso de sincronización con Google Sheets...")

    creds = obtener_credenciales_google()
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1

    # 1. Leer datos existentes en la hoja
    raw_records = sheet.get_all_records()
    df_existente = pd.DataFrame(raw_records)

    if df_existente.empty:
        print("⚠️ La planilla actual está vacía o no tiene datos.")
        return

    print(f"📊 Registros leídos de la planilla: {len(df_existente)}")

    # 2. Aplicar la limpieza y filtrado de reglas de negocio
    df_procesado = procesar_y_limpiar_data(df_existente)

    print(f"✅ Registros conservados (Año 2025+): {len(df_procesado)}")

    # 3. Limpiar la hoja e insertar los nuevos datos con los nuevos encabezados
    sheet.clear()
    
    # Preparar matriz de datos (encabezados + valores)
    valores_actualizar = [df_procesado.columns.tolist()] + df_procesado.fillna("").astype(str).values.tolist()
    
    sheet.update(range_name="A1", values=valores_actualizar)
    print("🚀 ¡Planilla 'Base Maestra Licitaciones y Compras Agiles' actualizada con éxito!")


if __name__ == "__main__":
    actualizar_google_sheets()
