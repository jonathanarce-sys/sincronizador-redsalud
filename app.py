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
    if isinstance(val, (int, float)):
        return float(val)
    try:
        val_str = str(val).replace("$", "").replace(".", "").replace(",", ".").replace("CLP", "").strip()
        return float(val_str)
    except Exception:
        return 0.0

def formatear_moneda(val):
    """Formatea valores numéricos a CLP ($ 638.655) sin corromper por puntos decimales."""
    try:
        monto_num = limpiar_monto_a_float(val)
        monto_int = int(round(monto_num))
        return f"$ {monto_int:,}".replace(",", ".")
    except Exception:
        return "$ 0"

def ajustar_monto_compra_agil(monto_raw, tipo_proceso):
    monto = limpiar_monto_a_float(monto_raw)
    if tipo_proceso == "Compra Ágil":
        if monto >= 6000000 and monto <= 10000000:
            monto = monto / 10.0
        elif monto > 10000000:
            monto = 760000.0
    return monto

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
    
    if any(k in org_upper for k in ["BULNES", "YUNGAY", "CHILLÁN", "CHILLAN", "SAN CARLOS", "ÑUBLE", "NUBLE"]):
        return "Región del Ñuble"
    elif any(k in org_upper for k in ["CHÉPICA", "CHEPICA", "SAN FERNANDO", "RANCAGUA", "CHIMBARONGO", "SANTA CRUZ", "O'HIGGINS"]):
        return "Región del Libertador General Bernardo O'Higgins"
    elif any(k in org_upper for k in ["SAN PEDRO DE ATACAMA", "ANTOFAGASTA", "CALAMA", "TOCOPILLA"]):
        return "Región de Antofagasta"
    elif any(k in org_upper for k in ["IQUIQUE", "ALTO HOSPICIO", "POZO ALMONTE", "TARAPACÁ"]):
        return "Región de Tarapacá"
    elif any(k in org_upper for k in ["VALPARAÍSO", "VALPARAISO", "VIÑA", "VINA", "QUILLOTA"]):
        return "Región de Valparaíso"
    elif any(k in org_upper for k in ["FRUTILLAR", "PUERTO MONTT", "OSORNO", "RELONCAVÍ"]):
        return "Región de Los Lagos"

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
                cre
