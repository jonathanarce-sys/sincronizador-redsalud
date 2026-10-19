import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import base64
import json

# Configuración de página con diseño ancho y estilo visual
st.set_page_config(
    page_title="Calculadora de Ofertas - RedSalud",
    layout="wide",
    page_icon="🧮"
)

st.title("🧮 Calculadora de Licite / Ofertas - RedSalud")
st.markdown("Herramienta interactiva para la estimación de costos, simulaciones y márgenes de licitaciones.")

SPREADSHEET_ID = "1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek"

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

    # Limpieza básica
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
    # 🔍 BUSCADOR Y FILTROS DUALES
    # ==========================================
    st.markdown("### 🔎 Búsqueda y Selección de Oportunidad")

    # Identificar nombres de columnas clave
    col_codigo = next((c for c in df.columns if "código" in c.lower() or "codigo" in c.lower()), df.columns[0])
    col_tipo = next((c for c in df.columns if "tipo" in c.lower()), df.columns[1] if len(df.columns) > 1 else df.columns[0])
    col_nombre = next((c for c in df.columns if "nombre" in c.lower()), df.columns[2] if len(df.columns) > 2 else df.columns[0])

    col_busqueda, col_filtro_tipo = st.columns([2, 1])

    # 1. Buscador directo por código
    codigo_buscado = col_busqueda.text_input(
        "🔎 Buscar por Código de Proceso (Licitación o Compra Ágil):",
        placeholder="Ej: 1380-4954-COT26..."
    ).strip()

    # 2. Filtro por tipo de proceso
    tipos_disponibles = ["Todos"] + list(df[col_tipo].dropna().unique())
    tipo_sel = col_filtro_tipo.selectbox("Filtrar por Tipo de Proceso:", tipos_disponibles)

    # Filtrar dataframe según búsqueda y selección
    df_filtrado = df.copy()

    if tipo_sel != "Todos":
        df_filtrado = df_filtrado[df_filtrado[col_tipo] == tipo_sel]

    if codigo_buscado:
        df_filtrado = df_filtrado[df_filtrado[col_codigo].astype(str).str.contains(codigo_buscado, case=False, na=False)]

    if df_filtrado.empty:
        st.warning(f"⚠️ No se encontraron coincidencias para el código o filtro ingresado: **'{codigo_buscado}'**")
    else:
        # Menú desplegable con las opciones encontradas
        opciones_proceso = df_filtrado[col_nombre].dropna().unique()
        
        # Etiqueta amigable que incluye el código en el selector
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
        # 📋 DETALLES DE LA OPORTUNIDAD SELECCIONADA
        # ==========================================
        st.markdown("---")
        st.subheader("📋 Detalles de la Oportunidad Seleccionada")

        col_cierre = next((c for c in df.columns if "cierre" in c.lower() or "termino" in c.lower()), "Fecha de Cierre")
        col_monto = next((c for c in df.columns if "monto" in c.lower() or "estimado" in c.lower() or "total" in c.lower()), "Monto")
        col_estado = next((c for c in df.columns if "estado" in c.lower()), "Estado")

        # Fila 1 de Métricas Principales
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Código Proceso", str(item.get(col_codigo, "N/A")))
        m2.metric("Tipo Proceso", str(item.get(col_tipo, "N/A")))
        m3.metric("Fecha de Cierre", str(item.get(col_cierre, "N/A")))
        m4.metric("Estado de la Oferta", str(item.get(col_estado, "N/A")))

        # Cálculo del Valor Adjudicado / Estimado con IVA 19%
        val_monto_raw = item.get(col_monto, 0)
        try:
            val_monto_clean = float(str(val_monto_raw).replace("$", "").replace(".", "").replace(",", ".").strip())
            monto_con_iva = val_monto_clean * 1.19
            str_monto_iva = f"$ {int(monto_con_iva):,}".replace(",", ".")
            str_monto_neto = f"$ {int(val_monto_clean):,}".replace(",", ".")
        except Exception:
            str_monto_iva = f"{val_monto_raw} (Con IVA)"
            str_monto_neto = f"{val_monto_raw}"

        # Fila 2 de Información Económica Reestructurada
        st.markdown("##### 💵 Montos Registrados y Comentarios")
        e1, e2, e3 = st.columns([1, 1, 2])
        e1.metric("Monto Neto Estimado / Adjudicado", str_monto_neto)
        e2.metric("Valor Total con IVA (Adjudicado / Por Adjudicar)", str_monto_iva)
        
        comentario_txt = item.get("Comentarios", item.get("Observaciones", "Sin comentarios adicionales."))
        e3.info(f"**Comentarios / Observaciones:**\n\n{comentario_txt}")

        # ==========================================
        # 📐 SIMULADOR Y CALCULADORA DE OFERTA
        # ==========================================
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

            st.markdown("### 📊 Resultado de la Propuesta")
            
            # Reestructurado: Solo 2 tarjetas principales (Neto y Final con IVA)
            res1, res2 = st.columns(2)
            res1.metric("Precio Oferta Sugerido (Neto)", f"$ {int(precio_sugerido_neto):,}".replace(",", "."))
            res2.metric("Precio Oferta Final (Con IVA 19%)", f"$ {int(precio_sugerido_bruto):,}".replace(",", "."))

else:
    st.info("💡 Esperando datos de la base maestra...")
