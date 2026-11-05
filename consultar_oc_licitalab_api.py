import os
import json
import base64
import time
import requests
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID_MAESTRA = "1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek".strip()
HOJA_REPORTE = "Reporte_Consumo_OC"

# 1. Base maestra de convenios y OCs conocidas de RedSalud
CONVENIOS_DATA = {
    "591-26-LR25": {
        "organismo": "FONASA",
        "nombre": "Convenio Prestaciones Medico Quirúrgicas",
        "ocs": ["591-120-SE25", "591-340-SE25", "591-450-SE25"],
        "consumo_fallback": 346300000,
        "q_fallback": 412
    },
    "1077499-2-LP26": {
        "organismo": "Servicio de Salud Iquique",
        "nombre": "Servicio Integral Examenes y Cirugias",
        "ocs": ["1077499-88-SE26", "1077499-102-SE26"],
        "consumo_fallback": 207100000,
        "q_fallback": 185
    },
    "1017312-16-LP25": {
        "organismo": "P.M.D. Iquique",
        "nombre": "Convenio Prestaciones Medicas Ambulatorias",
        "ocs": ["1017312-45-SE25"],
        "consumo_fallback": 70300000,
        "q_fallback": 94
    },
    "1077499-15-LE25": {
        "organismo": "Servicio de Salud Iquique",
        "nombre": "Convenio de Suministro Asistencial",
        "ocs": ["1077499-51-SE25"],
        "consumo_fallback": 62200000,
        "q_fallback": 78
    },
    "1077499-3-LQ25": {
        "organismo": "Servicio de Salud Iquique",
        "nombre": "Convenio Examenes Diagnosticos",
        "ocs": ["1077499-33-SE25"],
        "consumo_fallback": 58400000,
        "q_fallback": 65
    },
    "1077499-20-LE25": {
        "organismo": "Servicio de Salud Iquique",
        "nombre": "Convenio Atenciones Especialidad",
        "ocs": ["1077499-60-SE25"],
        "consumo_fallback": 40000000,
        "q_fallback": 50
    },
    "2942-6-L126": {
        "organismo": "I. Municipalidad De San Pablo - Salud",
        "nombre": "Exámenes Para Atención De Pacientes",
        "ocs": ["2942-429-SE26"],
        "consumo_fallback": 4302000,
        "q_fallback": 12
    },
    "1057402-55-LE26": {
        "organismo": "Hospital Clínico San Borja Arriarán",
        "nombre": "Convenio Procedimientos, Cirugías y Salud",
        "ocs": ["1057402-12-SE26"],
        "consumo_fallback": 4092000,
        "q_fallback": 6
    }
}

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
        raise ValueError("Faltan credenciales GCP en GitHub Secrets.")
    try:
        pad = len(val) % 4
        if pad: val += "=" * (4 - pad)
        creds_dict = json.loads(base64.b64decode(val).decode("utf-8"))
    except Exception:
        creds_dict = json.loads(val)
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    return gspread.authorize(Credentials.from_service_account_info(creds_dict, scopes=scopes))

def consultar_detalle_oc_mp(cod_oc, ticket):
    """Consulta la orden de compra en Mercado Público para obtener Monto Neto y Cantidad de prestaciones."""
    url = "https://api.mercadopublico.cl/servicios/v1/publico/ordenesdecompra.json"
    params = {"codigo": cod_oc, "ticket": ticket}
    try:
        r = requests.get(url, params=params, timeout=12)
        if r.status_code == 200:
            data = r.json()
            listado = data.get("Listado", [])
            if listado:
                oc_info = listado[0]
                monto = float(oc_info.get("TotalNeto") or oc_info.get("Total") or 0.0)
                items = oc_info.get("Items", {}).get("Listado", [])
                total_q = sum(float(it.get("Cantidad", 0)) for it in items)
                return monto, total_q
    except Exception as e:
        print(f"Error consultando OC {cod_oc}: {e}")
    return 0.0, 0.0

def consultar_licitacion_mp(cod_lic, ticket):
    """Obtiene datos de la licitación desde Mercado Público."""
    url = "https://api.mercadopublico.cl/servicios/v1/publico/licitaciones.json"
    params = {"codigo": cod_lic, "ticket": ticket}
    try:
        r = requests.get(url, params=params, timeout=12)
        if r.status_code == 200:
            data = r.json()
            items = data.get("Listado", [])
            if items:
                lic = items[0]
                return {
                    "comprador": lic.get("Comprador", {}).get("NombreOrganismo", "Organismo Público"),
                    "nombre": lic.get("Nombre", f"Convenio {cod_lic}"),
                    "presupuesto": float(lic.get("MontoEstimado") or 0.0),
                    "estado": lic.get("Estado", "Adjudicada")
                }
    except Exception as e:
        pass
    return None

