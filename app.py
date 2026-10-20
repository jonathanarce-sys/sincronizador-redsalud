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
    """Mapeador geográfico de municipios y organismos chilenos para evitar regiones erróneas."""
    reg_limpia = limpiar_texto(region_raw, fallback="")
    if reg_limpia and reg_limpia not in ["No registrado", "Sin información"]:
        return reg_limpia

    org_upper = str(organismo).upper()
    
    # Mapeos específicos
    if "CHÉPICA" in org_upper or "CHEPICA" in org_upper or "SAN FERNANDO" in org_upper or "RANCAGUA" in org_upper:
        return "Región del Libertador General Bernardo O'Higgins"
    elif "SAN PEDRO DE ATACAMA" in org_upper or "ANTOFAGASTA" in org_upper or "CALAMA" in org_upper:
        return "Región de Antofagasta"
    elif "IQUIQUE" in org_upper or "ALTO HOSPICIO" in org_upper or "TARAPACÁ" in org_upper:
        return "Región de Tarapacá"
    elif "VALPARAÍSO" in org_upper or "VALPARAISO" in org_upper or "VIÑA" in org_upper or "VINA" in org_upper:
        return "Región de Valparaíso"
    elif "FRUTILLAR" in org_upper or "PUERTO MONTT" in org_upper or "OSORNO" in org_upper or "RELONCAVÍ" in org_upper:
        return "Región de Los Lagos"
    elif "CONCEPCIÓN" in org_upper or "CONCEPCION" in org_upper or "TALCAHUANO" in org_upper or "BIOBÍO" in org_upper:
        return "Región del Biobío"
    elif "TEMUCO" in org_upper or "PADRE LAS CASAS" in org_upper or "ARAUCANÍA" in org_upper:
        return "Región de La Araucanía"
    elif "TALCA" in org_upper or "CURICÓ" in org_upper or "MAULE" in org_upper:
        return "Región del Maule"

    return "Región Metropolitana"

@st.cache_data(ttl=900)
def cargar_datos_con_respaldo_anti_bloqueo():
    headers = {"x-api-key": LICITALAB_API_KEY, "Accept": "application/json"}
    todos_items = []
    api_exitosa = False

    try:
        res = requests.get(f"{URL_API_LICITALAB}?page=1", headers=headers, timeout=6)
        if res.status_code == 200:
            data = res.json()
            items = data.get("data", data) if isinstance(data, dict) else data
            if isinstance(items, list) and len(items) > 0:
                todos_items.extend(items)
                api_exitosa = True
    except Exception:
        pass

    if api_exitosa and todos_items:
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
    except Exception as e:
        st.error(f"❌ Error al cargar datos: {e}")

    return pd.DataFrame()

# Carga de datos
with st.spinner("Cargando oportunidades..."):
    df_api = cargar_datos_con_respaldo_anti_bloqueo()

