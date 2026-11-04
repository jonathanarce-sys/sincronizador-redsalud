import os
import re
import json
import base64
import time
import requests
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 1. IDENTIFICADORES Y CONFIGURACIÓN
# ==========================================
SPREADSHEET_ID_MAESTRA = "1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek".strip()
HOJA_REPORTE = "Reporte_Consumo_OC"

LICITALAB_TOKEN = (
    os.environ.get("LICITALAB_TOKEN") or 
    os.environ.get("LICITALAB_API_KEY") or 
    os.environ.get("TOKEN_LICITALAB") or 
    ""
).strip()

TICKET_MERCADOPUBLICO = os.environ.get("MP_TICKET") or "F8537A18-6766-4DEF-9E59-426B4FEE5844"

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

TECHOS_CONTRATOS_AUDITADOS = {
    "1057402-55-LE26": {
        "organismo": "HOSPITAL CLINICO DR. LAUTARO NAVARRO AVARIA",
        "nombre": "PROCEDIMIENTOS, CIRUGIAS Y SALUD",
        "monto": 69500000,
        "consumo": 4092000,
        "ocs": ["1057402-1450-SE26"]
    }
}

def obtener_cliente_gspread():
    posibles = [
        "GCP_JSON_BASE64", "GCP_SERVICE_ACCOUNT", "GOOGLE_CREDENTIALS",
        "GCP_JSON", "GCP_SA_KEY", "GCP_CREDENTIALS"
    ]
    val = None
    for k in posibles:
        if k in os.environ and os.environ[k].strip():
            val = os.environ[k].strip()
            break
    if not val:
        for ek, ev in os.environ.items():
            if any(x in ek.upper() for x in ["GCP", "GOOGLE_CRED", "SERVICE_ACCOUNT"]) and ev.strip():
                val = ev.strip()
                break
    if not val:
        raise ValueError("Sin credenciales GCP en el entorno.")
    try:
        pad = len(val) % 4
        if pad:
            val += "=" * (4 - pad)
        dec = base64.b64decode(val)
        creds_dict = json.loads(dec.decode("utf-8"))
    except Exception:
        creds_dict = json.loads(val)
        
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    sa_email = creds_dict.get("client_email", "Email no identificado")
    client = gspread.authorize(Credentials.from_service_account_info(creds_dict, scopes=scopes))
    return client, sa_email

def escanear_hojas_locales(ss_maestra):
    """Indexa las pestañas de Google Sheets para cruzar OCs y datos existentes."""
    mapa = {}
    for ws in ss_maestra.worksheets():
        if ws.title.strip().lower() == HOJA_REPORTE.lower():
            continue
        try:
            filas = ws.get_all_values()
        except Exception:
            continue
        if not filas or len(filas) < 2:
            continue
            
        cab = [str(c).strip().upper() for c in filas[0]]
        idx_cod = -1
        idx_nom = -1
        idx_org = -1
        idx_mto = -1
        idx_oc = -1
        idx_oc_mto = -1
        
        for idx, c in enumerate(cab):
            if ("CÓDIGO" in c or "CODIGO" in c) and not any(x in c for x in ["OC", "CLIENTE", "PRESTADOR"]):
                if idx_cod == -1: idx_cod = idx
            elif "NOMBRE" in c and "PROCESO" in c:
                idx_nom = idx
            elif any(x in c for x in ["INSTITUCIÓN", "INSTITUCION", "COMPRADOR", "ORGANISMO"]):
                idx_org = idx
            elif any(x in c for x in ["MONTO", "PRESUPUESTO"]) and not any(x in c for x in ["OC", "UNITARIO"]):
                idx_mto = idx
            elif "CÓDIGO OC" in c or "CODIGO OC" in c:
                idx_oc = idx
            elif any(x in c for x in ["MONTO NETO OC", "MONTO BRUTO OC", "TOTAL OC", "VALOR OC"]):
                idx_oc_mto = idx

        for r in filas[1:]:
            c_val = ""
            if idx_cod != -1 and idx_cod < len(r) and r[idx_cod].strip():
                m = re.findall(r"\b\d{3,8}-\d{1,5}-[A-Za-z0-9]+\b", r[idx_cod])
                if m: c_val = m[0].upper()
            if not c_val:
                for celda in r[:4]:
                    m = re.findall(r"\b\d{3,8}-\d{1,5}-[A-Za-z0-9]+\b", str(celda))
                    if m:
                        c_val = m[0].upper()
                        break
            if not c_val:
                continue

            nom = r[idx_nom].strip() if idx_nom != -1 and idx_nom < len(r) else ""
            org = r[idx_org].strip() if idx_org != -1 and idx_org < len(r) else ""
            mto = r[idx_mto].strip() if idx_mto != -1 and idx_mto < len(r) else "0"
            oc_c = r[idx_oc].strip() if idx_oc != -1 and idx_oc < len(r) else ""
            oc_m = r[idx_oc_mto].strip() if idx_oc_mto != -1 and idx_oc_mto < len(r) else "0"

            if any(p in nom.upper() for p in ["ACEPTADA", "ENVIADA", "EVALUACIÓN", "EVALUACION", "MEDIATECA", "VINILOS"]):
                nom = ""

            if c_val not in mapa:
                mapa[c_val] = {"nombre": nom, "organismo": org, "monto": mto, "ocs": []}
            else:
                if nom and not mapa[c_val]["nombre"]: mapa[c_val]["nombre"] = nom
                if org and not mapa[c_val]["organismo"]: mapa[c_val]["organismo"] = org
                if mto and mto != "0" and mapa[c_val]["monto"] == "0": mapa[c_val]["monto"] = mto
                
            if oc_c:
                mapa[c_val]["ocs"].append({"codigo": oc_c, "monto": oc_m})
    return mapa

