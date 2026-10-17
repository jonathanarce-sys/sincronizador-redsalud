import requests
import gspread
from google.oauth2.service_account import Credentials
import json
import os

LICITALAB_API_KEY = "llab_live_kxaJvD38lM1h8Qj11SVe6P18cZ-nEp2lMsECS5_THoE"
SPREADSHEET_ID = "1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek"

def clasificar_tipo(tipo_raw, code_raw):
    code_upper = str(code_raw).upper()
    tipo_upper = str(tipo_raw).upper()

    if "COT" in code_upper or "AGILE" in tipo_upper or "COMPRA ÁGIL" in tipo_upper:
        return "Compra Ágil"
    elif "CO" in code_upper or "PRIVATE" in tipo_upper:
        return "Licitación Privada"
    return "Licitación Pública"

def formatear_moneda(val):
    if val is None or val == "" or str(val).upper() == "NONE":
        return "$ 0"
    try:
        monto = int(float(val))
        return f"$ {monto:,}".replace(",", ".")
    except:
        return str(val)

def limpiar_texto_o_lista(val):
    if val is None or val == "" or str(val).upper() == "NONE":
        return ""
    if isinstance(val, list):
        items_limpios = [str(x).strip(" []'\"") for x in val if x]
        return ", ".join(items_limpios)
    
    val_str = str(val).strip()
    if val_str.startswith("[") and val_str.endswith("]"):
        try:
            parsed = json.loads(val_str)
            if isinstance(parsed, list):
                items_limpios = [str(x).strip(" []'\"") for x in parsed if x]
                return ", ".join(items_limpios)
        except:
            pass
    return val_str.strip(" []'\"")

def procesar_item(item):
    """Extrae y formatea las 11 columnas a partir de un item de LicitaLAB."""
    fecha_raw = str(item.get("PUBLISH_DATE") or item.get("CREATED_AT") or "").strip()
    fecha = fecha_raw.split("T")[0] if "T" in fecha_raw else fecha_raw

    codigo = str(item.get("OPPORTUNITY_CODE") or item.get("opportunity_code") or "").strip()
    tipo_orig = str(item.get("OPPORTUNITY_TYPE") or item.get("opportunity_type") or "").strip()
    tipo = clasificar_tipo(tipo_orig, codigo)

    comprador = str(item.get("ORGANISM") or item.get("organism") or "").strip()
    nombre = str(item.get("OPPORTUNITY_NAME") or item.get("opportunity_name") or "").strip()
    prestacion = limpiar_texto_o_lista(item.get("B_LINE_TITLE") or item.get("ORGANISM_CATEGORY"))

    monto_ofertado = formatear_moneda(item.get("APPLIED_AMOUNT") or item.get("AVAILABLE_AMOUNT"))
    monto_total = formatear_moneda(item.get("TOTAL_AWARDED_AMOUNT") or item.get("AVAILABLE_AMOUNT"))
    estado_oferta = str(item.get("OPPORTUNITY_STATUS") or item.get("MANAGED_STATUS_NAME") or "").strip()
    adjudicatario = limpiar_texto_o_lista(item.get("AWARDED_PROVIDERS"))
    motivo_no_adj = limpiar_texto_o_lista(item.get("COMMENTS") or item.get("MANAGED_STATUS_NAME"))

    return [
        fecha, codigo, tipo, comprador, nombre,
        prestacion, monto_ofertado, monto_total,
        estado_oferta, adjudicatario, motivo_no_adj
    ]

def main():
    print("Iniciando Sincronización Incremental (Historización sin Duplicados)...")

    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        try:
            creds_dict = json.loads(creds_json)
            scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
            creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
            client = gspread.authorize(creds)
        except Exception as e:
            print(f"Error al autenticar credenciales de Google: {e}")
            return
    else:
        print("Error: No se encontraron credenciales en GOOGLE_CREDENTIALS_JSON")
        return

    try:
        sheet = client.open_by_key(SPREADSHEET_ID).sheet1
        print("¡Conexión exitosa con Google Sheets!")
    except Exception as e:
        print(f"Error al abrir la planilla de Google Sheets: {e}")
        return

    # 1. Leer datos existentes en Google Sheets
    todas_las_filas = sheet.get_all_values()
    
    headers = [
        "Fecha Publicación", "Código Proceso", "Tipo Proceso", 
        "Institución Compradora", "Nombre Proceso", "Prestación (Categoría RedSalud)",
        "Monto Ofertado / Estimado (CLP)", "Monto Total / Estimado (CLP)",
        "Estado de la Oferta", "Adjudicatario (Proveedor Ganador)", "Motivo de No Adjudicación (RedSalud)"
    ]

    # Mapeo de filas por Código Proceso (Columna B / Índice 1)
    mapa_filas = {}
    if len(todas_las_filas) > 1:
        for idx, fila in enumerate(todas_las_filas[1:], start=2):
            if len(fila) > 1 and fila[1].strip():
                codigo_existente = fila[1].strip()
                mapa_filas[codigo_existente] = {
                    "num_fila": idx,
                    "datos": fila
                }

    print(f"Registros existentes en Google Sheets: {len(mapa_filas)}")

    # 2. Consultar LicitaLAB BI API
    url = "https://biapi.licitalab.cl/bi/v2/opportunities"
    headers_api = {
        "x-api-key": LICITALAB_API_KEY,
        "Accept": "application/json"
    }

    try:
        res = requests.get(url, headers=headers_api)
        if res.status_code == 200:
            data = res.json()
            items = data.get("data", data) if isinstance(data, dict) else data
            
            if isinstance(items, list) and len(items) > 0:
                nuevas_filas = []
                actualizadas_cnt = 0

                for item in items:
                    fila_procesada = procesar_item(item)
                    codigo_item = fila_procesada[1]

                    if not codigo_item:
                        continue

                    # Si el código ya existe en la hoja, verificamos si cambió de estado o monto
                    if codigo_item in mapa_filas:
                        num_fila = mapa_filas[codigo_item]["num_fila"]
                        datos_viejos = mapa_filas[codigo_item]["datos"]

                        # Si hay cambios en los datos, actualizamos esa fila específica
                        if datos_viejos != fila_procesada:
                            sheet.update(f"A{num_fila}:K{num_fila}", [fila_procesada])
                            mapa_filas[codigo_item]["datos"] = fila_procesada
                            actualizadas_cnt += 1
                    else:
                        # Si es una licitación/compra ágil totalmente nueva, la guardamos para agregarla al final
                        nuevas_filas.append(fila_procesada)
                        mapa_filas[codigo_item] = {"datos": fila_procesada}

                # Agregar únicamente las filas nuevas al final de la planilla
                if nuevas_filas:
                    sheet.append_rows(nuevas_filas)
                    print(f"¡Éxito! Se agregaron {len(nuevas_filas)} nuevos registros a la base de datos.")
                
                if actualizadas_cnt > 0:
                    print(f"¡Éxito! Se actualizaron los estados de {actualizadas_cnt} registros existentes.")

                if not nuevas_filas and actualizadas_cnt == 0:
                    print("Sincronización finalizada: No hubo cambios de estado ni registros nuevos en este ciclo.")

            else:
                print("No se encontraron elementos en LicitaLAB.")
        else:
            print(f"Error HTTP {res.status_code}: {res.text}")
    except Exception as err:
        print(f"Excepción durante la sincronización incremental: {err}")

if __name__ == "__main__":
    main()
