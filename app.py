import streamlit as st
import requests
import pandas as pd
import json

# Configuración de la página
st.set_page_config(
    page_title="Calculadora Comercial LicitaLAB - RedSalud",
    layout="wide",
    page_icon="🧮"
)

st.title("🧮 Calculadora Comercial y Simulador de Ofertas - RedSalud")
st.markdown("Herramienta de inteligencia comercial conectada directamente a la **API de LicitaLAB**.")

# 🔑 Obtener API Key de LicitaLAB desde Streamlit Secrets o constante
LICITALAB_API_KEY = st.secrets.get("LICITALAB_API_KEY", "llab_live_kxaJvD38lM1h8Qj11SVe6P18cZ-nEp2lMsECS5_THoE")
URL_API_LICITALAB = "https://biapi.licitalab.cl/bi/v2/opportunities"

@st.cache_data(ttl=300)
def consultar_api_licitalab():
    """Consulta la API de LicitaLAB BI y retorna las oportunidades en vivo."""
    headers = {
        "x-api-key": LICITALAB_API_KEY,
        "Accept": "application/json"
    }
    try:
        res = requests.get(f"{URL_API_LICITALAB}?page=1", headers=headers, timeout=15)
        if res.status_code == 200:
            data = res.json()
            items = data.get("data", data) if isinstance(data, dict) else data
            return pd.DataFrame(items) if isinstance(items, list) else pd.DataFrame()
        else:
            st.error(f"⚠️ Error al conectar con LicitaLAB API (Status {res.status_code})")
            return pd.DataFrame()
    except Exception as e:
        st.error(f"❌ Excepción al consultar la API: {e}")
        return pd.DataFrame()

# Carga de Datos desde la API
with st.spinner("Conectando con la API de LicitaLAB BI..."):
    df_api = consultar_api_licitalab()

if not df_api.empty:
    st.success(f" Conexión en vivo exitosa: **{len(df_api)}** oportunidades obtenidas directamente desde la API.")

    # ==========================================
    # 🔎 BUSCADOR & FILTROS DE INTELIGENCIA
    # ==========================================
    st.markdown("---")
    st.subheader("🔎 Buscador y Selección de Oportunidad")

    f1, f2, f3 = st.columns([2, 1, 1])

    # 1. Búsqueda por código
    codigo_buscado = f1.text_input(
        "Buscar por Código de Proceso:",
        placeholder="Ej: 1380-4954-COT26..."
    ).strip()

    # 2. Filtro por Región / Territorio
    col_region = "REGION" if "REGION" in df_api.columns else "region"
    regiones_disp = ["Todas"] + list(df_api[col_region].dropna().unique()) if col_region in df_api.columns else ["Todas"]
    region_sel = f2.selectbox("Territorio / Región:", regiones_disp)

    # 3. Filtro por Tipo
    col_tipo = "OPPORTUNITY_TYPE" if "OPPORTUNITY_TYPE" in df_api.columns else "opportunity_type"
    tipos_disp = ["Todos"] + list(df_api[col_tipo].dropna().unique()) if col_tipo in df_api.columns else ["Todos"]
    tipo_sel = f3.selectbox("Tipo de Proceso:", tipos_disp)

    # Filtrar DataFrame
    df_filtrado = df_api.copy()

    if region_sel != "Todas" and col_region in df_filtrado.columns:
        df_filtrado = df_filtrado[df_filtrado[col_region] == region_sel]

    if tipo_sel != "Todos" and col_tipo in df_filtrado.columns:
        df_filtrado = df_filtrado[df_filtrado[col_tipo] == tipo_sel]

    col_code = "OPPORTUNITY_CODE" if "OPPORTUNITY_CODE" in df_filtrado.columns else "opportunity_code"
    if codigo_buscado and col_code in df_filtrado.columns:
        df_filtrado = df_filtrado[df_filtrado[col_code].astype(str).str.contains(codigo_buscado, case=False, na=False)]

    if df_filtrado.empty:
        st.warning("⚠️ No se encontraron procesos con los criterios de búsqueda seleccionados.")
    else:
        # Selector de proceso
        col_name = "OPPORTUNITY_NAME" if "OPPORTUNITY_NAME" in df_filtrado.columns else "opportunity_name"
        
        lista_opciones = []
        mapa_opciones = {}
        for idx, row in df_filtrado.iterrows():
            lbl = f"[{row.get(col_code, 'S/C')}] - {row.get(col_name, 'Sin nombre')}"
            lista_opciones.append(lbl)
            mapa_opciones[lbl] = row

        proceso_sel = st.selectbox("Selecciona la Licitación o Compra Ágil a analizar:", lista_opciones)
        item = mapa_opciones[proceso_sel]

        # ==========================================
        # 📍 INTELIGENCIA COMERCIAL Y TERRITORIAL
        # ==========================================
        st.markdown("---")
        st.subheader("📍 Análisis Comercial y Territorial del Proceso")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Código Proceso", str(item.get(col_code, "N/A")))
        m2.metric("Workspace Asignado", str(item.get("WORKSPACE_TITLE", "Casa Matriz")))
        m3.metric("Fecha de Cierre", str(item.get("CLOSING_DATE", "N/A")).split("T")[0])
        m4.metric("Estado Oferta", str(item.get("OPPORTUNITY_STATUS", item.get("MANAGED_STATUS_NAME", "Publicada"))))

        st.markdown("##### 🏛️ Territorio, Comprador y Competencia")
        c1, c2, c3 = st.columns([1, 1.5, 1.5])
        
        c1.metric("Región / Territorio", str(item.get("REGION", "No indicada")))
        c2.metric("Institución Compradora", str(item.get("ORGANISM", "No indicada")))
        
        # Competencia u Oferentes Previos
        competidores = str(item.get("AWARDED_PROVIDERS", "Sin registro previo de competencia"))
        if competidores in ["None", "null", "[]", ""]:
            competidores = "Sin registro / Abierta"
        c3.metric("Competencia / Adjudicatario Previo", competidores)

        # ==========================================
        # 💵 ANÁLISIS ECONÓMICO Y PRESUPUESTARIO
        # ==========================================
        st.markdown("---")
        st.subheader("💵 Presupuesto y Valores de Referencia")

        monto_neto_raw = item.get("APPLIED_AMOUNT") or item.get("AVAILABLE_AMOUNT") or item.get("TOTAL_AWARDED_AMOUNT") or 0
        try:
            monto_neto = float(monto_neto_raw)
        except:
            monto_neto = 0.0

        monto_iva = monto_neto * 1.19

        e1, e2, e3 = st.columns(3)
        e1.metric("Monto Neto Disponible / Estimado", f"$ {int(monto_neto):,}".replace(",", "."))
        e2.metric("Monto Total + IVA (19%)", f"$ {int(monto_iva):,}".replace(",", "."))
        
        comentarios_txt = str(item.get("COMMENTS", "Sin observaciones registradas."))
        e3.info(f"💬 **Comentarios de Gestión:**\n\n{comentarios_txt}")

        # ==========================================
        # 📐 SIMULADOR TÁCTICO DE MARGEN DE OFERTA
        # ==========================================
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
            r1.metric("Precio Oferta Sugerido (Neto)", f"$ {int(precio_neto_sugerido):,}".replace(",", "."))
            r2.metric("Precio Oferta Final (Con IVA 19%)", f"$ {int(precio_bruto_sugerido):,}".replace(",", "."))
            r3.metric("Utilidad Bruta Estimada", f"$ {int(ganancia_bruta):,}".replace(",", "."))

else:
    st.info("💡 Consultando la API de LicitaLAB...")
