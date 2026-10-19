import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import base64
import json

st.set_page_config(page_title="Calculadora de Ofertas RedSalud", layout="wide", page_icon="🧮")

st.title("🧮 Calculadora de Licite / Ofertas - RedSalud")
st.markdown("Herramienta interactiva para la estimación de costos y márgenes de licitaciones.")

SPREADSHEET_ID = "1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek"

@st.cache_data(ttl=300)
def cargar_datos():
    if "GCP_JSON_BASE64" not in st.secrets:
        st.error("❌ No se encontró la clave GCP_JSON_BASE64 en Settings > Secrets.")
        return pd.DataFrame()

    b64_str = st.secrets["GCP_JSON_BASE64"]
    json_bytes = base64.b64decode(b64_str)
    creds_dict = json.loads(json_bytes.decode("utf-8"))

    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)

    sheet = client.open_by_key(SPREADSHEET_ID).sheet1
    data = sheet.get_all_records()
    return pd.DataFrame(data)

# Carga de Datos
with st.spinner("Cargando oportunidades desde Google Sheets..."):
    try:
        df = cargar_datos()
    except Exception as e:
        st.error(f"❌ Error al conectar con Google Sheets: {e}")
        df = pd.DataFrame()

if not df.empty:
    st.success(f" Base de datos conectada correctamente: **{len(df)}** registros cargados.")

    # Filtros superiores
    col_f1, col_f2 = st.columns(2)
    
    col_tipo = "Tipo Proceso" if "Tipo Proceso" in df.columns else df.columns[2]
    col_nombre = "Nombre Proceso" if "Nombre Proceso" in df.columns else df.columns[4]

    tipos_disponibles = ["Todos"] + list(df[col_tipo].unique())
    tipo_sel = col_f1.selectbox("Filtrar por Tipo de Proceso:", tipos_disponibles)

    df_filtrado = df if tipo_sel == "Todos" else df[df[col_tipo] == tipo_sel]

    opciones_proceso = df_filtrado[col_nombre].unique()
    proceso_sel = col_f2.selectbox("Selecciona una Licitación o Compra Ágil:", opciones_proceso)

    if proceso_sel:
        item = df_filtrado[df_filtrado[col_nombre] == proceso_sel].iloc[0]
        
        st.markdown("---")
        st.subheader("📋 Detalles de la Oportunidad Seleccionada")
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Código Proceso", item.get("Código Proceso", "N/A"))
        c2.metric("Tipo Proceso", item.get("Tipo Proceso", "N/A"))
        c3.metric("Monto Estimado", item.get("Monto Total / Estimado (CLP)", "$ 0"))
        c4.metric("Estado", item.get("Estado de la Oferta", "N/A"))

        # Calculadora
        st.markdown("---")
        st.subheader("📐 Simulador y Calculadora de Margen de Oferta")

        col_calc1, col_calc2 = st.columns(2)
        
        costo_directo = col_calc1.number_input("Costo Directo Estimado (CLP)", min_value=0, value=500000, step=10000)
        costo_operativo = col_calc1.number_input("Gastos Operativos / Logística (CLP)", min_value=0, value=50000, step=5000)
        
        margen_pct = col_calc2.slider("Margen de Utilidad Deseado (%)", min_value=1, max_value=60, value=20)
        
        costo_total_base = costo_directo + costo_operativo
        
        if costo_total_base > 0:
            precio_sugerido_neto = costo_total_base / (1 - (margen_pct / 100))
            iva = precio_sugerido_neto * 0.19
            precio_sugerido_bruto = precio_sugerido_neto + iva
            utilidad_neta = precio_sugerido_neto - costo_total_base

            st.markdown("### 📊 Resultado de la Propuesta")
            res1, res2, res3 = st.columns(3)
            res1.metric("Precio Oferta Sugerido (Neto)", f"$ {int(precio_sugerido_neto):,}".replace(",", "."))
            res2.metric("Precio Oferta Final (Con IVA 19%)", f"$ {int(precio_sugerido_bruto):,}".replace(",", "."))
            res3.metric("Ganancia Neta Estimada", f"$ {int(utilidad_neta):,}".replace(",", "."))
