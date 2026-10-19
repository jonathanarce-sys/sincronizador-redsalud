import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import json

st.set_page_config(page_title="Calculadora de Ofertas RedSalud", layout="wide", page_icon="🧮")

st.title("🧮 Calculadora de Licite / Ofertas - RedSalud")
st.markdown("Herramienta interactiva para la estimación de costos y márgenes de licitaciones.")

# Conexión a Google Sheets
@st.cache_data(ttl=600)
def cargar_datos():
    creds_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS_JSON"])
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_key("1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek").sheet1
    data = sheet.get_all_records()
    return pd.DataFrame(data)

try:
    df = cargar_datos()
    st.success(f" Base de datos cargada: {len(df)} oportunidades registradas.")
    
    # Buscador de Licitación
    busqueda = st.selectbox("Selecciona una Licitación o Compra Ágil:", df["Nombre Proceso"].unique() if "Nombre Proceso" in df.columns else [])
    
    if busqueda:
        item = df[df["Nombre Proceso"] == busqueda].iloc[0]
        st.subheader("📋 Detalles del Proceso")
        col1, col2, col3 = st.columns(3)
        col1.metric("Código Proceso", item.get("Código Proceso", "N/A"))
        col2.metric("Tipo Proceso", item.get("Tipo Proceso", "N/A"))
        col3.metric("Monto Estimado", item.get("Monto Total / Estimado (CLP)", "$ 0"))

    st.markdown("---")
    st.subheader("📐 Simulador de Costos y Margen")
    
    c1, c2 = st.columns(2)
    costo_base = c1.number_input("Costo Base Directo (CLP)", min_value=0, value=1000000, step=50000)
    margen_deseado = c2.slider("Margen de Utilidad Deseado (%)", min_value=5, max_value=50, value=20)
    
    precio_oferta = costo_base / (1 - (margen_deseado / 100))
    utilidad = precio_oferta - costo_base
    
    st.metric("Precio de Oferta Sugerido (Neto CLP)", f"$ {int(precio_oferta):,}".replace(",", "."))
    st.metric("Utilidad Estimada (CLP)", f"$ {int(utilidad):,}".replace(",", "."))

except Exception as e:
    st.error(f"Error al conectar con Google Sheets: {e}")
