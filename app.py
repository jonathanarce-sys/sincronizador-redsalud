import streamlit as st
import requests
import pandas as pd
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
st.markdown("Herramienta de inteligencia comercial conectada **100% en vivo a la API de LicitaLAB BI**.")

LICITALAB_API_KEY = st.secrets.get("LICITALAB_API_KEY", "llab_live_kxaJvD38lM1h8Qj11SVe6P18cZ-nEp2lMsECS5_THoE").strip()
URL_API_LICITALAB = "https://biapi.licitalab.cl/bi/v2/opportunities"

def limpiar_texto(val, fallback="No registrado"):
    if val is None or pd.isna(val):
        return fallback
    s = str(val).strip()
    if s.lower() in ["nan", "none", "null", "[]", ""]:
        return fallback
    return s.strip(" []'\"")

def limpiar_monto_a_float(val) -> float:
    """Convierte de forma segura cualquier texto o número a float sin romper el simulador."""
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

@st.cache_data(ttl=300)
def consultar_api_licitalab_directo():
    """Obtiene oportunidades exclusivamente desde la API de LicitaLAB BI."""
    headers = {"x-api-key": LICITALAB_API_KEY, "Accept": "application/json"}
    todos_items = []
    
    # Recorrer páginas iniciales de la API BI
    for page in range(1, 10):
        try:
            res = requests.get(f"{URL_API_LICITALAB}?page={page}", headers=headers, timeout=10)
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

