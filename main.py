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

def parsear_monto(val):
    if val is None or val == "" or str(val).upper() == "NONE":
        return ""
    try:
        num = float(val)
        return int(num) if num.is_integer() else num
    except:
        return str(val)

def parsear_lista_o_texto(val):
    if val is None or val == "" or str(val).upper() == "NONE":
        return ""
    if isinstance(val, list):
        return ", ".join([str(x) for x in val if x])
    val_str = str(val).strip()
    if val_str.startswith("["):
        try:
            parsed = json.loads(val_str)
            if isinstance(parsed, list):
                return ", ".join([str(x) for x in parsed if x])
        except:
            pass
    return val_str

def main():
    print("Iniciando sincronización completa de 11 columnas con LicitaLAB BI API...")

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

    url = "https://biapi.licitalab.cl/bi/v2/opportunities"
    headers = {
        "x-api-key": LICITALAB_API_KEY,
        "Accept": "application/json"
    }

    print(f"Consultando endpoint oficial: {url}")
    try:
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            data = res.json()
            items = data.get("data", data) if isinstance(data, dict) else data
            
            if isinstance(items, list) and len(items) > 0:
                filas_nuevas = []
                for item in items:
                    # Columna A: Fecha Publicación
                    fecha_raw = str(item.get("PUBLISH_DATE") or item.get("CREATED_AT") or "").strip()
                    fecha = fecha_raw.split("T")[0] if "T" in fecha_raw else fecha_raw

                    # Columna B: Código Proceso
                    codigo = str(item.get("OPPORTUNITY_CODE") or item.get("opportunity_code") or "").strip()

                    # Columna C: Tipo Proceso
                    tipo_orig = str(item.get("OPPORTUNITY_TYPE") or item.get("opportunity_type") or "").strip()
                    tipo = clasificar_tipo(tipo_orig, codigo)

                    # Columna D: Institución Compradora
                    comprador = str(item.get("ORGANISM") or item.get("organism") or "").strip()

                    # Columna E: Nombre Proceso
                    nombre = str(item.get("OPPORTUNITY_NAME") or item.get("opportunity_name") or "").strip()

                    # Columna F: Prestación (Categoría RedSalud)
                    prestacion = parsear_lista_o_texto(item.get("B_LINE_TITLE") or item.get("ORGANISM_CATEGORY"))

                    # Columna G: Monto Ofertado / Estimado (CLP)
                    monto_ofertado = parsear_monto(item.get("APPLIED_AMOUNT") or item.get("AVAILABLE_AMOUNT"))

                    # Columna H: Monto Total / Estimado (CLP)
                    monto_total = parsear_monto(item.get("TOTAL_AWARDED_AMOUNT") or item.get("AVAILABLE_AMOUNT"))

                    # Columna I: Estado de la Oferta
                    estado_oferta = str(item.get("OPPORTUNITY_STATUS") or item.get("MANAGED_STATUS_NAME") or "").strip()

                    # Columna J: Adjudicatario (Proveedor Ganador)
                    adjudicatario = parsear_lista_o_texto(item.get("AWARDED_PROVIDERS"))

                    # Columna K: Motivo de No Adjudicación (RedSalud)
                    motivo_no_adj = parsear_lista_o_texto(item.get("COMMENTS") or item.get("MANAGED_STATUS_NAME"))

                    filas_nuevas.append([
                        fecha,            # A
                        codigo,           # B
                        tipo,             # C
                        comprador,        # D
                        nombre,           # E
                        prestacion,       # F
                        monto_ofertado,   # G
                        monto_total,      # H
                        estado_oferta,    # I
                        adjudicatario,    # J
                        motivo_no_adj     # K
                    ])

                # Limpiar la hoja y reemplazar con las 11 columnas completas
                sheet.resize(rows=1)
                sheet.resize(rows=1000)
                sheet.append_rows(filas_nuevas)
                print(f"¡ÉXITO TOTAL! Se sincronizaron {len(filas_nuevas)} oportunidades con las 11 columnas (A-K) pobladas.")
            else:
                print("Conexión exitosa: No hay oportunidades en LicitaLAB actualmente.")
        else:
            print(f"Error devuelto por LicitaLAB API: {res.status_code} - {res.text}")
    except Exception as err:
        print(f"Excepción al procesar datos: {err}")

if __name__ == "__main__":
    main()
