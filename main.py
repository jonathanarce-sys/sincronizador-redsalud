import os
import json
import base64
import sys
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek"

def log(msg):
    print(msg, flush=True)

def obtener_credenciales_google():
    log("🔑 Cargando credenciales de Google...")
    gcp_secret = os.getenv("GCP_JSON_BASE64", "").strip() or os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip()

    if not gcp_secret:
        raise ValueError("❌ No se encontraron credenciales en GCP_JSON_BASE64 ni en GOOGLE_CREDENTIALS_JSON.")

    try:
        creds_dict = json.loads(gcp_secret, strict=False)
        log("✅ Credenciales leídas como JSON directo.")
    except Exception:
        try:
            missing_padding = len(gcp_secret) % 4
            if missing_padding != 0:
                gcp_secret += '=' * (4 - missing_padding)
            json_bytes = base64.b64decode(gcp_secret)
            creds_dict = json.loads(json_bytes.decode("utf-8"))
            log("✅ Credenciales leídas como Base64.")
        except Exception as e:
            raise ValueError(f"❌ Error al decodificar credenciales: {e}")

    if "private_key" in creds_dict:
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    return Credentials.from_service_account_info(creds_dict, scopes=scopes)

def procesar_y_reestructurar_columnas(df: pd.DataFrame) -> pd.DataFrame:
    """Asegura la presencia y orden de Fecha de Cierre, Comentarios y Workspace."""
    
    # 1. Eliminar Criterios de Evaluación y Puntajes
    cols_eliminar = [c for c in df.columns if "criterio" in c.lower() or "evaluaci" in c.lower() or "puntaje" in c.lower()]
    if cols_eliminar:
        log(f"🗑️ Eliminando columnas obsoletas: {cols_eliminar}")
        df = df.drop(columns=cols_eliminar, errors="ignore")

    # 2. Filtrar fechas 2025+
    col_inicio = next((c for c in df.columns if "publica" in c.lower() or "inicio" in c.lower() or "creaci" in c.lower()), None)
    if col_inicio:
        df[col_inicio] = pd.to_datetime(df[col_inicio], errors="coerce", dayfirst=True)
        df = df[df[col_inicio].dt.year >= 2025]
        df[col_inicio] = df[col_inicio].dt.strftime("%Y-%m-%d")
        log(f"📅 Registros conservados (Año 2025+): {len(df)}")

    # 3. Crear 'Fecha de Cierre' si no existe o mapearla desde LicitaLAB
    col_cierre = next((c for c in df.columns if "cierre" in c.lower() or "termino" in c.lower() or "limite" in c.lower() or "postulaci" in c.lower()), None)
    if not col_cierre or col_cierre not in df.columns:
        df["Fecha de Cierre"] = "Pendiente / Sin fecha"
        log("➕ Creando encabezado: Fecha de Cierre")
    else:
        df.rename(columns={col_cierre: "Fecha de Cierre"}, inplace=True)

    # 4. Crear 'Comentarios' si no existe
    col_comentarios = next((c for c in df.columns if "comentario" in c.lower() or "observaci" in c.lower() or "nota" in c.lower()), None)
    if not col_comentarios or col_comentarios not in df.columns:
        df["Comentarios"] = ""
        log("➕ Creando encabezado: Comentarios")
    else:
        df.rename(columns={col_comentarios: "Comentarios"}, inplace=True)

    # 5. Crear 'Workspace' si no existe
    col_ws = next((c for c in df.columns if "workspace" in c.lower() or "equipo" in c.lower() or "espacio" in c.lower()), None)
    if not col_ws or col_ws not in df.columns:
        df["Workspace"] = "General RedSalud"
        log("➕ Creando encabezado: Workspace")
    else:
        df.rename(columns={col_ws: "Workspace"}, inplace=True)

    # 6. Calcular 'Monto Total + IVA (Adjudicado / Estimado)'
    col_monto = next((c for c in df.columns if "monto" in c.lower() or "estimado" in c.lower() or "total" in c.lower()), None)
    def calc_iva(val):
        try:
            v = float(str(val).replace("$", "").replace(".", "").replace(",", ".").strip())
            return f"$ {int(v * 1.19):,}".replace(",", ".")
        except Exception:
            return "$ 0"

    if col_monto:
        df["Monto Total + IVA (Adjudicado / Estimado)"] = df[col_monto].apply(calc_iva)

    # 7. Definir orden oficial de la Base Maestra
    columnas_ordenadas = [
        "Fecha Publicación",
        "Fecha de Cierre",
        "Código Proceso",
        "Tipo Proceso",
        "Institución Compradora",
        "Nombre Proceso",
        "Prestación (Categoría RedSalud)",
        "Monto Ofertado / Estimado (CLP)",
        "Monto Total + IVA (Adjudicado / Estimado)",
        "Estado de la Oferta",
        "Workspace",
        "Adjudicatario (Proveedor Ganador)",
        "Motivo de No Adjudicación (RedSalud)",
        "Comentarios"
    ]

    # Mantener columnas adicionales que pudiesen existir
    cols_finales = [c for c in columnas_ordenadas if c in df.columns] + \
                   [c for c in df.columns if c not in columnas_ordenadas]

    return df[cols_finales]

def sincronizar():
    log("🔄 Iniciando sincronización de Base Maestra...")
    creds = obtener_credenciales_google()
    client = gspread.authorize(creds)

    log(f"📄 Conectando a la planilla ID: {SPREADSHEET_ID}")
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1

    raw_records = sheet.get_all_records()
    df_existente = pd.DataFrame(raw_records)

    if df_existente.empty:
        log("⚠️ La planilla está vacía actualmente.")
        return

    log(f"📊 Total de registros leídos: {len(df_existente)}")

    df_actualizado = procesar_y_reestructurar_columnas(df_existente)

    log("🧹 Limpiando contenido antiguo de la hoja...")
    sheet.clear()

    log("📝 Escribiendo los datos con los nuevos encabezados (Fecha de Cierre, Workspace, Comentarios)...")
    valores = [df_actualizado.columns.tolist()] + df_actualizado.fillna("").astype(str).values.tolist()
    sheet.update(range_name="A1", values=valores)

    log("🚀 ¡Base Maestra reestructurada y actualizada exitosamente!")

if __name__ == "__main__":
    sincronizar()
