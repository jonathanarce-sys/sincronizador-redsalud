import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import base64
import json

# Configuración de página con diseño ancho y profesional
st.set_page_config(
    page_title="Calculadora de Ofertas - RedSalud",
    layout="wide",
    page_icon="🧮"
)

# Estilo visual limpio
st.markdown("""
    <style>
    .stMetric {
        background-color: #f8f9fa;
        padding: 12px;
        border-radius: 8px;
        border: 1px solid #e9ecef;
    }
    </style>
""", unsafe_allow_html=True)

st.title("🧮 Calculadora de Licite / Ofertas - RedSalud")
st.markdown("Herramienta interactiva para la estimación de costos, análisis territorial, competencia y márgenes de licitaciones.")

SPREADSHEET_ID = "1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek"

def limpiar_monto_a_float(val) -> float:
    """Convierte cualquier valor de texto/moneda a float de forma segura sin romper la interfaz."""
    if pd.isna(val) or val is None:
        return 0.0
    try:
        val_str = str(val).replace("$", "").replace(".", "").replace(",", ".").replace("CLP", "").strip()
        return float(val_str)
    except Exception:
        return 0.0

def formatear_clp(monto: float) -> str:
    """Formatea un número flotante a formato moneda CLP ($ 1.000.000)."""
    try:
        return f"$ {int(round(monto)):,}".replace(",", ".")
    except Exception:
        return "$ 0"

@st.cache_data(ttl=300)
def cargar_y_procesar_datos():
    creds_dict = None
    if "GCP_JSON_BASE64" in st.secrets:
        b64_str = st.secrets["GCP_JSON_BASE64"]
        json_bytes = base64.b64decode(b64_str)
        creds_dict = json.loads(json_bytes.decode("utf-8"))
    elif "gcp_service_account" in st.secrets:
        creds_dict = dict(st.secrets["gcp_service_account"])
        if "private_key" in creds_dict:
            creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
    else:
        st.error("❌ No se encontraron credenciales en Settings > Secrets de Streamlit.")
        return pd.DataFrame()

    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)

    sheet = client.open_by_key(SPREADSHEET_ID).sheet1
    data = sheet.get_all_records()
    df = pd.DataFrame(data)

    if df.empty:
        return df

    # Limpieza de columnas no requeridas
    cols_eliminar = [c for c in df.columns if "criterio" in c.lower() or "evaluaci" in c.lower()]
    df = df.drop(columns=cols_eliminar, errors="ignore")

    return df

# Carga de datos
with st.spinner("Cargando información desde la Base Maestra..."):
    try:
        df = cargar_y_procesar_datos()
    except Exception as e:
        st.error(f"❌ Error al conectar con Google Sheets: {e}")
        df = pd.DataFrame()

