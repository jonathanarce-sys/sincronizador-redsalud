import os
import re
import json
import base64
import unicodedata
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 1. CONFIGURACIÓN Y ESQUEMA DE 23 COLUMNAS
# ==========================================
SPREADSHEET_ID_DESTINO = os.environ.get(
    "SPREADSHEET_ID_ARANCELES",
    "1Lpuc3XXjss5QAhlmz7cuYUMmqlto7yLVpe_up8Yr6Ek"
).strip()

HOJA_DESTINO = "RAW_Data_Ingesta"

FUENTES_ARANCELES = [
    "ARMADA _ Arancel Consolidado [Clientes Sector Público] - PRESTACIONES 2026",
    "ISL_Arancel Consolidado_Providencia - PROVIDENCIA",
    "ISL_Arancel Consolidado_Valparaíso - VALPARAISO",
    "ISL_Arancel Consolidado_Magallanes - MAGALLANES",
    "Maestro Aranceles RedSalud. - Trazabilidad",
    "ISL_Arancel Consolidado_CMD - CMD",
    "ISL_Arancel Consolidado_Elqui - ELQUI",
    "DIPRECA_2026_Prestaciones",
    "DIPRECA_2026_Paquetes",
    "DIPRECA_2026_HMQ",
    "ISL_Arancel Consolidado_Iquique - IQUIQUE",
    "ISL_Arancel Consolidado_Santiago - SANTIAGO",
    "ISL_Arancel Consolidado_Rancagua - RANCAGUA",
    "ISL_Arancel Consolidado_Temuco - TEMUCO",
]

ENCABEZADOS_RAW_INGESTA = [
    "filial",
    "sociedad",
    "cliente",
    "contrato",
    "id_licitación",
    "centro",
    "año",
    "tipo_arancel [origen]",
    "código_redsalud [no TC]",
    "código_cliente",
    "código_fonasa",
    "glosa_prestación",
    "tipo_prestación",
    "Indexador",
    "precio_total",
    "ámbito",
    "recargo",
    "%_recargo",
    "vigencia_desde",
    "vigencia_hasta",
    "id_convenio_cliente",
    "Convenio_redsalud",
    "código_lugar_his",
]

ROLES_HMQ = [
    ("1º CIR", ["1º CIR", "1° CIR", "1ER CIR", "PRIMER CIRUJANO", "CIRUJANO 1"]),
    ("2º CIR", ["2º CIR", "2° CIR", "2DO CIR", "SEGUNDO CIRUJANO", "CIRUJANO 2"]),
    ("3º CIR", ["3º CIR", "3° CIR", "3ER CIR", "TERCER CIRUJANO", "CIRUJANO 3"]),
    ("4º CIR", ["4º CIR", "4° CIR", "4TO CIR", "CUARTO CIRUJANO", "CIRUJANO 4"]),
    ("ANEST", ["ANEST", "ANESTESIA", "ANESTESISTA", "ANESTESIOLOGO"]),
    ("ARSENALERA", ["ARSENALERA", "ARSENALERIA", "ARSENALERO"]),
]