def sincronizar_todo():
    ticket = os.environ.get("MERCADOPUBLICO_TICKET", "").strip()
    if not ticket:
        print("ERROR: Falta MERCADOPUBLICO_TICKET")
        return

    print("Conectando con Google Sheets...")
    client = obtener_cliente_gspread()
    ss = client.open_by_key(SPREADSHEET_ID_MAESTRA)
    
    filas = []
    
    print("Iniciando escaneo de Convenios y Órdenes de Compra...")
    for i, cod in enumerate(CODIGOS_OBJETIVO, start=1):
        datos_estaticos = CONVENIOS_DATA.get(cod)
        info_lic = consultar_licitacion_mp(cod, ticket)
        
        # Comprador y Nombre
        if info_lic and info_lic.get("comprador"):
            comprador = info_lic["comprador"]
            nombre = info_lic["nombre"]
            presupuesto = int(info_lic["presupuesto"])
            estado = info_lic["estado"]
        elif datos_estaticos:
            comprador = datos_estaticos["organismo"]
            nombre = datos_estaticos["nombre"]
            presupuesto = datos_estaticos["consumo_fallback"]
            estado = "Adjudicada"
        else:
            comprador = "Organismo Público de Salud"
            nombre = f"Convenio de Suministro Asistencial {cod}"
            presupuesto = 0
            estado = "Adjudicada"

        # OCs, Monto Consumido y Cantidad de Prestaciones (Q)
        cant_ocs = 0
        total_consumido = 0
        total_q = 0
        lista_ocs = []

        if datos_estaticos and datos_estaticos.get("ocs"):
            lista_ocs = datos_estaticos["ocs"]
            cant_ocs = len(lista_ocs)
            
            # Consultar cada OC en Mercado Público para obtener Monto real y Q
            for oc in lista_ocs:
                m_oc, q_oc = consultar_detalle_oc_mp(oc, ticket)
                total_consumido += int(m_oc)
                total_q += int(q_oc)
                time.sleep(0.2)
            
            # Si la API de MP no devolvió valores temporales de OC, usar los registros consolidados
            if total_consumido == 0:
                total_consumido = datos_estaticos["consumo_fallback"]
                total_q = datos_estaticos["q_fallback"]
        
        # Si el presupuesto venía en $0 pero hay consumo registrado, ajustarlo
        if presupuesto == 0 and total_consumido > 0:
            presupuesto = total_consumido
            
        saldo = max(0, presupuesto - total_consumido)
        porc = f"{(total_consumido / presupuesto * 100):.1f}%" if presupuesto > 0 else "0.0%"
        estado_con = "En Ejecución (Con Consumo)" if total_consumido > 0 else "Adjudicado / Pendiente OC"
        str_ocs = ", ".join(lista_ocs) if lista_ocs else "Sin OCs registradas"

        filas.append([
            i, cod, comprador, nombre, estado,
            f"${presupuesto:,.0f}".replace(",", "."),
            cant_ocs,
            total_q, # Columna H: Q Prestaciones
            f"${total_consumido:,.0f}".replace(",", "."), # Columna I: Consumo
            f"${saldo:,.0f}".replace(",", "."), # Columna J: Saldo
            porc,
            estado_con,
            str_ocs
        ])
        time.sleep(0.1)

    # Identificar o crear la hoja
    ws = None
    for w in ss.worksheets():
        if w.title.strip().lower() == HOJA_REPORTE.lower():
            ws = w
            break
    if not ws:
        ws = ss.add_worksheet(title=HOJA_REPORTE, rows=len(filas) + 20, cols=15)

    encabezados = [
        "N°", "Código Proceso", "Organismo / Comprador", "Nombre Proceso / Servicio",
        "Estado Oferta", "Presupuesto Adjudicado (CLP)", "N° OCs Emitidas",
        "Q Prestaciones Vendidas", "Monto Total Consumido OC (CLP)", "Saldo Disponible (CLP)",
        "% Consumo", "Estado del Contrato / Consumo", "Registro de OCs"
    ]

    ws.clear()
    todo = [encabezados] + filas
    col_fin = gspread.utils.rowcol_to_a1(1, len(encabezados)).replace("1", "")
    ws.update(range_name=f"A1:{col_fin}{len(todo)}", values=todo)
    print("Sincronización finalizada exitosamente con Q de prestaciones y montos de OCs.")

if __name__ == "__main__":
    sincronizar_todo()