def consultar_licitalab_con_ordenes(codigo, idx_debug=0):
    """
    Consulta LicitaLAB con exploración profunda de endpoints de órdenes de compra (OC).
    """
    if not LICITALAB_TOKEN:
        return None, []
        
    headers = {
        "x-api-key": LICITALAB_TOKEN,
        "Accept": "application/json",
        "User-Agent": "RedSalud-Consumo/1.0"
    }

    item_opp = None
    lista_ocs = []

    # 1. Consultar Detalle Oportunidad
    try:
        url_det = f"https://biapi.licitalab.cl/bi/v2/opportunities/{codigo}"
        r = requests.get(url_det, headers=headers, timeout=8)
        if r.status_code == 200:
            d = r.json()
            cand = d.get("data") if isinstance(d, dict) and "data" in d else d
            if isinstance(cand, dict):
                cod_cand = str(cand.get("OPPORTUNITY_CODE") or cand.get("code") or "").strip().upper()
                if cod_cand == codigo.upper() or not cod_cand:
                    item_opp = cand
                    # Revisar si dentro del detalle ya vienen órdenes de compra
                    for k in ["purchase_orders", "orders", "purchaseOrders", "ordenes_compra", "awarded_orders"]:
                        if k in cand and isinstance(cand[k], list) and len(cand[k]) > 0:
                            lista_ocs.extend(cand[k])
        if idx_debug < 3:
            print(f"[DEBUG LicitaLAB Opp {codigo}] Status: {r.status_code}", flush=True)
    except Exception as e:
        if idx_debug < 3: print(f"[DEBUG Opp Error {codigo}]: {e}", flush=True)

    # 2. Consultar Endpoints de Purchase Orders con distintos nombres de parámetro
    if not lista_ocs:
        rutas_pos = [
            f"https://biapi.licitalab.cl/bi/v2/opportunities/{codigo}/purchase-orders",
            f"https://biapi.licitalab.cl/bi/v2/purchase-orders?opportunity_code={codigo}",
            f"https://biapi.licitalab.cl/bi/v2/purchase-orders?tender_code={codigo}",
            f"https://biapi.licitalab.cl/bi/v2/purchase-orders?opportunity={codigo}",
            f"https://biapi.licitalab.cl/bi/v2/purchase-orders?code={codigo}"
        ]
        
        for u in rutas_pos:
            try:
                r2 = requests.get(u, headers=headers, timeout=8)
                if idx_debug < 3:
                    print(f"[DEBUG LicitaLAB PO] URL: {u} -> Status: {r2.status_code}", flush=True)
                if r2.status_code == 200:
                    d2 = r2.json()
                    res = d2 if isinstance(d2, list) else (d2.get("data") or d2.get("purchase_orders") or [])
                    if isinstance(res, list) and len(res) > 0:
                        lista_ocs.extend(res)
                        if idx_debug < 3:
                            print(f"  -> Encontradas {len(res)} OCs en {u}", flush=True)
                        break
            except Exception:
                pass

    return item_opp, lista_ocs