ALIAS_COLUMNAS = {
    "filial": ["FILIAL", "CLINICA", "CLÍNICA", "SEDE_FILIAL"],
    "sociedad": ["SOCIEDAD", "RAZON SOCIAL", "RAZÓN SOCIAL", "RUT SOCIEDAD"],
    "cliente": ["CLIENTE", "INSTITUCION", "INSTITUCIÓN", "ORGANISMO", "MANDANTE"],
    "contrato": ["CONTRATO", "NOMBRE CONTRATO", "CONVENIO"],
    "id_licitación": ["ID_LICITACION", "ID_LICITACIÓN", "ID LICITACION", "CODIGO LICITACION", "CÓDIGO LICITACIÓN", "LICITACION"],
    "centro": ["CENTRO", "CENTRO MEDICO", "CENTRO MÉDICO", "SEDE", "SUCURSAL"],
    "año": ["AÑO", "ANO", "PERIODO"],
    "tipo_arancel [origen]": ["TIPO_ARANCEL [ORIGEN]", "TIPO_ARANCEL", "TIPO ARANCEL", "ORIGEN"],
    "código_redsalud [no TC]": ["CODIGO_REDSALUD [NO TC]", "CÓDIGO_REDSALUD [NO TC]", "CODIGO_REDSALUD", "CÓDIGO_REDSALUD", "COD_REDSALUD", "CODIGO REDSALUD", "CODIGO INTERNO"],
    "código_cliente": ["CODIGO_CLIENTE", "CÓDIGO_CLIENTE", "COD_CLIENTE", "CODIGO CLIENTE", "HOMOLOGO"],
    "código_fonasa": ["CODIGO_FONASA", "CÓDIGO_FONASA", "COD_FONASA", "CODIGO FONASA", "FONASA"],
    "glosa_prestación": ["GLOSA_PRESTACION", "GLOSA_PRESTACIÓN", "GLOSA", "PRESTACION", "PRESTACIÓN", "NOMBRE PRESTACION", "DESCRIPCION", "DESCRIPCIÓN"],
    "tipo_prestación": ["TIPO_PRESTACION", "TIPO_PRESTACIÓN", "TIPO PRESTACION", "CATEGORIA", "RUBRO", "GRUPO"],
    "Indexador": ["INDEXADOR", "REAJUSTE", "MONEDA", "FACTOR"],
    "precio_total": ["PRECIO_TOTAL", "PRECIO TOTAL", "VALOR TOTAL", "VALOR", "PRECIO", "ARANCEL", "TARIFA", "MONTO"],
    "ámbito": ["AMBITO", "ÁMBITO", "MODALIDAD", "TIPO ATENCION", "TIPO ATENCIÓN"],
    "recargo": ["RECARGO", "APLICA RECARGO", "TIPO RECARGO"],
    "%_recargo": ["%_RECARGO", "% RECARGO", "PORCENTAJE RECARGO", "PORC_RECARGO"],
    "vigencia_desde": ["VIGENCIA_DESDE", "VIGENCIA DESDE", "FECHA INICIO", "DESDE"],
    "vigencia_hasta": ["VIGENCIA_HASTA", "VIGENCIA HASTA", "FECHA TERMINO", "FECHA TÉRMINO", "HASTA"],
    "id_convenio_cliente": ["ID_CONVENIO_CLIENTE", "ID CONVENIO CLIENTE", "COD CONVENIO CLIENTE"],
    "Convenio_redsalud": ["CONVENIO_REDSALUD", "CONVENIO REDSALUD", "CONVENIO HIS"],
    "código_lugar_his": ["CODIGO_LUGAR_HIS", "CÓDIGO_LUGAR_HIS", "CODIGO LUGAR HIS", "LUGAR HIS", "CENTRO COSTO"],
}

CATALOGO_FILIALES = [
    (["PROVIDENCIA"], "RS Providencia", "96.536.000-8"),
    (["VALPARAISO", "VALPARAÍSO"], "RS Valparaíso", "96.543.000-6"),
    (["MAGALLANES"], "RS Magallanes", "96.541.000-5"),
    (["ELQUI"], "RS Elqui", "99.533.790-8"),
    (["IQUIQUE"], "RS Iquique", "96.598.850-0"),
    (["SANTIAGO"], "RS Santiago", "96.524.000-2"),
    (["RANCAGUA"], "RS Rancagua", "96.542.000-0"),
    (["TEMUCO"], "RS Mayor Temuco", "96.537.000-3"),
    (["VITACURA"], "RS Vitacura", "78.053.560-1"),
    (["CMD"], "Centros Médicos RedSalud", "96.856.000-2"),
]

