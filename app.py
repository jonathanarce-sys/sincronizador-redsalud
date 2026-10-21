import streamlit as st
import requests
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import base64
import json

# Configuración ejecutiva de página
st.set_page_config(
    page_title="Calculadora Comercial & Inteligencia de Competencia - RedSalud",
    layout="wide",
    page_icon="🧮"
)

# Estilos CSS personalizados
st.markdown("""
    <style>
    .kpi-card {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 16px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.04);
        margin-bottom: 12px;
    }
    .kpi-title {
        font-size: 0.82rem;
        color: #64748b;
        font-weight: 600;
        text-transform: uppercase;
        margin-bottom: 6px;
    }
    .kpi-value {
        font-size: 1.2rem;
        color: #0f172a;
        font-weight: 700;
        word-wrap: break-word;
        white-space: normal;
    }
    .reason-box-green {
        background-color: #f0fdf4;
        border-left: 4px solid #16a34a;
        padding: 14px;
        border-radius: 6px;
        margin-bottom: 12px;
    }
    .reason-box-blue {
        background-color: #eff6ff;
        border-left: 4px solid #2563eb;
        padding: 14px;
        border-radius: 6px;
        margin-bottom: 12px;
    }
    .advantage-badge {
        background-color: #f1f5f9;
        color: #334155;
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 0.85rem;
        font-weight: 600;
        display: inline-block;
        margin-right: 6px;
        margin-bottom: 6px;
    }
    </style>
""", unsafe_allow_html=True)

st.title("🧮 Calculadora Comercial y Simulador de Ofertas - RedSalud")
st.markdown("Herramienta de inteligencia comercial conectada a **LicitaLAB BI API / Base Maestra**.")

LICITALAB_API_KEY = st.secrets.get("LICITALAB_API_KEY", "llab_live_kxaJvD38lM1h8Qj11SVe6P18cZ-nEp2lMsECS5_THoE").strip()
URL_API_LICITALAB = "https://biapi.licitalab.cl/bi/v2/opportunities"
MERCADO_PUBLICO_TICKET = "F8537A18-6766-4DEF-9E59-4F1F06B4C236"
SPREADSHEET_ID = "1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek"

def limpiar_texto(val, fallback="No registrado"):
    if val is None or pd.isna(val):
        return fallback
    s = str(val).strip()
    if s.lower() in ["nan", "none", "null", "[]", ""]:
        return fallback
    return s.strip(" []'\"")

def limpiar_monto_a_float(val) -> float:
    if val is None or pd.isna(val):
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    try:
        val_str = str(val).replace("$", "").replace(".", "").replace(",", ".").replace("CLP", "").strip()
        return float(val_str)
    except Exception:
        return 0.0

def formatear_moneda(val):
    try:
        monto_num = limpiar_monto_a_float(val)
        monto_int = int(round(monto_num))
        return f"$ {monto_int:,}".replace(",", ".")
    except Exception:
        return "$ 0"

def clasificar_tipo_label(tipo_raw, code_raw):
    code_upper = str(code_raw).upper()
    tipo_upper = str(tipo_raw).upper()
    if "COT" in code_upper or "AGILE" in tipo_upper or "COMPRA ÁGIL" in tipo_upper:
        return "Compra Ágil"
    elif "CO" in code_upper or "PRIVATE" in tipo_upper:
        return "Licitación Privada"
    return "Licitación Pública"

def detectar_region_por_organismo(organismo, region_raw):
    reg_limpia = limpiar_texto(region_raw, fallback="")
    if reg_limpia and reg_limpia not in ["No registrado", "Sin información", "RM"]:
        return reg_limpia

    org_upper = str(organismo).upper()
    if any(k in org_upper for k in ["BULNES", "YUNGAY", "CHILLÁN", "CHILLAN", "SAN CARLOS", "ÑUBLE"]):
        return "Región del Ñuble"
    elif any(k in org_upper for k in ["CHÉPICA", "CHEPICA", "SAN FERNANDO", "RANCAGUA", "O'HIGGINS"]):
        return "Región del Libertador General Bernardo O'Higgins"
    elif any(k in org_upper for k in ["SAN PEDRO DE ATACAMA", "ANTOFAGASTA", "CALAMA"]):
        return "Región de Antofagasta"
    elif any(k in org_upper for k in ["IQUIQUE", "ALTO HOSPICIO", "TARAPACÁ"]):
        return "Región de Tarapacá"
    elif any(k in org_upper for k in ["VALPARAÍSO", "VALPARAISO", "VIÑA"]):
        return "Región de Valparaíso"
    elif any(k in org_upper for k in ["FRUTILLAR", "PUERTO MONTT", "OSORNO"]):
        return "Región de Los Lagos"

    return "Región Metropolitana"