def consultar_mercadopublico_api(codigo):
    """Consulta la API de Mercado Público para licitaciones exactas."""
    url = f"https://api.mercadopublico.cl/servicios/v1/publico/licitaciones.json?codigo={codigo}&ticket={TICKET_MERCADOPUBLICO}"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            d = r.json()
            listado = d.get("Listado") or []
            if isinstance(listado, list) and len(listado) > 0:
                return listado[0]
    except Exception:
        pass
    return None

def generar_reporte_consumo():
    print("=== MOTOR DE REPORTE DE CONSUMO Y OCs CON EXPLORACIÓN PROFUNDA ===", flush=True)

    try:
        client, sa_email = obtener_cliente_gspread()
        print(f"Autenticado en Google Sheets como: {sa_email}", flush=True)
        ss_maestra = client.open_by_key(SPREADSHEET_ID_MAESTRA)
    except Exception as e:
        print(f"Error conectando a Google Sheets: {repr(e)}", flush=True)
        return

    # 1. Escaneo de pestañas locales
    datos_locales = escanear_hojas_locales(ss_maestra)
    print(f"Licitaciones indexadas localmente en el archivo: {len(datos_locales)}", flush=True)

    encabezados = [
        "N°",
        "Código Proceso",
        "Organismo / Comprador",
        "Nombre Proceso / Servicio",
        "Estado Oferta",
        "Presupuesto Adjudicado (CLP)",
        "N° OCs Emitidas",
        "Monto Total Consumido OC (CLP)",
        "Saldo Disponible (CLP)",
        "% Consumo",
        "Estado del Consumo",
        "Códigos OC Asociados"
    ]

    filas_reporte = []

    print(f"\nProcesando {len(CODIGOS_OBJETIVO)} licitaciones...", flush=True)

    for i, cod in enumerate(CODIGOS_OBJETIVO, start=1):
        if cod in TECHOS_CONTRATOS_AUDITADOS:
            info_aud = TECHOS_CONTRATOS_AUDITADOS[cod]
            org = info_aud["organismo"]
            nom = info_aud["nombre"]
            presupuesto = info_aud["monto"]
            consumo_total = info_aud["consumo"]
            ocs_encontradas = info_aud["ocs"]
            est = "Adjudicada"
        else:
            # Consultar LicitaLAB con exploración de OCs
            info_api, ocs_api = consultar_licitalab_con_ordenes(cod, idx_debug=(i-1))
            info_mp = None
            if not info_api:
                info_mp = consultar_mercadopublico_api(cod)

            info_loc = datos_locales.get(cod, {})

            # Organismo
            org = ""
            if info_api: org = str(info_api.get("ORGANISM") or info_api.get("buyer") or "")
            if not org and info_mp: org = str(info_mp.get("Comprador", {}).get("NombreOrganismo") or "")
            if not org: org = info_loc.get("organismo", "")
            if not org: org = "Servicio de Salud / Hospital Público"

            # Nombre
            nom = ""
            if info_api: nom = str(info_api.get("OPPORTUNITY_NAME") or info_api.get("name") or "")
            if not nom and info_mp: nom = str(info_mp.get("Nombre") or "")
            if not nom: nom = info_loc.get("nombre", "")
            if not nom: nom = f"Convenio Asistencial {cod}"

            # Estado
            est = "Adjudicada"
            if info_api: est = str(info_api.get("OPPORTUNITY_STATUS") or est)
            elif info_mp: est = str(info_mp.get("Estado") or est)

            # Presupuesto Adjudicado
            monto_val = 0
            if info_api:
                for k in ["TOTAL_AWARDED_AMOUNT", "WON_AMOUNT", "AWARDED_AMOUNT", "AVAILABLE_AMOUNT"]:
                    v = info_api.get(k)
                    if v:
                        m_clean = re.sub(r"[^\d]", "", str(v))
                        if m_clean and int(m_clean) > 0:
                            monto_val = int(m_clean)
                            break
            if monto_val == 0 and info_mp:
                adj = info_mp.get("Adjudicacion")
                if isinstance(adj, dict):
                    for k in ["MontoTotal", "MontoAdjudicado", "ValorTotal"]:
                        v = adj.get(k)
                        if v:
                            m_clean = re.sub(r"[^\d]", "", str(v))
                            if m_clean and int(m_clean) > 0:
                                monto_val = int(m_clean)
                                break
                if monto_val == 0:
                    v = info_mp.get("MontoEstimado")
                    m_clean = re.sub(r"[^\d]", "", str(v or ""))
                    if m_clean: monto_val = int(m_clean)

            if monto_val == 0:
                m_loc = re.sub(r"[^\d]", "", str(info_loc.get("monto", "0")))
                if m_loc: monto_val = int(m_loc)

            presupuesto = monto_val

            # Consumo y OCs: combinar API + Datos locales de la hoja
            consumo_total = 0
            ocs_encontradas = []

            # 1. OCs desde la API
            for oc in ocs_api:
                c_oc = str(oc.get("code") or oc.get("ORDER_CODE") or oc.get("id") or "").strip()
                if c_oc and c_oc not in ocs_encontradas:
                    ocs_encontradas.append(c_oc)
                mto_oc = oc.get("total_amount") or oc.get("TOTAL_AMOUNT") or oc.get("amount") or oc.get("net_amount") or 0
                m_c = re.sub(r"[^\d]", "", str(mto_oc))
                if m_c: consumo_total += int(m_c)

            # 2. OCs desde las hojas locales si la API no devolvió
            if consumo_total == 0 and info_loc.get("ocs"):
                for oc_l in info_loc["ocs"]:
                    c_oc_l = oc_l.get("codigo", "").strip()
                    if c_oc_l and c_oc_l not in ocs_encontradas:
                        ocs_encontradas.append(c_oc_l)
                    m_c_l = re.sub(r"[^\d]", "", str(oc_l.get("monto", "0")))
                    if m_c_l: consumo_total += int(m_c_l)

        cant_ocs = len(ocs_encontradas)
        saldo = max(0, presupuesto - consumo_total)
        porc_consumo = round((consumo_total / presupuesto) * 100, 2) if presupuesto > 0 else 0.0

        if porc_consumo >= 100:
            estado_consumo = "100% Consumido (Completado)"
        elif porc_consumo >= 75:
            estado_consumo = "Consumo Alto (>75%)"
        elif porc_consumo >= 25:
            estado_consumo = "En Consumo Medio (25% - 75%)"
        elif porc_consumo > 0:
            estado_consumo = "En Consumo Inicial (<25%)"
        else:
            estado_consumo = "Sin Consumo (Pendiente OC)"

        str_ocs = ", ".join(ocs_encontradas) if ocs_encontradas else "Pendiente de Emisión"

        filas_reporte.append([
            i,
            cod,
            org,
            nom,
            est,
            f"${presupuesto:,.0f}".replace(",", "."),
            cant_ocs,
            f"${consumo_total:,.0f}".replace(",", "."),
            f"${saldo:,.0f}".replace(",", "."),
            f"{porc_consumo:.1f}%",
            estado_consumo,
            str_ocs
        ])

    # Guardar en pestaña 'Reporte_Consumo_OC'
    ws_reporte = None
    for ws in ss_maestra.worksheets():
        if ws.title.strip().lower() == HOJA_REPORTE.lower():
            ws_reporte = ws
            break

    if not ws_reporte:
        print(f"Creando pestaña '{HOJA_REPORTE}'...", flush=True)
        ws_reporte = ss_maestra.add_worksheet(title=HOJA_REPORTE, rows=len(filas_reporte) + 50, cols=15)

    ws_reporte.resize(rows=len(filas_reporte) + 20, cols=len(encabezados) + 2)
    ws_reporte.clear()

    todo = [encabezados] + filas_reporte
    col_fin = gspread.utils.rowcol_to_a1(1, len(encabezados)).replace("1", "")
    rango = f"A1:{col_fin}{len(todo)}"

    ws_reporte.update(range_name=rango, values=todo)
    print(f"\n=== Sincronización exitosa: {len(filas_reporte)} procesos actualizados en '{HOJA_REPORTE}' ===", flush=True)

if __name__ == "__main__":
    generar_reporte_consumo()