# ==========================================
# 2. UTILIDADES
# ==========================================
def obtener_cliente_gspread():
    posibles = [
        "GCP_JSON_BASE64", "GCP_SERVICE_ACCOUNT", "GOOGLE_CREDENTIALS",
        "GCP_JSON", "GCP_SA_KEY", "GCP_CREDENTIALS"
    ]
    val = next((os.environ[k].strip() for k in posibles if k in os.environ and os.environ[k].strip()), None)
    if not val:
        raise ValueError("Sin credenciales GCP en el entorno.")
    try:
        pad = len(val) % 4
        if pad:
            val += "=" * (4 - pad)
        creds_dict = json.loads(base64.b64decode(val).decode("utf-8"))
    except Exception:
        creds_dict = json.loads(val)

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    return gspread.authorize(Credentials.from_service_account_info(creds_dict, scopes=scopes)), creds_dict.get("client_email", "SA")

def norm_txt(s):
    s = unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode("utf-8")
    return re.sub(r"\s+", " ", s).strip().upper()

def limpiar_codigo_redsalud(val):
    s = str(val or "").strip()
    s = re.sub(r"[\[\(\-]?\s*\bTC\b\s*[\]\)]?", "", s, flags=re.IGNORECASE).strip()
    return s

def parsear_monto(val):
    if val is None or val == "":
        return 0
    if isinstance(val, (int, float)):
        return int(round(val))
    limpio = re.sub(r"[^\d]", "", str(val))
    return int(limpio) if limpio else 0

def inferir_metadatos_fuente(nombre_fuente):
    u = norm_txt(nombre_fuente)
    cliente_def = ""
    if u.startswith("ISL"):
        cliente_def = "ISL"
    elif "DIPRECA" in u:
        cliente_def = "DIPRECA"
    elif "ARMADA" in u:
        cliente_def = "Armada de Chile"

    filial_def, soc_def = "", ""
    for claves, nom_f, rut_f in CATALOGO_FILIALES:
        if any(c in u for c in claves):
            filial_def, soc_def = nom_f, rut_f
            break

    anio_match = re.search(r"\b(202[4-9])\b", u)
    anio_def = anio_match.group(1) if anio_match else ""

    tipo_prest_def = ""
    if "PAQUETE" in u:
        tipo_prest_def = "Paquete"
    elif "HMQ" in u:
        tipo_prest_def = "HMQ"

    return {
        "cliente": cliente_def,
        "filial": filial_def,
        "sociedad": soc_def,
        "año": anio_def,
        "tipo_prestación": tipo_prest_def
    }

def mapear_indices_hoja(cabecera):
    cab_norm = [norm_txt(c) for c in cabecera]
    indices = {}

    for col_dest, aliases in ALIAS_COLUMNAS.items():
        aliases_norm = [norm_txt(a) for a in aliases]
        idx_encontrado = None
        for a in aliases_norm:
            if a in cab_norm:
                idx_encontrado = cab_norm.index(a)
                break
        if idx_encontrado is None:
            for a in aliases_norm:
                if len(a) >= 5:
                    for i, c in enumerate(cab_norm):
                        if a in c:
                            idx_encontrado = i
                            break
                if idx_encontrado is not None:
                    break
        if idx_encontrado is not None:
            indices[col_dest] = idx_encontrado

    indices_hmq = {}
    for rol_std, aliases_rol in ROLES_HMQ:
        aliases_r_norm = [norm_txt(a) for a in aliases_rol]
        for i, c in enumerate(cab_norm):
            if any(ar == c or ar in c for ar in aliases_r_norm):
                indices_hmq[rol_std] = i
                break

    return indices, indices_hmq

def obtener_celda(fila, idx_map, clave, default=""):
    idx = idx_map.get(clave)
    if idx is not None and idx < len(fila):
        val = str(fila[idx]).strip()
        if val:
            return val
    return default