if not df.empty:
    st.success(f" Base de datos conectada: **{len(df)}** oportunidades disponibles.")

    # ==========================================
    # 🔍 BUSCADOR Y FILTROS ESTRATÉGICOS
    # ==========================================
    st.markdown("### 🔎 Búsqueda y Selección de Oportunidad")

    # Identificación inteligente de columnas
    col_codigo = next((c for c in df.columns if "código" in c.lower() or "codigo" in c.lower()), df.columns[0])
    col_tipo = next((c for c in df.columns if "tipo" in c.lower()), df.columns[1] if len(df.columns) > 1 else df.columns[0])
    col_nombre = next((c for c in df.columns if "nombre" in c.lower()), df.columns[2] if len(df.columns) > 2 else df.columns[0])
    col_territorio = next((c for c in df.columns if "territorio" in c.lower() or "region" in c.lower() or "zona" in c.lower() or "lugar" in c.lower()), None)

    f1, f2, f3 = st.columns([2, 1, 1])

    # 1. Buscador por Código
    codigo_buscado = f1.text_input(
        "🔎 Buscar por Código de Proceso:",
        placeholder="Ej: 1380-4954-COT26..."
    ).strip()

    # 2. Filtro por Tipo de Proceso
    tipos_disponibles = ["Todos"] + list(df[col_tipo].dropna().unique())
    tipo_sel = f2.selectbox("Tipo de Proceso:", tipos_disponibles)

    # 3. Filtro por Territorio (si existe en la planilla)
    if col_territorio:
        territorios_disp = ["Todos"] + list(df[col_territorio].dropna().unique())
        territorio_sel = f3.selectbox("Territorio / Zona:", territorios_disp)
    else:
        territorio_sel = "Todos"

    # Filtrar Dataframe
    df_filtrado = df.copy()

    if tipo_sel != "Todos":
        df_filtrado = df_filtrado[df_filtrado[col_tipo] == tipo_sel]

    if col_territorio and territorio_sel != "Todos":
        df_filtrado = df_filtrado[df_filtrado[col_territorio] == territorio_sel]

    if codigo_buscado:
        df_filtrado = df_filtrado[df_filtrado[col_codigo].astype(str).str.contains(codigo_buscado, case=False, na=False)]

    if df_filtrado.empty:
        st.warning(f"⚠️ No se encontraron resultados con los criterios seleccionados.")
    else:
        # Selector de Licitación
        lista_opciones = []
        mapa_opciones = {}
        for idx, row in df_filtrado.iterrows():
            lbl = f"[{row[col_codigo]}] - {row[col_nombre]}"
            lista_opciones.append(lbl)
            mapa_opciones[lbl] = row

        proceso_seleccionado_lbl = st.selectbox(
            "Selecciona la Licitación o Compra Ágil a calcular:",
            lista_opciones
        )

        item = mapa_opciones[proceso_seleccionado_lbl]

        # ==========================================
        # 📋 DETALLES DE LA OPORTUNIDAD & METRICAS
        # ==========================================
        st.markdown("---")
        st.subheader("📋 Detalles de la Oportunidad Seleccionada")

        col_cierre = next((c for c in df.columns if "cierre" in c.lower() or "termino" in c.lower()), "Fecha de Cierre")
        col_monto = next((c for c in df.columns if "monto" in c.lower() or "estimado" in c.lower() or "total" in c.lower()), "Monto")
        col_estado = next((c for c in df.columns if "estado" in c.lower()), "Estado")
        col_competencia = next((c for c in df.columns if "competencia" in c.lower() or "oferente" in c.lower() or "ganador" in c.lower()), None)

        # Fila 1: Datos de Identificación
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Código Proceso", str(item.get(col_codigo, "N/A")))
        m2.metric("Tipo Proceso", str(item.get(col_tipo, "N/A")))
        m3.metric("Fecha de Cierre", str(item.get(col_cierre, "N/A")))
        m4.metric("Estado de la Oferta", str(item.get(col_estado, "N/A")))

        # Fila 2: Análisis Económico, Territorio y Competencia
        monto_neto_val = limpiar_monto_a_float(item.get(col_monto, 0))
        monto_iva_val = monto_neto_val * 1.19

        st.markdown("##### 📍 Análisis Territorial, Competencia y Económico")
        e1, e2, e3, e4 = st.columns(4)

        e1.metric("Territorio / Zona", str(item.get(col_territorio, "No especificado")) if col_territorio else "N/A")
        e2.metric("Monto Neto Estimado", formatear_clp(monto_neto_val))
        e3.metric("Valor Total con IVA (Adjudicado/Por Adjudicar)", formatear_clp(monto_iva_val))
        
        info_comp = str(item.get(col_competencia, "Sin registro de competencia")) if col_competencia else "No registrada"
        e4.metric("Competencia / Oferentes", info_comp)

        # Comentarios u Observaciones
        comentario_txt = str(item.get("Comentarios", item.get("Observaciones", "Sin comentarios registrados.")))
        st.info(f"💬 **Comentarios u Observaciones del Proceso:**\n\n{comentario_txt}")

        # ==========================================
        # 📐 SIMULADOR & CALCULADORA A PRUEBA DE ERRORES
        # ==========================================
        st.markdown("---")
        st.subheader("📐 Simulador y Calculadora de Margen de Oferta")

        col_calc1, col_calc2 = st.columns(2)

        costo_directo = col_calc1.number_input(
            "Costo Directo Estimado (CLP)",
            min_value=0,
            value=int(monto_neto_val * 0.6) if monto_neto_val > 0 else 500000,
            step=10000
        )
        costo_operativo = col_calc1.number_input(
            "Gastos Operativos / Logística (CLP)",
            min_value=0,
            value=50000,
            step=5000
        )

        margen_pct = col_calc2.slider("Margen de Utilidad Deseado (%)", min_value=1, max_value=80, value=20)

        costo_total_base = costo_directo + costo_operativo

        # Cálculos de resultados protegidos contra quiebres
        if costo_total_base > 0 and margen_pct < 100:
            precio_sugerido_neto = costo_total_base / (1 - (margen_pct / 100))
            iva_calc = precio_sugerido_neto * 0.19
            precio_sugerido_bruto = precio_sugerido_neto + iva_calc
            utilidad_bruta = precio_sugerido_neto - costo_total_base

            st.markdown("### 📊 Resultado de la Propuesta")
            res1, res2, res3 = st.columns(3)
            
            res1.metric("Precio Oferta Sugerido (Neto)", formatear_clp(precio_sugerido_neto))
            res2.metric("Precio Oferta Final (Con IVA 19%)", formatear_clp(precio_sugerido_bruto))
            res3.metric("Margen / Utilidad Bruta Estimada", formatear_clp(utilidad_bruta))
        else:
            st.warning("⚠️ Ingrese un costo mayor a $0 para calcular la propuesta.")

else:
    st.info("💡 Esperando datos de la base maestra...")
