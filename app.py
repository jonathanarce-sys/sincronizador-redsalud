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

@st.cache_data(ttl=180)
def consultar_api_licitalab(page=1, code_search=None):
    """Consulta directa y liviana a la API BI de LicitaLAB."""
    headers = {"x-api-key": LICITALAB_API_KEY, "Accept": "application/json"}
    
    url = f"{URL_API_LICITALAB}?page={page}"
    if code_search:
        url = f"{URL_API_LICITALAB}?code={code_search.strip()}"

    try:
        res = requests.get(url, headers=headers, timeout=8)
        if res.status_code == 200:
            data = res.json()
            items = data.get("data", data) if isinstance(data, dict) else data
            if isinstance(items, list):
                return pd.DataFrame(items)
        else:
            st.error(f"⚠️ API LicitaLAB respondió con código {res.status_code}: {res.text}")
    except Exception as e:
        st.error(f"❌ Error al conectar con la API de LicitaLAB: {e}")
        
    return pd.DataFrame()

# ==========================================
# 🔎 BUSCADOR PRINCIPAL (CARGA INMEDIATA)
# ==========================================
st.markdown("---")
st.subheader("🔎 Buscador y Selección de Oportunidad")

col_busqueda, col_filtro_tipo = st.columns([2.5, 1.5])

codigo_ingresado = col_busqueda.text_input(
    "Ingresa o busca por Código de Proceso (API LicitaLAB BI):",
    value="1380-5003-COT26",
    placeholder="Ej: 1380-5003-COT26, 2432-804-COT26..."
).strip()

# Consulta directa según búsqueda o página principal
if codigo_ingresado:
    with st.spinner(