# ==========================================
# 3. PROCESAMIENTO Y DESPIVOTADO HMQ
# ==========================================
def procesar_worksheet(ws, etiqueta_origen):
    filas = ws.get_all_values()
    if len(filas) < 2:
        return []

    fila_cab_idx = 0
    for r_i in range(min(4, len(filas))):
        linea_u = " ".join(norm_txt(x) for x in filas[r_i])
        if any(k in linea_u for k in ("FONASA", "GLOSA", "PRESTACION", "CODIGO", "PRECIO", "ARANCEL")):
            fila_cab_idx = r_i
            break

    cabecera = filas[fila_cab_idx]
    idx_map, indices_hmq = mapear_indices_hoja(cabecera)
    meta = inferir_metadatos_fuente(etiqueta_origen)

    es_hoja_hmq = ("HMQ" in norm_txt(etiqueta_origen)) or (len(indices_hmq) >= 2)
    registros_salida = []

    for r in filas[fila_cab_idx + 1:]:
        if not any(str(c).strip() for c in r):
            continue

        glosa_base = obtener_celda(r, idx_map, "glosa_prestación")
        cod_rs = limpiar_codigo_redsalud(obtener_celda(r, idx_map, "código_redsalud [no TC]"))
        cod_cli = obtener_celda(r, idx_map, "código_cliente")
        cod_fon = obtener_celda(r, idx_map, "código_fonasa")

        if not glosa_base and not cod_rs and not cod_fon and not cod_cli:
            continue
        if norm_txt(glosa_base) in ("TOTAL", "SUBTOTAL", "GLOSA", "GLOSA_PRESTACION"):
            continue

        filial = obtener_celda(r, idx_map, "filial", meta["filial"])
        sociedad = obtener_celda(r, idx_map, "sociedad", meta["sociedad"])
        cliente = obtener_celda(r, idx_map, "cliente", meta["cliente"])
        contrato = obtener_celda(r, idx_map, "contrato")
        id_lic = obtener_celda(r, idx_map, "id_licitación")
        centro = obtener_celda(r, idx_map, "centro")
        anio = obtener_celda(r, idx_map, "año", meta["año"])
        tipo_arancel_origen = etiqueta_origen
        tipo_prest = obtener_celda(r, idx_map, "tipo_prestación", meta["tipo_prestación"])
        indexador = obtener_celda(r, idx_map, "Indexador")
        ambito = obtener_celda(r, idx_map, "ámbito")
        recargo = obtener_celda(r, idx_map, "recargo")
        porc_recargo = obtener_celda(r, idx_map, "%_recargo")
        vig_desde = obtener_celda(r, idx_map, "vigencia_desde")
        vig_hasta = obtener_celda(r, idx_map, "vigencia_hasta")
        id_conv_cli = obtener_celda(r, idx_map, "id_convenio_cliente")
        conv_rs = obtener_celda(r, idx_map, "Convenio_redsalud")
        cod_lugar_his = obtener_celda(r, idx_map, "código_lugar_his")

        if es_hoja_hmq and indices_hmq:
            roles_con_valor = []
            for rol_nombre, col_i in indices_hmq.items():
                if col_i < len(r):
                    monto_rol = parsear_monto(r[col_i])
                    if monto_rol > 0:
                        roles_con_valor.append((rol_nombre, monto_rol))

            if roles_con_valor:
                for rol_nombre, monto_rol in roles_con_valor:
                    glosa_rol = f"{glosa_base} - {rol_nombre}".strip(" -")
                    registros_salida.append([
                        filial, sociedad, cliente, contrato, id_lic, centro, anio,
                        tipo_arancel_origen, cod_rs, cod_cli, cod_fon, glosa_rol,
                        "HMQ", indexador, monto_rol, ambito, recargo, porc_recargo,
                        vig_desde, vig_hasta, id_conv_cli, conv_rs, cod_lugar_his
                    ])
                continue

        precio = parsear_monto(obtener_celda(r, idx_map, "precio_total"))
        registros_salida.append([
            filial, sociedad, cliente, contrato, id_lic, centro, anio,
            tipo_arancel_origen, cod_rs, cod_cli, cod_fon, glosa_base,
            tipo_prest, indexador, precio, ambito, recargo, porc_recargo,
            vig_desde, vig_hasta, id_conv_cli, conv_rs, cod_lugar_his
        ])

    return registros_salida