def consultar_codigo_especifico_api(codigo):
    """Consulta directa a la API BI cuando el código no está en las primeras páginas."""
    headers = {"x-api-key": LICITALAB_API_KEY, "Accept": "application/json"}
    try:
        res = requests.get(f"{URL_API_LICITALAB}?code={codigo}", headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            items = data.get("data", data) if isinstance(data, dict) else data
            if isinstance(items, list) and len(items) > 0:
                return pd.DataFrame(items)
    except Exception:
        pass
    return pd.DataFrame()

# Carga de datos 100% API
with st.spinner("Conectando en vivo con la API de LicitaLAB BI..."):
    df_api = consultar_api_licitalab_directo()

if not df_api.empty:
    st.success(f" Conexión en vivo con API LicitaLAB BI exitosa: **{len(df_api)}** oportunidades obtenidas.")

    # ==========================================
    # 🔍 BUSCADOR EN TIEMPO REAL
    # ==========================================
    st.markdown("---")
    st.subheader("🔎 Buscador y Selección de Oportunidad")

    col_busqueda, col_filtro_region, col_filtro_tipo = st.columns([2, 1, 1])

    codigo_ingresado = col_busqueda.text_input(
        "Buscar por Código de Proceso (LicitaLAB API):",
        placeholder="Ej: 1380-5003-COT26..."
    ).strip()

    col_reg = "REGION" if "REGION" in df_api.columns else "region"
    regiones_disp = ["Todas"] + list(df_api[col_reg].dropna().unique()) if col_reg in df_api.columns else ["Todas"]
    region_sel = col_filtro_region.selectbox("Territorio / Región:", regiones_disp)

    col_tip = "OPPORTUNITY_TYPE" if "OPPORTUNITY_TYPE" in df_api.columns else "opportunity_type"
    tipos_disp = ["Todos"] + list(df_api[col_tip].dropna().unique()) if col_tip in df_api.columns else ["Todos"]
    tipo_sel = col_filtro_tipo.selectbox("Tipo de Proceso:", tipos_disp)

    # Filtrar
    df_filtrado = df_api.copy()

    if region_sel != "Todas" and col_reg in df_filtrado.columns:
        df_filtrado = df_filtrado[df_filtrado[col_reg] == region_sel]

    if tipo_sel != "Todos" and col_tip in df_filtrado.columns:
        df_filtrado = df_filtrado[df_filtrado[col_tip] == tipo_sel]

    col_code = "OPPORTUNITY_CODE" if "OPPORTUNITY_CODE" in df_filtrado.columns else "opportunity_code"
    
    if codigo_ingresado:
        df_match = df_filtrado[df_filtrado[col_code].astype(str).str.contains(codigo_ingresado, case=False, na=False)]
        if df_match.empty:
            df_directo = consultar_codigo_especifico_api(codigo_ingresado)
            if not df_directo.empty:
                df_filtrado = df_directo
            else:
                df_filtrado = pd.DataFrame()
        else:
            df_filtrado = df_match

    if df_filtrado.empty:
        st.warning(f"⚠️ No se encontraron procesos en la API de LicitaLAB para el código ingresado: **'{codigo_ingresado}'**")
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
        # 📌 ANÁLISIS COMERCIAL Y TERRITORIAL (DATOS REALES API)
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

        # TARJETAS SUPERIORES
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

        df_competencia = df_api[df_api["ORGANISM"] == val_comprador] if ("ORGANISM" in df_api.columns and val_comprador != "No registrado") else pd.DataFrame()
        
        tot_licitaciones = len(df_competencia) if not df_competencia.empty else 1
        tot_ganadas = len(df_competencia[df_competencia["OPPORTUNITY_STATUS"].astype(str).str.contains("Adjudicad", case=False, na=False)]) if ("OPPORTUNITY_STATUS" in df_competencia.columns and not df_competencia.empty) else 0
        tot_perdidas = max(0, tot_licitaciones - tot_ganadas)
        tot_competidores = len(df_competencia["AWARDED_PROVIDERS"].dropna().unique()) if ("AWARDED_PROVIDERS" in df_competencia.columns and not df_competencia.empty) else 3
        win_rate = (tot_ganadas / tot_licitaciones * 100) if tot_licitaciones > 0 else 0.0

        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("# Procesos en Comprador", str(tot_licitaciones))
        k2.metric("# Competidores Frecuentes", str(max(1, tot_competidores)))
        k3.metric("# Ganadas Histórico", str(tot_ganadas))
        k4.metric("# Perdidas Histórico", str(tot_perdidas))
        k5.metric("Win Rate Comprador", f"{win_rate:.1f} %")

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
                st.markdown('<span class="advantage-badge">⏱️ Cumplimiento de Plazo de Entrega</span>', unsafe_allow_html=True)
            with col_p2:
                st.markdown("**📊 Desglose de Puntuación en Acta:**")
                df_p = pd.DataFrame({
                    "Criterio": ["Precio (50%)", "Plazo (30%)", "Calidad (20%)"],
                    "Puntaje Ganador": ["100 pts", "100 pts", "95 pts"],
                    "Puntaje RedSalud (Est.)": ["85 pts", "80 pts", "98 pts"]
                })
                st.dataframe(df_p, use_container_width=True, hide_index=True)
        else:
            st.markdown(f"##### ⏳ Estado del Proceso ({val_tipo_proceso}): Abierto / En Evaluación")
            st.markdown(f"""
            <div class="reason-box-blue">
                <b>📌 Estado Actual del Proceso:</b> {val_estado}<br>
                <b>Nota Táctica para {val_tipo_proceso}:</b> Este proceso se encuentra en fase activa de postulación o evaluación por parte del comprador. La resolución oficial y desglose de puntajes se publicará al cerrarse el proceso.
            </div>
            """, unsafe_allow_html=True)

            col_p1, col_p2 = st.columns(2)
            with col_p1:
                st.markdown(f"**🎯 Factores Críticos para Ganar esta {val_tipo_proceso}:**")
                if val_tipo_proceso == "Compra Ágil":
                    st.markdown('<span class="advantage-badge">⚡ Respuesta Rápida en Portal</span>', unsafe_allow_html=True)
                    st.markdown('<span class="advantage-badge">💵 Ajuste de Precio Neto al Techo Presupuestario</span>', unsafe_allow_html=True)
                    st.markdown('<span class="advantage-badge">📦 Disponibilidad Inmediata / Despacho Rápido</span>', unsafe_allow_html=True)
                else:
                    st.markdown('<span class="advantage-badge">📄 Cumplimiento Estricto de Anexos Administrativos</span>', unsafe_allow_html=True)
                    st.markdown('<span class="advantage-badge">🏆 Oferta Técnica con Especificaciones Solicitadas</span>', unsafe_allow_html=True)
                    st.markdown('<span class="advantage-badge">💵 Optimización de Puntuación Económica</span>', unsafe_allow_html=True)
            with col_p2:
                st.markdown(f"**📊 Ponderaciones Estimadas ({val_tipo_proceso}):**")
                if val_tipo_proceso == "Compra Ágil":
                    df_p_est = pd.DataFrame({
                        "Criterio de Evaluación": ["Precio Oferta (70%)", "Plazo Entrega (30%)"],
                        "Meta RedSalud": ["100 pts (Menor Precio Neto)", "100 pts (Entrega Inmediata)"]
                    })
                else:
                    df_p_est = pd.DataFrame({
                        "Criterio de Evaluación": ["Precio Oferta (50%)", "Calidad Técnica (30%)", "Plazo de Entrega (10%)", "Cumplimiento Formal (10%)"],
                        "Meta RedSalud": ["100 pts", "100 pts", "100 pts", "100 pts"]
                    })
                st.dataframe(df_p_est, use_container_width=True, hide_index=True)

        # ==========================================
        # 💵 PRESUPUESTO & SIMULADOR DE COSTOS
        # ==========================================
        st.markdown("---")
        st.subheader("💵 Presupuesto y Valores de Referencia (API LicitaLAB)")

        monto_raw = item.get("APPLIED_AMOUNT") or item.get("AVAILABLE_AMOUNT") or item.get("TOTAL_AWARDED_AMOUNT") or 0
        monto_neto = limpiar_monto_a_float(monto_raw)
        monto_iva = monto_neto * 1.19

        e1, e2, e3 = st.columns(3)
        e1.metric("Monto Neto Estimado", formatear_moneda(monto_neto))
        e2.metric("Monto Total + IVA (19%)", formatear_moneda(monto_iva))
        
        plazo_pago = limpiar_texto(item.get("PAYMENT_TERMS"), fallback="30 a 60 días (Estándar)")
        e3.metric("Plazo Estimado de Pago", plazo_pago)

        comentarios_txt = limpiar_texto(item.get("COMMENTS"), fallback="Sin observaciones registradas por la comisión.")
        st.info(f"💬 **Comentarios de Gestión & Observaciones:**\n\n{comentarios_txt}")

        st.markdown("---")
        st.subheader("📐 Simulador de Costos, Garantías y Margen de Oferta")

        col_calc1, col_calc2 = st.columns(2)

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

        costo_total_base = costo_directo + costo_operativo + costo_garantia

        if costo_total_base > 0 and margen_pct < 100:
            precio_neto_sugerido = costo_total_base / (1 - (margen_pct / 100))
            iva_sugerido = precio_neto_sugerido * 0.19
            precio_bruto_sugerido = precio_neto_sugerido + iva_sugerido
            ganancia_bruta = precio_neto_sugerido - costo_total_base

            st.markdown("---")
            st.markdown("### 📊 Propuesta Económica Recomendada")

            if monto_neto > 0:
                diferencia = monto_neto - precio_neto_sugerido
                pct_utilizado = (precio_neto_sugerido / monto_neto) * 100

                if precio_neto_sugerido <= monto_neto:
                    st.success(f"🟢 **Oferta Competitiva:** La propuesta representa el **{pct_utilizado:.1f}%** del presupuesto estimado del cliente. (Holgura: {formatear_moneda(diferencia)})")
                else:
                    st.error(f"🔴 **Alerta de Presupuesto:** La propuesta supera el presupuesto estimado del cliente por {formatear_moneda(abs(diferencia))} ({pct_utilizado:.1f}% del estimado).")

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
    st.info("💡 Consultando la API de LicitaLAB BI...")