@st.cache_data(ttl=900)
def cargar_datos_iniciales():
    headers = {"x-api-key": LICITALAB_API_KEY, "Accept": "application/json"}
    todos_items = []
    try:
        res = requests.get(f"{URL_API_LICITALAB}?page=1", headers=headers, timeout=6)
        if res.status_code == 200:
            data = res.json()
            items = data.get("data", data) if isinstance(data, dict) else data
            if isinstance(items, list) and len(items) > 0:
                todos_items.extend(items)
    except Exception:
        pass

    if todos_items:
        df = pd.DataFrame(todos_items)
        df["_origen"] = "API LicitaLAB BI (En Vivo)"
        return df

    try:
        creds_dict = None
        if "GCP_JSON_BASE64" in st.secrets:
            b64_str = st.secrets["GCP_JSON_BASE64"]
            json_bytes = base64.b64decode(b64_str)
            creds_dict = json.loads(json_bytes.decode("utf-8"))
        elif "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
            if "private_key" in creds_dict:
                creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

        if creds_dict:
            scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
            creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
            client = gspread.authorize(creds)
            sheet = client.open_by_key(SPREADSHEET_ID).sheet1
            records = sheet.get_all_records()
            df_sheet = pd.DataFrame(records)
            
            df_sheet["OPPORTUNITY_CODE"] = df_sheet["Código Proceso"] if "Código Proceso" in df_sheet.columns else df_sheet.iloc[:, 1]
            df_sheet["OPPORTUNITY_NAME"] = df_sheet["Nombre Proceso"] if "Nombre Proceso" in df_sheet.columns else df_sheet.iloc[:, 4]
            df_sheet["ORGANISM"] = df_sheet["Institución Compradora"] if "Institución Compradora" in df_sheet.columns else df_sheet.iloc[:, 3]
            df_sheet["PUBLISH_DATE"] = df_sheet["Fecha Publicación"] if "Fecha Publicación" in df_sheet.columns else ""
            df_sheet["CLOSING_DATE"] = df_sheet["Fecha de Cierre"] if "Fecha de Cierre" in df_sheet.columns else ""
            df_sheet["OPPORTUNITY_STATUS"] = df_sheet["Estado de la Oferta"] if "Estado de la Oferta" in df_sheet.columns else "Publicada"
            df_sheet["AVAILABLE_AMOUNT"] = df_sheet["Monto Total + IVA (Adjudicado / Estimado)"] if "Monto Total + IVA (Adjudicado / Estimado)" in df_sheet.columns else 0
            df_sheet["_origen"] = "Base Maestra Respaldada (Google Sheets)"
            return df_sheet
    except Exception:
        pass

    return pd.DataFrame()