if not df_api.empty:
    origen_txt = df_api["_origen"].iloc[0] if "_origen" in df_api.columns else "Base Maestra"
    st.success(f" Base de datos conectada vía **{origen_txt}**: **{len(df_api)}** oportunidades cargadas.")

    # ==========================================
    # 🔍 BUSCADOR
    # ==========================================
    st.markdown("---")
    st.subheader("🔎 Buscador y Selección de Oportunidad")

    col_busqueda, col_filtro_tipo = st.columns([2.5, 1.5])

    codigo_ingresado = col_busqueda.text_input(
        "Ingresa o busca por Código de Proceso:",
        value="1380-5003-COT26",
        placeholder="Ej: 1380-5003-COT26, 2432-804-COT26..."
    ).strip()

    df_filtrado = df_api.copy()
    col_code = "OPPORTUNITY_CODE" if "OPPORTUNITY_CODE" in df_filtrado.columns else "Código Proceso"

    if codigo_ingresado:
        df_filtrado = df_filtrado[df_filtrado[col_code].astype(str).str.contains(codigo_ingresado, case=False, na=False)]

    if df_filtrado.empty:
        st.warning(f"⚠️ No se encontraron procesos para el código ingresado: **'{codigo_ingresado}'**")
    else:
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

        val_comprador = limpiar_texto(item.get("ORGANISM") or item.get("Institución Compradora"))
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
        # 🏢 MÓDULO DE COMPETENCIA Y ADJUDICACIÓN
        # ==========================================
        st.markdown("---")
        st.subheader("🏢 Análisis de Competencia e Historia de Adjudicación")

        col_org = "ORGANISM" if "ORGANISM" in df_api.columns else "Institución Compradora"
        df_competencia = df_api[df_api[col_org] == val_comprador] if (col_org in df_api.columns and val_comprador != "No registrado") else pd.DataFrame()
        
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
                <b>Nota Táctica para {val_tipo_proceso}:</b> Este proceso se encuentra en fase activa. La resolución oficial se publicará al cerrarse la evaluación por el comprador.
            </div>
            """, unsafe_allow_html=True)

        # ==========================================
        # 💵 PRESUPUESTO & SIMULADOR CORREGIDO
        # ==========================================
        st.markdown("---")
        st.subheader("💵 Presupuesto y Valores de Referencia")

        monto_raw = item.get("APPLIED_AMOUNT") or item.get("AVAILABLE_AMOUNT") or item.get("TOTAL_AWARDED_AMOUNT") or item.get("Monto Ofertado / Estimado (CLP)") or item.get("Monto Total + IVA (Adjudicado / Estimado)") or 0
        monto_neto = limpiar_monto_a_float(monto_raw)

        # Topecito táctico para Compras Ágiles en Mercado Público (Evitar $40M inflados)
        if val_tipo_proceso == "Compra Ágil" and monto_neto > 8000000:
            monto_neto = 3500000.0  # Presupuesto de cotización típico para Compra Ágil

        monto_iva = monto_neto * 1.19

        e1, e2, e3 = st.columns(3)
        e1.metric("Monto Neto Estimado", formatear_moneda(monto_neto))
        e2.metric("Monto Total + IVA (19%)", formatear_moneda(monto_iva))
        
        plazo_pago = limpiar_texto(item.get("PAYMENT_TERMS"), fallback="30 a 60 días (Estándar)")
        e3.metric("Plazo Estimado de Pago", plazo_pago)

        comentarios_txt = limpiar_texto(item.get("COMMENTS") or item.get("Comentarios"), fallback="Sin observaciones registradas por la comisión.")
        st.info(f"💬 **Comentarios de Gestión & Observaciones:**\n\n{comentarios_txt}")

        st.markdown("---")
        st.subheader("📐 Simulador de Costos, Garantías y Margen de Oferta")

        col_calc1, col_calc2 = st.columns(2)

        # CÁLCULO DE COSTO DIRECTO INICIAL REALISTA
        val_costo_dir_def = int(monto_neto * 0.6) if monto_neto > 0 else 500000

        costo_directo = col_calc1.number_input(
            "Costo Directo Estimado (Insumos, Personal) (CLP):",
            min_value=0,
            value=val_costo_dir_def,
            step=10000,
            key=f"costo_directo_{val_code}"
        )
        costo_operativo = col_calc1.number_input(
            "Gastos Operativos / Logística por Zona (CLP):",
            min_value=0,
            value=50000,
            step=5000,
            key=f"costo_operativo_{val_code}"
        )
        costo_garantia = col_calc1.number_input(
            "Costo Boleta de Garantía / Financiero (CLP):",
            min_value=0,
            value=15000,
            step=2500,
            key=f"costo_garantia_{val_code}"
        )

        margen_pct = col_calc2.slider(
            "Margen de Utilidad Deseado (%)",
            min_value=1,
            max_value=80,
            value=20,
            key=f"margen_{val_code}"
        )

        # MATEMÁTICA EXACTA DEL PUNTO DE EQUILIBRIO Y PRECIO
        costo_total_base = float(costo_directo + costo_operativo + costo_garantia)

        if costo_total_base > 0 and margen_pct < 100:
            precio_neto_sugerido = costo_total_base / (1 - (margen_pct / 100.0))
            iva_sugerido = precio_neto_sugerido * 0.19
            precio_bruto_sugerido = precio_neto_sugerido + iva_sugerido
            ganancia_bruta = precio_neto_sugerido - costo_total_base

            st.markdown("---")
            st.markdown("### 📊 Propuesta Económica Recomendada")

            if monto_neto > 0:
                diferencia = monto_neto - precio_neto_sugerido
                pct_utilizado = (precio_neto_sugerido / monto_neto) * 100

                if precio_neto_sugerido <= monto_neto:
                    st.success(f"🟢 **Oferta Competitiva:** La propuesta representa el **{pct_utilizado:.1f}%** del presupuesto estimado. (Holgura: {formatear_moneda(diferencia)})")
                else:
                    st.error(f"🔴 **Alerta de Presupuesto:** La propuesta supera el presupuesto estimado por {formatear_moneda(abs(diferencia))} ({pct_utilizado:.1f}% del estimado).")

            res1, res2, res3, res4 = st.columns(4)
            
            with res1:
                st.markdown(f'''
                    <div class="kpi-card" style="border-top: 4px solid #3b82f6;">
                        <div class="kpi-title">Punto de Equilibrio (Neto)</div>
                        <div class="kpi-value">{formatear_moneda(costo_total_base)}</div>
                        <small style="color: #64748b;">Costo Mínimo Sin Ganancia</small>
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
            st.warning("⚠️ Ingrese un costo mayor a $0 para calcular la propuesta.")

else:
    st.warning("⚠️ No se pudieron obtener datos.")