# ==========================================
# 4. ORQUESTADOR MULTI-ARCHIVO EN DRIVE
# ==========================================
def consolidar_aranceles():
    print("=== INICIANDO CONSOLIDACIÓN DE ARANCELES -> RAW_Data_Ingesta (23 COLS) ===", flush=True)
    client, sa_email = obtener_cliente_gspread()
    print(f"Autenticado como: {sa_email}", flush=True)

    libros_drive = client.openall()
    print(f"Archivos compartidos visibles en Drive para la Service Account: {len(libros_drive)}", flush=True)
    for lb in libros_drive:
        print(f"  * Libro disponible: '{lb.title}' (ID: {lb.id})", flush=True)

    # Buscar destino donde está RAW_Data_Ingesta
    ss_dest = None
    ws_dest = None
    for lb in libros_drive:
        w = next((x for x in lb.worksheets() if norm_txt(x.title) == norm_txt(HOJA_DESTINO)), None)
        if w:
            ss_dest = lb
            ws_dest = w
            break
    if not ss_dest:
        ss_dest = client.open_by_key(SPREADSHEET_ID_DESTINO)
        ws_dest = ss_dest.add_worksheet(title=HOJA_DESTINO, rows=500, cols=len(ENCABEZADOS_RAW_INGESTA))

    print(f"Destino seleccionado: '{ss_dest.title}' -> pestaña '{ws_dest.title}'", flush=True)

    todas_las_filas = []
    for fuente in FUENTES_ARANCELES:
        f_norm = norm_txt(fuente)
        # Separar posible nombre de archivo y pestaña ("Archivo - Pestaña")
        partes = [p.strip() for p in fuente.split(" - ", 1)]
        prefijo_archivo = norm_txt(partes[0])
        sufijo_hoja = norm_txt(partes[1]) if len(partes) > 1 else ""

        ws_encontrada = None
        # 1. Buscar como pestaña exacta dentro de cualquier libro compartido
        for lb in libros_drive:
            for w in lb.worksheets():
                w_norm = norm_txt(w.title)
                if w_norm == f_norm or (sufijo_hoja and sufijo_hoja in w_norm and prefijo_archivo[:12] in norm_txt(lb.title)):
                    ws_encontrada = w
                    break
            if ws_encontrada:
                break

        # 2. Si no apareció como pestaña, buscar como libro independiente cuyo título coincida con prefijo_archivo
        if not ws_encontrada:
            for lb in libros_drive:
                lb_norm = norm_txt(lb.title)
                if prefijo_archivo in lb_norm or lb_norm in f_norm:
                    if sufijo_hoja:
                        ws_encontrada = next((w for w in lb.worksheets() if sufijo_hoja in norm_txt(w.title)), lb.sheet1)
                    else:
                        ws_encontrada = lb.sheet1
                    break

        if not ws_encontrada:
            print(f"  [AVISO] Fuente no encontrada en Drive (¿falta compartir?): '{fuente}'", flush=True)
            continue

        filas_f = procesar_worksheet(ws_encontrada, fuente)
        print(f"  -> {fuente}: {len(filas_f)} registros procesados", flush=True)
        todas_las_filas.extend(filas_f)

    ws_dest.clear()
    ws_dest.resize(rows=max(len(todas_las_filas) + 50, 500), cols=len(ENCABEZADOS_RAW_INGESTA))

    matriz_final = [ENCABEZADOS_RAW_INGESTA] + todas_las_filas
    col_fin = gspread.utils.rowcol_to_a1(1, len(ENCABEZADOS_RAW_INGESTA)).replace("1", "")
    ws_dest.update(range_name=f"A1:{col_fin}{len(matriz_final)}", values=matriz_final)

    print(f"=== CONSOLIDACIÓN COMPLETADA: {len(todas_las_filas)} registros en '{HOJA_DESTINO}' (23 columnas: A:{col_fin}) ===", flush=True)

if __name__ == "__main__":
    consolidar_aranceles()