def buscar_codigo_en_apis_externas(codigo_target):
    """Búsqueda directa por código en LicitaLAB API, Google Sheets o Mercado Público."""
    headers = {"x-api-key": LICITALAB_API_KEY, "Accept": "application/json"}
    
    # 1. LicitaLAB API por código
    try:
        res = requests.get(f"{URL_API_LICITALAB}?code={codigo_target}", headers=headers, timeout=6)
        if res.status_code == 200:
            data = res.json()
            items = data.get("data", data) if isinstance(data, dict) else data
            if isinstance(items, list) and len(items) > 0:
                df = pd.DataFrame(items)
                df["_origen"] = "Búsqueda Directa API LicitaLAB"
                return df
    except Exception:
        pass

    # 2. Búsqueda en Google Sheets Base Maestra
    try:
        creds_dict = None
        if "GCP_JSON_BASE64" in st.secrets:
            b64_str = st.secrets["GCP_JSON_BASE64"]
            json_bytes = base64.b64decode(b64_str)
            creds_dict = json.loads(json_bytes.decode("utf-8"))
        if creds_dict:
            scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
            creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
            client = gspread.authorize(creds)
            sheet = client.open_by_key(SPREADSHEET_ID).sheet1
            records = sheet.get_all_records()
            df_sheet = pd.DataFrame(records)
            df_match = df_sheet[df_sheet["Código Proceso"].astype(str).str.contains(codigo_target, case=False, na=False)] if "Código Proceso" in df_sheet.columns else pd.DataFrame()
            if not df_match.empty:
                df_match["OPPORTUNITY_CODE"] = df_match["Código Proceso"]
                df_match["OPPORTUNITY_NAME"] = df_match["Nombre Proceso"]
                df_match["ORGANISM"] = df_match["Institución Compradora"]
                df_match["_origen"] = "Base Maestra (Google Sheets)"
                return df_match
    except Exception:
        pass

    # 3. Mercado Público API
    try:
        url_mp = f"https://api.mercadopublico.cl/servicios/v1/Publico/Licitaciones.json?codigo={codigo_target}&ticket={MERCADO_PUBLICO_TICKET}"
        res = requests.get(url_mp, timeout=6)
        if res.status_code == 200:
            data = res.json()
            listado = data.get("Listado", [])
            if listado:
                it = listado[0]
                item_mapped = {
                    "OPPORTUNITY_CODE": it.get("CodigoExterno", codigo_target),
                    "OPPORTUNITY_NAME": it.get("Nombre", "Proceso de Mercado Público"),
                    "ORGANISM": it.get("Comprador", {}).get("NombreOrganismo", "Institución Pública"),
                    "PUBLISH_DATE": (it.get("Fechas", {}).get("FechaCreacion") or "").split("T")[0],
                    "CLOSING_DATE": (it.get("Fechas", {}).get("FechaCierre") or "").split("T")[0],
                    "OPPORTUNITY_STATUS": it.get("Estado", "Publicada"),
                    "AVAILABLE_AMOUNT": it.get("MontoEstimado", 0),
                    "REGION": it.get("Comprador", {}).get("RegionComprador", ""),
                    "_origen": "API Oficial Mercado Público"
                }
                return pd.DataFrame([item_mapped])
    except Exception:
        pass

    return pd.DataFrame()

# Carga inicial
with st.spinner("Conectando con la base de datos de oportunidades..."):
    df_api = cargar_datos_iniciales()

# ==========================================
# 🔍 BUSCADOR MULTICAPA
# ==========================================
st.markdown("---")
st.subheader("🔎 Buscador y Selección de Oportunidad")

col_busqueda, col_filtro_tipo = st.columns([2.5, 1.5])

codigo_ingresado = col_busqueda.text_input(
    "Ingresa o busca por Código de Proceso:",
    value="2963-26-LR26",
    placeholder="Ej: 2963-26-LR26, 3904-939-COT26, 1380-5003-COT26..."
).strip()

df_filtrado = pd.DataFrame()

if not df_api.empty:
    col_code = "OPPORTUNITY_CODE" if "OPPORTUNITY_CODE" in df_api.columns else "Código Proceso"
    if codigo_ingresado:
        df_filtrado = df_api[df_api[col_code].astype(str).str.contains(codigo_ingresado, case=False, na=False)]

if codigo_ingresado and df_filtrado.empty:
    with st.spinner(f"Consultando directamente el código {codigo_ingresado}..."):
        df_filtrado = buscar_codigo_en_apis_externas(codigo_ingresado)

if not df_api.empty and not codigo_ingresado:
    df_filtrado = df_api

if df_filtrado.empty:
    st.warning(f"⚠️ No se encontraron procesos para el código ingresado: **'{codigo_ingresado}'**.")
