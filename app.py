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
    # 🔍 BUSCADOR Y SELECCIÓN DE OPORTUNIDAD
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
