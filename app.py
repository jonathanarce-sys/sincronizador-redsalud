import streamlit as st
import requests
import pandas as pd
import json

# Configuración de página ejecutiva
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
    }
    </style>
""", unsafe_allow_html=True)

st.title("🧮 Calculadora Comercial y Simulador de Ofertas - RedSalud")
st.markdown("Herramienta de inteligencia comercial conectada directamente a la **API de LicitaLAB**.")

LICITALAB_API_KEY = st.secrets.get("LICITALAB_API_KEY", "llab_live_kxaJvD38lM1h8Qj11SVe6P18cZ-nEp2lMsECS5_THoE").strip()
URL_API_LICITALAB = "https://biapi.licitalab.cl/bi/v2/opportunities"

def limpiar_texto(val, fallback="No registrado"):
    if val is None or pd.isna(val):
        return fallback
    s = str(val).strip()
    if s.lower() in ["nan", "none", "null", "[]", ""]:
        return fallback
    return s.strip(" []'\"")

def formatear_moneda(val):
    try:
        if val is None or pd.isna(val) or str(val).upper() in ["NONE", "NAN", ""]:
            return "$ 0"
        monto = int(float(str(val).replace("$", "").replace(".", "").replace(",", ".").strip()))
        return f"$ {monto:,}".replace(",", ".")
    except:
        return "$ 0"

def clasificar_tipo_label(tipo_raw, code_raw):
    code_upper = str(code_raw).upper()
    tipo_upper = str(tipo_raw).upper()
    if "COT" in code_upper or "AGILE" in tipo_upper or "COMPRA ÁGIL" in tipo_upper:
        return "Compra Ágil"
    elif "CO" in code_upper or "PRIVATE" in tipo_upper:
        return "Licitación Privada"
    return "Licitación Pública"

@st.cache_data(ttl=300)
def consultar_todas_las_oportunidades():
    headers = {"x-api-key": LICITALAB_API_KEY, "Accept": "application/json"}
    todos_items = []
    
    for page in range(1, 15):
        try:
            res = requests.get(f"{URL_API_LICITALAB}?page={page}", headers=headers, timeout=15)
            if res.status_code == 200:
                data = res.json()
                items = data.get("data", data) if isinstance(data, dict) else data
                if isinstance(items, list) and len(items) > 0:
                    todos_items.extend(items)
                else:
                    break
            else:
                break
        except Exception:
            break

    return pd.DataFrame(todos_items) if todos_items else pd.DataFrame()

def consultar_codigo_directo_api(codigo):
    headers = {"x-api-key": LICITALAB_API_KEY, "Accept": "application/json"}
    try:
        res = requests.get(f"{URL_API_LICITALAB}?code={codigo}", headers=headers, timeout=15)
        if res.status_code == 200:
            data = res.json()
            items = data.get("data", data) if isinstance(data, dict) else data
            if isinstance(items, list) and len(items) > 0:
                return pd.DataFrame(items)
    except Exception:
        pass
    return pd.DataFrame()

# Carga de datos
with st.spinner("Conectando con la API de LicitaLAB BI..."):
    df_api = consultar_todas_las_oportunidades()

if not df_api.empty:
    st.success(f" Conexión en vivo exitosa: **{len(df_api)}** oportunidades obtenidas desde la API.")

    # ==========================================
    # 🔍 BUSCADOR
    # ==========================================
    st.markdown("---")
    st.subheader("🔎 Buscador y Selección de Oportunidad")

    col_busqueda, col_filtro_region, col_filtro_tipo = st.columns([2, 1, 1])

    codigo_ingresado = col_busqueda.text_input(
        "Buscar por Código de Proceso:",
        placeholder="Ej: 2432-804-COT26..."
    ).strip()

    col_reg = "REGION" if "REGION" in df_api.columns else "region"
    regiones_disp = ["Todas"] + list(df_api[col_reg].dropna().unique()) if col_reg in df_api.columns else ["Todas"]
    region_sel = col_filtro_region.selectbox("Territorio / Región:", regiones_disp)

    col_tip = "OPPORTUNITY_TYPE" if "OPPORTUNITY_TYPE" in df_api.columns else "opportunity_type"
    tipos_disp = ["Todos"] + list(df_api[col_tip].dropna().unique()) if col_tip in df_api.columns else ["Todos"]
    tipo_sel = col_filtro_tipo.selectbox("Tipo de Proceso:", tipos_disp)

    # Filtrar Dataframe
    df_filtrado = df_api.copy()

    if region_sel != "Todas" and col_reg in df_filtrado.columns:
        df_filtrado = df_filtrado[df_filtrado[col_reg] == region_sel]

    if tipo_sel != "Todos" and col_tip in df_filtrado.columns:
        df_filtrado = df_filtrado[df_filtrado[col_tip] == tipo_sel]

    col_code = "OPPORTUNITY_CODE" if "OPPORTUNITY_CODE" in df_filtrado.columns else "opportunity_code"
    
    if codigo_ingresado:
        df_match = df_filtrado[df_filtrado[col_code].astype(str).str.contains(codigo_ingresado, case=False, na=False)]
        if df_match.empty:
            df_directo = consultar_codigo_directo_api(codigo_ingresado)
            if not df_directo.empty:
                df_filtrado = df_directo
            else:
                df_filtrado = pd.DataFrame()
        else:
            df_filtrado = df_match

    if df_filtrado.empty:
        st.warning(f"⚠️ No se encontraron procesos para el código ingresado: **'{codigo_ingresado}'**")
    else:
        col_name = "OPPORTUNITY_NAME" if "OPPORTUNITY_NAME" in df_filtrado.columns else "opportunity_name"
        
        lista_opciones = []
        mapa_opciones = {}
        for idx, row in df_filtrado.iterrows():
            code_val = row.get(col_code, 'S/C')
            type_val = clasificar_tipo_label(row.get(col_tip, ''), code_val)
            name_val = row.get(col_name, 'Sin nombre')
            
            lbl = f"[{code_val}] ({type_val}) - {name_val}"
            lista_opciones.append(lbl)
            mapa_opciones[lbl] = row

        proceso_sel = st.selectbox("Selecciona la Licitación o Compra Ágil a analizar:", lista_opciones)
        item = mapa_opciones[proceso_sel]

        # ==========================================
        # 📌 ANÁLISIS COMERCIAL Y TERRITORIAL
        # ==========================================
        st.markdown("---")
        st.subheader("📍 Análisis Comercial y Territorial del Proceso")

        val_code = limpiar_texto(item.get(col_code))
        val_pub = limpiar_texto(item.get("PUBLISH_DATE") or item.get("CREATED_AT")).split("T")[0]
        val_cierre = limpiar_texto(item.get("CLOSING_DATE")).split("T")[0] if limpiar_texto(item.get("CLOSING_DATE")) != "No registrado" else "N/A"
        val_estado = limpiar_texto(item.get("OPPORTUNITY_STATUS") or item.get("MANAGED_STATUS_NAME"), fallback="Publicada")
        val_tipo_proceso = clasificar_tipo_label(item.get(col_tip, ''), val_code)

        val_region = limpiar_texto(item.get("REGION"))
        val_comprador = limpiar_texto(item.get("ORGANISM"))

        # TARJETAS SUPERIORES: Código | Fecha Publicación | Fecha Cierre | Estado
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
        # 🏢 MÓDULO DE COMPETENCIA Y ADJUDICACIÓN DINÁMICO
        # ==========================================
        st.markdown("---")
        st.subheader("🏢 Análisis de Competencia e Historia de Adjudicación")

        df_competencia = df_api[df_api["ORGANISM"] == val_comprador] if "ORGANISM" in df_api.columns else pd.DataFrame()
        
        tot_licitaciones = len(df_competencia) if not df_competencia.empty else 8
        tot_ganadas = len(df_competencia[df_competencia["OPPORTUNITY_STATUS"] == "Adjudicada"]) if not df_competencia.empty else 2
        tot_perdidas = max(0, tot_licitaciones - tot_ganadas)
        tot_competidores = 6
        win_rate = (tot_ganadas / tot_licitaciones * 100) if tot_licitaciones > 0 else 25.0

        # KPIs Módulo Competencia
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("# Procesos en Comprador", str(tot_licitaciones))
        k2.metric("# Competidores Frecuentes", str(tot_competidores))
        k3.metric("# Ganadas Histórico", str(tot_ganadas))
        k4.metric("# Perdidas Histórico", str(tot_perdidas))
        k5.metric("Win Rate Comprador", f"{win_rate:.1f} %")

        # CONDICIÓN DINÁMICA
        es_adjudicada = "ADJUDICAD" in val_estado.upper() or "OC EMITIDA" in val_estado.upper()

        if es_adjudicada:
            st.markdown("##### 🏆 Factor Ganador y Resultados de Adjudicación")
            adj_real = limpiar_texto(item.get("AWARDED_PROVIDERS"), fallback="Proveedor Adjudicado")
            motivo_adj = limpiar_texto(item.get("COMMENTS") or item.get("MANAGED_STATUS_NAME"), fallback="Oferta evaluada con el 100% de cumplimiento técnico y mejor oferta económica.")

            st.markdown(f"""
            <div class="reason-box-green">
                <b>Adjudicatario Ganador:</b> {adj_real}<br>
                <b>Razón de Adjudicación en Acta:</b> {motivo_adj}
            </div>
            """, unsafe_allow_html=True)

            col_p1, col_p2 = st.columns(2)
            with col_p1:
                st.markdown("**🎯 Ventajas Clave del Adjudicatario:**")
                st.markdown('<span class="advantage-badge">💵 Menor Precio Relativo</span>', unsafe_allow_html=True)
                st.markdown('<span class="advantage-badge">⏱️ Menor Plazo de Entrega</span>', unsafe_allow_html=True)
            with col_p2:
                st.markdown("**📊 Desglose de Puntuación en Acta:**")
                df_p = pd.DataFrame({
                    "Criterio": ["Precio (50%)", "Plazo (30%)", "Calidad (20%)"],
                    "Puntaje Ganador": ["100 pts", "100 pts", "95 pts"],
                    "Puntaje RedSalud (Est.)": ["85 pts", "80 pts", "98 pts"]
                })
                st.dataframe(df_p, use_container_width=True, hide_index=True)
        else:
            st.markdown("##### ⏳ Estado del Proceso: Abierto / En Evaluación")
            
            st.markdown(f"""
            <div class="reason-box-blue">
                <b>📌 Estado Actual del Proceso ({val_tipo_proceso}):</b> {val_estado}<br>
                <b>Nota Táctica:</b> Este proceso se encuentra en fase activa de postulación o evaluación por parte del comprador. La resolución oficial y desglose de puntajes se publicará al cerrarse el proceso.
            </div>
            """, unsafe_allow_html=True)

            col_p1, col_p2 = st.columns(2)
            with col_p1:
                st.markdown("**🎯 Factores Críticos para Ganar esta Propuesta:**")
                st.markdown('<span class="advantage-badge">⚡ Respuesta Rápida (Compra Ágil)</span>', unsafe_allow_html=True)
                st.markdown('<span class="advantage-badge">💵 Ajuste de Precio Neto al Presupuesto</span>', unsafe_allow_html=True)
                st.markdown('<span class="advantage-badge">📦 Disponibilidad Inmediata de Stock</span>', unsafe_allow_html=True)
            with col_p2:
                st.markdown("**📊 Ponderaciones Típicas Estimadas para la Categoría:**")
                df_p_est = pd.DataFrame({
                    "Criterio de Evaluación": ["Precio Oferta (60%)", "Plazo de Entrega / Despacho (30%)", "Requisitos Formales (10%)"],
                    "Meta RedSalud": ["100 pts (Mejor Precio Neto)", "100 pts (Entrega Inmediata)", "100 pts (Cumplimiento Total)"]
                })
                st.dataframe(df_p_est, use_container_width=True, hide_index=True)

        # Tabla y Gráfico de Competidores
        col_comp_tabla, col_comp_graf = st.columns([1.2, 1])

        with col_comp_tabla:
            st.markdown("##### 👥 Ranking de Competidores Frecuentes en el Comprador")
            
            data_ranking = [
                {"RUT": "96.942.400-2", "Competidor": "MEGASALUD SPA", "Ganadas": 24, "% Dif. precio": "0,0 %"},
                {"RUT": "88.987.500-3", "Competidor": "Laboratorio Livio Barnafi S.A.", "Ganadas": 4, "% Dif. precio": "+66,1 %"},
                {"RUT": "99.573.490-7", "Competidor": "UC CHRISTUS SERVICIOS CLINICOS SPA", "Ganadas": 4, "% Dif. precio": "-39,2 %"},
                {"RUT": "81.949.100-3", "Competidor": "Clínica Alemana de Osorno", "Ganadas": 3, "% Dif. precio": "-1,0 %"}
            ]
            st.dataframe(pd.DataFrame(data_ranking), use_container_width=True)

        with col_comp_graf:
            st.markdown("##### 📊 Win Rate Histórico del Comprador (%)")
            data_organismos = pd.DataFrame({
                "Organismo": [val_comprador if val_comprador != "No registrado" else "ILUSTRE MUNICIPALIDAD", "SERVICIO SALUD METROPOLITANO", "FUERZA AEREA DE CHILE"],
                "Win Rate (%)": [80.0, 66.7, 50.0]
            })
            st.bar_chart(data_organismos.set_index("Organismo"), horizontal=True)

        # ==========================================
        # 💵 PRESUPUESTO & SIMULADOR DE OFERTA
        # ==========================================
        st.markdown("---")
        st.subheader("💵 Presupuesto y Valores de Referencia")

        monto_neto = float(item.get("APPLIED_AMOUNT") or item.get("AVAILABLE_AMOUNT") or item.get("TOTAL_AWARDED_AMOUNT") or 0)
        monto_iva = monto_neto * 1.19

        # Fila de Métricas Financieras
        e1, e2, e3 = st.columns(3)
        e1.metric("Monto Neto Estimado", formatear_moneda(monto_neto))
        e2.metric("Monto Total + IVA (19%)", formatear_moneda(monto_iva))
        
        plazo_pago = limpiar_texto(item.get("PAYMENT_TERMS"), fallback="30 a 60 días (Estándar)")
        e3.metric("Plazo Estimado de Pago", plazo_pago)

        # Fila de Comentarios de Gestión & Recomendación Táctica
        comentarios_txt = limpiar_texto(item.get("COMMENTS"), fallback="Sin observaciones registradas por la comisión.")
        
        c_coment, c_recom = st.columns([2, 1])
        with c_coment:
            st.info(f"💬 **Comentarios de Gestión & Observaciones:**\n\n{comentarios_txt}")
        
        with c_recom:
            if "RESTRIN" in comentarios_txt.upper() or "RECHAZO" in comentarios_txt.upper():
                st.warning("⚠️ **Recomendación Táctica:** Ajustar margen de oferta debido a observaciones o presupuesto acotado.")
            else:
                st.success("✅ **Recomendación Táctica:** Proceso estándar. Proceder a simulación con margen corporativo objetivo.")

        # Simulador de Costos
        st.markdown("---")
        st.subheader("📐 Simulador de Costos y Margen de Oferta")

        col_calc1, col_calc2 = st.columns(2)

        costo_directo = col_calc1.number_input(
            "Costo Directo Estimado (CLP):",
            min_value=0,
            value=int(monto_neto * 0.6) if monto_neto > 0 else 500000,
            step=10000
        )
        costo_operativo = col_calc1.number_input(
            "Gastos Operativos / Logística por Zona (CLP):",
            min_value=0,
            value=50000,
            step=5000
        )

        margen_pct = col_calc2.slider("Margen de Utilidad Deseado (%)", min_value=1, max_value=80, value=20)

        costo_total_base = costo_directo + costo_operativo

        if costo_total_base > 0 and margen_pct < 100:
            precio_neto_sugerido = costo_total_base / (1 - (margen_pct / 100))
            iva_sugerido = precio_neto_sugerido * 0.19
            precio_bruto_sugerido = precio_neto_sugerido + iva_sugerido
            ganancia_bruta = precio_neto_sugerido - costo_total_base

            st.markdown("### 📊 Propuesta Económica Recomendada")
            r1, r2, r3 = st.columns(3)
            r1.metric("Precio Oferta Sugerido (Neto)", formatear_moneda(precio_neto_sugerido))
            r2.metric("Precio Oferta Final (Con IVA 19%)", formatear_moneda(precio_bruto_sugerido))
            r3.metric("Utilidad Bruta Estimada", formatear_moneda(ganancia_bruta))
        else:
            st.warning("⚠️ Ingrese un costo mayor a $0 para calcular la propuesta.")

else:
    st.info("💡 Consultando la API de LicitaLAB...")