else:
    origen_txt = df_filtrado["_origen"].iloc[0] if "_origen" in df_filtrado.columns else "API Directa"
    st.success(f" Oportunidad localizada vía **{origen_txt}**.")

    col_code = "OPPORTUNITY_CODE" if "OPPORTUNITY_CODE" in df_filtrado.columns else "Código Proceso"
    col_name = "OPPORTUNITY_NAME" if "OPPORTUNITY_NAME" in df_filtrado.columns else "Nombre Proceso"
    col_tip = "OPPORTUNITY_TYPE" if "OPPORTUNITY_TYPE" in df_filtrado.columns else "Tipo Proceso"

    lista_opciones = []
    mapa_opciones = {}
    for idx, row in df_filtrado.iterrows():
        code_val = row.get(col_code, 'S/C')
        type_val = clasificar_tipo_label(row.get(col_tip, ''), code_val)
        name_val = row.get(col_name, 'Sin nombre')
        
        lbl = f"[{code_val}] ({type_val}) - {name_val}"
        lista_opciones.append(lbl)
        mapa_opciones[lbl] = row

    proceso_sel = st.selectbox("Selecciona el proceso a analizar:", lista_opciones)
    item = mapa_opciones[proceso_sel]

    # ==========================================
    # 📌 ANÁLISIS COMERCIAL Y TERRITORIAL
    # ==========================================
    st.markdown("---")
    st.subheader("📍 Análisis Comercial y Territorial del Proceso")

    val_code = limpiar_texto(item.get(col_code))
    val_pub = limpiar_texto(item.get("PUBLISH_DATE") or item.get("CREATED_AT") or item.get("Fecha Publicación")).split("T")[0]
    val_cierre = limpiar_texto(item.get("CLOSING_DATE") or item.get("Fecha de Cierre")).split("T")[0] if limpiar_texto(item.get("CLOSING_DATE") or item.get("Fecha de Cierre")) != "No registrado" else "N/A"
    val_estado = limpiar_texto(item.get("OPPORTUNITY_STATUS") or item.get("MANAGED_STATUS_NAME") or item.get("Estado de la Oferta"), fallback="Publicada")
    val_tipo_proceso = clasificar_tipo_label(item.get(col_tip, ''), val_code)

    val_comprador = limpiar_texto(item.get("ORGANISM") or item.get("organism") or item.get("Institución Compradora"))
    val_region = detectar_region_por_organismo(val_comprador, item.get("REGION") or item.get("Región / Territorio"))

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f'<div class="kpi-card"><div class="kpi-title">Código Proceso ({val_tipo_proceso})</div><div class="kpi-value">{val_code}</div></div>', unsafe_allow_html=True)
    with c2:
        st.markdown(f'<div class="kpi-card"><div class="kpi-title">Fecha de Publicación</div><div class="kpi-value">{val_pub}</div></div>', unsafe_allow_html=True)
    with c3:
        st.markdown(f'<div class="kpi-card"><div class="kpi-title">Fecha de Cierre</div><div class="kpi-value">{val_cierre}</div></div>', unsafe_allow_html=True)
    with c4:
        st.markdown(f'<div class="kpi-card"><div class="kpi-title">Estado Oferta</div><div class="kpi-value">{val_estado}</div></div>', unsafe_allow_html=True)

    st.markdown("##### 🏛️ Territorio y Comprador")
    t1, t2 = st.columns(2)
    with t1:
        st.markdown(f'<div class="kpi-card"><div class="kpi-title">Región / Territorio</div><div class="kpi-value">{val_region}</div></div>', unsafe_allow_html=True)
    with t2:
        st.markdown(f'<div class="kpi-card"><div class="kpi-title">Institución Compradora</div><div class="kpi-value">{val_comprador}</div></div>', unsafe_allow_html=True)

    # ==========================================
    # 🏢 MÓDULO DE COMPETENCIA
    # ==========================================
    st.markdown("---")
    st.subheader("🏢 Análisis de Competencia e Historia de Adjudicación")

    col_org = "ORGANISM" if "ORGANISM" in df_filtrado.columns else "Institución Compradora"
    df_competencia = df_filtrado[df_filtrado[col_org] == val_comprador] if (col_org in df_filtrado.columns and val_comprador != "No registrado") else pd.DataFrame()
    
    tot_licitaciones = len(df_competencia) if not df_competencia.empty else 1
    tot_ganadas = len(df_competencia[df_competencia["OPPORTUNITY_STATUS"].astype(str).str.contains("Adjudicad", case=False, na=False)]) if ("OPPORTUNITY_STATUS" in df_competencia.columns and not df_competencia.empty) else 0
    tot_perdidas = max(0, tot_licitaciones - tot_ganadas)
    tot_competidores = 3
    win_rate = (tot_ganadas / tot_licitaciones * 100) if tot_licitaciones > 0 else 0.0

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("# Procesos en Comprador", str(tot_licitaciones))
    k2.metric("# Competidores Frecuentes", str(tot_competidores))
    k3.metric("# Ganadas Histórico", str(tot_ganadas))
    k4.metric("# Perdidas Histórico", str(tot_perdidas))
    k5.metric("Win Rate Comprador", f"{win_rate:.1f} %")

    es_adjudicada = "ADJUDICAD" in val_estado.upper() or "OC EMITIDA" in val_estado.upper()

    if es_adjudicada:
        st.markdown("##### 🏆 Factor Ganador y Resultados de Adjudicación")
        adj_real = limpiar_texto(item.get("AWARDED_PROVIDERS") or item.get("Adjudicatario (Proveedor Ganador)"), fallback="Proveedor Adjudicado")
        motivo_adj = limpiar_texto(item.get("COMMENTS") or item.get("MANAGED_STATUS_NAME") or item.get("Comentarios"), fallback="Oferta con menor precio relativo y cumplimiento del 100% de requerimientos en bases.")

        st.markdown(f"""
        <div class="reason-box-green">
            <b>Adjudicatario Ganador:</b> {adj_real}<br>
            <b>Razón de Adjudicación en Acta:</b> {motivo_adj}
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"##### ⏳ Estado del Proceso ({val_tipo_proceso}): Abierto / En Evaluación")
        st.markdown(f"""
        <div class="reason-box-blue">
            <b>📌 Estado Actual del Proceso:</b> {val_estado}<br>
            <b>Nota Táctica para {val_tipo_proceso}:</b> Este proceso se encuentra en fase activa de postulación o evaluación por la institución compradora.
        </div>
        """, unsafe_allow_html=True)

    # ==========================================
    # 💵 PRESUPUESTO & VALORES DE REFERENCIA
    # ==========================================
    st.markdown("---")
    st.subheader("💵 Presupuesto y Valores de Referencia")

    monto_raw = item.get("APPLIED_AMOUNT") or item.get("Monto Ofertado / Estimado (CLP)") or item.get("AVAILABLE_AMOUNT") or item.get("TOTAL_AWARDED_AMOUNT") or 0
    monto_extraido = limpiar_monto_a_float(monto_raw)

    if val_tipo_proceso == "Compra Ágil":
        val_bruto_def = int(monto_extraido) if monto_extraido > 0 else 760000
    else:
        val_bruto_def = int(monto_extraido * 1.19) if monto_extraido > 0 else 1190000

    p1, p2, p3 = st.columns([1.5, 1.5, 1])

    monto_bruto_input = p1.number_input(
        "Presupuesto Estimado Total con IVA (CLP):",
        min_value=0,
        value=val_bruto_def,
        step=50000,
        key=f"monto_bruto_user_{val_code}",
        help="En Compra Ágil, este monto corresponde al presupuesto total publicado en Mercado Público (con IVA)."
    )

    monto_bruto_total = float(monto_bruto_input)
    monto_neto_calculado = float(round(monto_bruto_total / 1.19))

    p2.metric("Monto Neto Estimado sin IVA", formatear_moneda(monto_neto_calculado))
    plazo_pago = limpiar_texto(item.get("PAYMENT_TERMS"), fallback="30 a 60 días (Estándar)")
    p3.metric("Plazo Estimado de Pago", plazo_pago)

    comentarios_txt = limpiar_texto(item.get("COMMENTS") or item.get("Comentarios"), fallback="Sin observaciones registradas por la comisión.")
    st.info("💬 **Comentarios de Gestión & Observaciones:** " + comentarios_txt)

    # ==========================================
    # 📐 SIMULADOR CON 4 VARIABLES DE EVALUACIÓN
    # ==========================================
    st.markdown("---")
    st.subheader("📐 Simulador de Costos por Criterios de Evaluación y Margen de Oferta")

    col_calc1, col_calc2 = st.columns(2)

    val_eval_tec_def = int(round(monto_neto_calculado * 0.50)) if monto_neto_calculado > 0 else 350000
    eval_tecnica = col_calc1.number_input(
        "Evaluación Técnica (Insumos, Personal, Equipamiento) (CLP):",
        min_value=0,
        value=val_eval_tec_def,
        step=10000,
        key=f"eval_tec_{val_code}",
        help="Costos directos asociados al cumplimiento técnico de la prestación."
    )

    eval_admin = col_calc1.number_input(
        "Evaluación Administrativa (Garantías, Gestión Documental) (CLP):",
        min_value=0,
        value=15000 if val_tipo_proceso != "Compra Ágil" else 0,
        step=2500,
        key=f"eval_admin_{val_code}",
        help="Pólizas, boletas de fiel cumplimiento y gestión administrativa."
    )

    eval_economica = col_calc1.number_input(
        "Evaluación Económica (Costos Financieros, Retenciones) (CLP):",
        min_value=0,
        value=20000,
        step=2500,
        key=f"eval_econ_{val_code}",
        help="Gastos de financiamiento, comisiones o costos de transacción."
    )

    eval_territorial = col_calc1.number_input(
        "Evaluación Territorial (Logística, Traslado por Zona) (CLP):",
        min_value=0,
        value=30000,
        step=5000,
        key=f"eval_terr_{val_code}",
        help="Fletes, logística de zona y distribución regional."
    )

    margen_pct = col_calc2.slider(
        "Margen de Utilidad Deseado (%)",
        min_value=1,
        max_value=80,
        value=20,
        key=f"margen_{val_code}"
    )

    costo_total_base = float(eval_tecnica + eval_admin + eval_economica + eval_territorial)

    precio_neto_sugerido = (costo_total_base / (1 - (margen_pct / 100.0))) if (costo_total_base > 0 and margen_pct < 100) else 0.0
    iva_sugerido = precio_neto_sugerido * 0.19
    precio_bruto_sugerido = precio_neto_sugerido + iva_sugerido
    ganancia_bruta = precio_neto_sugerido - costo_total_base

    st.markdown("---")
    st.markdown("### 📊 Propuesta Económica Recomendada")

    if monto_bruto_total > 0 and precio_bruto_sugerido > 0:
        diferencia_bruta = monto_bruto_total - precio_bruto_sugerido
        pct_utilizado = (precio_bruto_sugerido / monto_bruto_total) * 100

        if precio_bruto_sugerido <= monto_bruto_total:
            st.success(f"🟢 **Oferta Competitiva:** La propuesta final con IVA ({formatear_moneda(precio_bruto_sugerido)}) representa el **{pct_utilizado:.1f}%** del presupuesto del cliente ({formatear_moneda(monto_bruto_total)}). (Holgura: {formatear_moneda(diferencia_bruta)})")
        else:
            st.error(f"🔴 **Alerta de Presupuesto:** La propuesta supera el presupuesto estimado por {formatear_moneda(abs(diferencia_bruta))} ({pct_utilizado:.1f}% del estimado).")

    res1, res2, res3, res4 = st.columns(4)

    with res1:
        st.markdown(f'''
            <div class="kpi-card" style="border-top: 4px solid #3b82f6;">
                <div class="kpi-title">Punto de Equilibrio (Neto)</div>
                <div class="kpi-value">{formatear_moneda(costo_total_base)}</div>
                <small style="color: #64748b;">Suma 4 Evaluaciones</small>
            </div>
        ''', unsafe_allow_html=True)

    with res2:
        st.markdown(f'''
            <div class="kpi-card" style="border-top: 4px solid #2563eb;">
                <div class="kpi-title">Precio Sugerido (Neto)</div>
                <div class="kpi-value">{formatear_moneda(precio_neto_sugerido)}</div>
                <small style="color: #64748b;">Valor Propuesta Comercial</small>
            </div>
        ''', unsafe_allow_html=True)

    with res3:
                st.markdown(f'''
                    <div class="kpi-card" style="border-top: 4px solid #0284c7;">
                        <div class="kpi-title">Precio Final (Con IVA 19%)</div>
                        <div class="kpi-value">{formatear_moneda(precio_bruto_sugerido)}</div>
                        <small style="color: #64748b;">Monto Total Facturable</small>
                    </div>
                ''', unsafe_allow_html=True)

    with res4:
        st.markdown(f'''
            <div class="kpi-card" style="border-top: 4px solid #16a34a;">
                <div class="kpi-title">Utilidad Bruta Estimada</div>
                <div class="kpi-value" style="color: #15803d;">{formatear_moneda(ganancia_bruta)}</div>
                <small style="color: #166534;">Margen Efectivo: {margen_pct}%</small>
            </div>
        ''', unsafe_allow_html=True)

else:
    st.warning("⚠️ No se pudieron obtener datos.")
