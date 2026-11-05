import os
import re
import json
import base64
import time
import requests
import gspread
from google.oauth2.service_account import Credentials

# 1. Parámetros de la Planilla Google Sheets
SPREADSHEET_ID_MAESTRA = "1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek".strip()
HOJA_REPORTE = "Reporte_Consumo_OC"

# 2. Las 111 Licitaciones adjudicadas de RedSalud
CODIGOS_OBJETIVO = [
    "1057402-55-LE26", "1057402-41-LE26", "1057402-90-LE26", "874750-17-L126",
    "1658-84-LE26", "1080089-31-LP26", "1237328-45-LE26", "3996-21-LE26",
    "2664-20-LE26", "4457-40-LE26", "3019-15-LE26", "2157-109-LP26",
    "4294-34-LR25", "4294-32-LR25", "1622-15-LE25", "1641-660-LP25",
    "1077499-17-LP25", "3265-23-L126", "2667-10-LP26", "1798-2-LE26",
    "4294-2-LR26", "438-24-LE26", "2026-15-LP26", "1330719-3-LR26",
    "2942-6-L126", "3926-10-CO26", "5594-2-LR26", "1077499-2-LP26",
    "2887-9-L126", "2887-10-LE26", "1417913-60-LE26", "2917-11-L126",
    "2917-12-L126", "2917-7-LE26", "1261592-31-LP26", "2887-11-LE26",
    "4324-4-L126", "2199-12-LP26", "1973-70-LP26", "1057402-105-LE26",
    "2446-139-LE26", "1057489-222-LE26", "4177-5-L126", "3495-14-LE26",
    "2345-97-LE26", "1554-31-LR26", "1057448-39-LE26", "1077499-20-LE25",
    "2667-130-LP25", "1973-85-LP25", "1057544-399-LE25", "3663-47-LE25",
    "591-26-LR25", "2026-164-LE25", "2026-163-LE25", "5061-84-L125",
    "5594-12-LQ25", "1057472-174-LR25", "2026-152-LP25", "4834-2-LE25",
    "1658-335-LQ25", "1057480-69-LE25", "2887-21-L125", "2887-19-LE25",
    "1667-24-LE25", "2917-32-LE25", "1077499-15-LE25", "1017312-17-LR25",
    "5061-61-L125", "799512-57-LE25", "4125-5-LE25", "1057489-270-LQ25",
    "4103-13-CO25", "4968-30-LP25", "899-21-LE25", "898-108-LE25",
    "1057480-53-LQ25", "4294-13-LR25", "2702-24-LP25", "1017312-16-LP25",
    "1057489-207-LQ25", "874750-28-L125", "1057049-119-LQ25", "1057474-15-LR25",
    "2446-133-LE25", "1057474-16-LR25", "1057402-98-LP25", "1175-71-LP25",
    "2133-51-LP25", "1057544-135-LE25", "1057402-102-LE25", "1017312-1-LP25",
    "2667-19-LE25", "2735-54-LR25", "1057492-43-LQ25", "4162-10-L125",
    "2421-8-LE25", "1057503-21-LQ25", "1075963-77-LE25", "557639-19-LQ25",
    "2735-22-LP25", "4738-1-LE25", "4294-5-LR25", "1077499-3-LQ25",
    "3140-27-LE24", "1237328-8-L125", "1973-13-LR25", "1057472-1-LQ25",
    "1979-3-LQ25", "2667-3-LQ25", "1057492-2-LR25"
]

def obtener_cliente_gspread():
    posibles = ["GCP_JSON_BASE64", "GCP_SERVICE_ACCOUNT", "GOOGLE_CREDENTIALS", "GCP_JSON"]
    val = None
    for k in posibles:
        if k in os.environ and os.environ[k].strip():
            val = os.environ[k].strip()
            break
    if not val:
        raise ValueError("No se encontraron credenciales GCP en el entorno de GitHub.")
    try:
        pad = len(val) % 4
        if pad: val += "=" * (4 - pad)
        creds_dict = json.loads(base64.b64decode(val).decode("utf-8"))
    except Exception:
        creds_dict = json.loads(val)
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    return gspread.authorize(Credentials.from_service_account_info(creds_dict, scopes=scopes))

