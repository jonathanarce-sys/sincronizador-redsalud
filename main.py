import requests
import gspread
from google.oauth2.service_account import Credentials
import json
import os
import time

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
    print("Iniciando Descarga Multipágina de LicitaLAB BI (Carga Completa e Incremental)...")

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

    # 1. Obtenemos lo que ya existe en la planilla
    todas_las_filas = sheet.get_all_values()
    mapa_filas = {}
    if len(todas_las_filas) > 1:
        for idx, fila in enumerate(todas_las_filas[1:], start=2):
            if len(fila) > 1 and fila[1].strip():
                codigo_existente = fila[1].strip()
                mapa_filas[codigo_existente] = {
                    "num_fila": idx,
                    "datos": fila
                }

    print(f"Registros previos en Google Sheets: {len(mapa_filas)}")

    # 2. Bucle para recorrer TODAS las páginas de la API de LicitaLAB
    headers_api = {
        "x-api-key": LICITALAB_API_KEY,
        "Accept": "application/json"
    }

    page = 1
    max_pages = 20  # Permite traer hasta 20,000 registros históricos
    nuevas_filas = []
    actualizadas_cnt = 0

    while page <= max_pages:
        url = f"https://biapi.licitalab.cl/bi/v2/opportunities?page={page}"
        print(f"Consultando página {page}: {url}")
        try:
            res = requests.get(url, headers=headers_api)
            if res.status_code == 200:
                data = res.json()
                items = data.get("data", data) if isinstance(data, dict) else data
                
                if not isinstance(items, list) or len(items) == 0:
                    print(f"Página {page} vacía. Se alcanzó el final de los datos.")
                    break
                
                print(f"Página {page} recibida con {len(items)} registros.")
                
                for item in items:
                    fila_proc = procesar_item(item)
                    codigo_item = fila_proc[1]

                    if not codigo_item:
                        continue

                    if codigo_item in mapa_filas:
                        # Si existe, verificamos si requiere actualizar estado
                        num_fila = mapa_filas[codigo_item]["num_fila"]
                        datos_viejos = mapa_filas[codigo_item]["datos"]
                        if datos_viejos != fila_proc:
                            sheet.update(f"A{num_fila}:K{num_fila}", [fila_proc])
                            mapa_filas[codigo_item]["datos"] = fila_proc
                            actualizadas_cnt += 1
                    else:
                        nuevas_filas.append(fila_proc)
                        mapa_filas[codigo_item] = {"datos": fila_proc}

                page += 1
                time.sleep(0.5) # Pausa amigable para no saturar la API
            else:
                print(f"Fin de paginación o error HTTP {res.status_code} en página {page}")
                break
        except Exception as err:
            print(f"Excepción en página {page}: {err}")
            break

    # 3. Guardar todos los nuevos registros acumulados
    if nuevas_filas:
        print(f"Guardando {len(nuevas_filas)} registros históricos nuevos en Google Sheets...")
        # Insertar en bloques para evitar exceder límites de Google API
        chunk_size = 500
        for i in range(0, len(nuevas_filas), chunk_size):
            chunk = nuevas_filas[i:i + chunk_size]
            sheet.append_rows(chunk)
            time.sleep(1)
        print(f"¡ÉXITO TOTAL! Se agregaron {len(nuevas_filas)} nuevos registros a tu historial.")
    
    if actualizadas_cnt > 0:
        print(f"¡ÉXITO! Se actualizaron {actualizadas_cnt} registros existentes.")

    if not nuevas_filas and actualizadas_cnt == 0:
        print("Sincronización finalizada: Toda la base de datos está al día.")

if __name__ == "__main__":
    main()