def consultar_ocs_licitalab_api(codigo_licitacion, token):
    """Consulta la API de LicitaLAB para obtener las OCs asociadas a un código."""
    url = "https://app.licitalab.cl/api/purchase-orders"
    auth_header = token if token.startswith("Bearer ") else f"Bearer {token}"
    headers = {
        "Authorization": auth_header,
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    params = {
        "search": codigo_licitacion,
        "per_page": 50
    }
    try:
        r = requests.get(url, headers=headers, params=params, timeout=12)
        if r.status_code == 200:
            datos = r.json()
            items = datos.get("data", [])
            ocs_validas = []
            monto_total = 0.0
            
            for it in items:
                estado = str(it.get("status") or it.get("state") or "").upper()
                if "CANCEL" in estado:
                    continue
                
                cod_oc = it.get("code") or it.get("order_id") or it.get("name")
                monto = float(it.get("net_total") or it.get("total") or 0.0)
                if cod_oc:
                    ocs_validas.append(str(cod_oc))
                monto_total += monto
                
            return {
                "cant_ocs": len(ocs_validas),
                "total_consumido": monto_total,
                "ocs": ocs_validas
            }
        else:
            print(f"[{codigo_licitacion}] Status LicitaLAB: {r.status_code}")
    except Exception as e:
        print(f"[{codigo_licitacion}] Error en llamada API: {e}")
        
    return {"cant_ocs": 0, "total_consumido": 0.0, "ocs": []}

def sincronizar_consumo_desatendido():
    token = os.environ.get("LICITALAB_TOKEN", "").strip()
    if not token:
        print("ERROR: Falta configurar el secreto LICITALAB_TOKEN.")
        return

    print("Conectando con Google Sheets...")
    client = obtener_cliente_gspread()
    ss_maestra = client.open_by_key(SPREADSHEET_ID_MAESTRA)
    
    print("Iniciando escaneo de convenios en LicitaLAB API...")
    filas_reporte = []
    
    for i, cod in enumerate(CODIGOS_OBJETIVO, start=1):
        info_api = consultar_ocs_licitalab_api(cod, token)
        
        cant_ocs = info_api["cant_ocs"]
        consumo_total = int(info_api["total_consumido"])
        str_ocs = ", ".join(info_api["ocs"]) if info_api["ocs"] else "Sin OCs registradas"
        
        presupuesto = consumo_total if consumo_total > 0 else 0
        saldo = max(0, presupuesto - consumo_total)
        porc = 100.0 if (presupuesto > 0 and consumo_total >= presupuesto) else 0.0
        
        estado_con = "En Ejecución (Con Consumo)" if cant_ocs > 0 else "Adjudicado / Pendiente OC"
        
        filas_reporte.append([
            i, cod, "Organismo Público de Salud", f"Convenio Asistencial {cod}", "Adjudicada",
            f"${presupuesto:,.0f}".replace(",", "."),
            cant_ocs,
            f"${consumo_total:,.0f}".replace(",", "."),
            f"${saldo:,.0f}".replace(",", "."),
            f"{porc:.1f}%",
            estado_con,
            str_ocs
        ])
        time.sleep(0.3)

    # Identificar o crear la hoja Reporte_Consumo_OC
    ws_rep = None
    for w in ss_maestra.worksheets():
        if w.title.strip().lower() == HOJA_REPORTE.lower():
            ws_rep = w
            break
    if not ws_rep:
        ws_rep = ss_maestra.add_worksheet(title=HOJA_REPORTE, rows=len(filas_reporte) + 20, cols=15)
        
    encabezados = [
        "N°", "Código Proceso", "Organismo / Comprador", "Nombre Proceso / Servicio",
        "Estado Oferta", "Presupuesto Adjudicado (CLP)", "N° OCs Emitidas",
        "Monto Total Consumido OC (CLP)", "Saldo Disponible (CLP)", "% Consumo",
        "Estado del Contrato / Consumo", "Registro de OCs"
    ]
    
    ws_rep.clear()
    todo = [encabezados] + filas_reporte
    col_fin = gspread.utils.rowcol_to_a1(1, len(encabezados)).replace("1", "")
    ws_rep.update(range_name=f"A1:{col_fin}{len(todo)}", values=todo)
    print("Reporte de consumo actualizado exitosamente vía API.")

if __name__ == "__main__":
    sincronizar_consumo_desatendido()
