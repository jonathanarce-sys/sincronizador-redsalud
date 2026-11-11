TypeError: Object of type Timestamp is not JSON serializable
```[cite: 15]

---

### Diagnóstico del error

1. **Columnas con Fechas (`Timestamp`):**  
   Los archivos de aranceles (especialmente el archivo Excel de DIPRECA) contienen celdas de fechas. Pandas las interpreta internamente como objetos `pd.Timestamp`, los cuales no pueden ser convertidos directamente a texto JSON por la API de Google Sheets[cite: 15].
2. **Duplicidad de archivos:**  
   En la lista de archivos detectados están tanto `DIPRECA ... .xlsx` (14.641 filas) como `DIPRECA ... 2026_Prestaciones (2).csv` (14.641 filas)[cite: 14]. Ambas versiones estaban sumando **33.658 filas** en total para insertar[cite: 14].
3. **Volumen de envío:**  
   Subir más de 30.000 filas en un solo paquete directo suele provocar bloqueos de memoria o límites de tamaño en Google Sheets. Se debe enviar en bloques (lotes de 5.000 filas).

---

### Código corregido para `sync_aranceles.py`

Reemplaza todo el contenido de **`sync_aranceles.py`** en tu repositorio con esta versión:

```python
import os
import glob
import json
import base64
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID_MAESTRA = "1qxeY4CQN-g-bHqbfEpr2MjQXzObpNG5fSxThqexbXHo"
HOJA_DESTINO = "RAW_DATA_INGESTA"
CARPETA_RAW = "data/raw"
FILA_INICIO = 19019
BATCH_SIZE = 5000  # Envío en bloques para estabilidad de la API

def obtener_cliente_gspread():
    posibles = ["GCP_SA_KEY", "GCP_JSON_BASE64", "GCP_SERVICE_ACCOUNT", "GOOGLE_CREDENTIALS", "GCP_JSON"]
    val = None
    for k in posibles:
        if k in os.environ and os.environ[k].strip():
            val = os.environ[k].strip()
            break
            
    if not val:
        raise ValueError("No se encontraron credenciales de Google Cloud en GitHub Secrets.")

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
    return gspread.authorize(Credentials.from_service_account_info(creds_dict, scopes=scopes))

def formatear_valor(x):
    """Convierte timestamps, nulos y tipos no serializables a texto o formatos estándar."""
    if pd.isna(x):
        return ""
    if isinstance(x, (pd.Timestamp, pd.DatetimeIndex)):
        return x.strftime("%d-%m-%Y")
    return str(x) if isinstance(x, (float, int)) and pd.isna(x) else x

def sincronizar_aranceles():
    print("Conectando con Google Sheets...")
    client = obtener_cliente_gspread()
    ss = client.open_by_key(SPREADSHEET_ID_MAESTRA)
    
    ws = None
    objetivo = HOJA_DESTINO.strip().lower()
    for w in ss.worksheets():
        if w.title.strip().lower() == objetivo:
            ws = w
            break

    if not ws:
        raise ValueError(f"No se encontró la hoja '{HOJA_DESTINO}'.")

    print(f"Pestaña identificada con éxito: '{ws.title}'")

    patron = os.path.join(CARPETA_RAW, "*")
    archivos = [f for f in glob.glob(patron) if not os.path.basename(f).startswith(".")]
    print(f"Archivos encontrados para ingesta: {[os.path.basename(x) for x in archivos]}")

    if not archivos:
        print("No se encontraron archivos en data/raw para anexar.")
        return

    registros = []
    max_cols = 0

    for f in archivos:
        print(f"Leyendo: {os.path.basename(f)}")
        if f.lower().endswith(".csv"):
            try:
                df = pd.read_csv(f, sep=None, engine="python", encoding="utf-8")
            except Exception:
                df = pd.read_csv(f, sep=None, engine="python", encoding="latin1")
        else:
            df = pd.read_excel(f)

        # Formateo de fechas a string (elimina el error Timestamp not JSON serializable)
        df = df.apply(lambda col: col.map(formatear_valor))
        df = df.fillna("")
        
        datos = df.values.tolist()
        if datos:
            max_cols = max(max_cols, len(datos[0]))
            registros.extend(datos)
            print(f" -> {len(datos)} filas procesadas de {os.path.basename(f)}")

    if not registros:
        print("No hay filas con datos para anexar.")
        return

    total_filas = len(registros)
    fila_fin = FILA_INICIO + total_filas - 1
    col_fin = gspread.utils.rowcol_to_a1(1, max_cols).replace("1", "")

    # Validar capacidad de filas
    if ws.row_count < fila_fin:
        filas_agregar = (fila_fin - ws.row_count) + 500
        print(f"Expandiendo hoja en {filas_agregar} filas...")
        ws.add_rows(filas_agregar)

    print(f"Insertando {total_filas} filas por lotes desde la fila {FILA_INICIO}...")

    # Escritura por bloques
    for i in range(0, total_filas, BATCH_SIZE):
        bloque = registros[i:i + BATCH_SIZE]
        f_inicio = FILA_INICIO + i
        f_termino = f_inicio + len(bloque) - 1
        rango_bloque = f"A{f_inicio}:{col_fin}{f_termino}"
        print(f"  Escribiendo bloque: {rango_bloque} ({len(bloque)} registros)...")
        ws.update(range_name=rango_bloque, values=bloque)

    print(f"Éxito: Se anexaron {total_filas} filas respetando las 19018 previas.")

if __name__ == "__main__":
    sincronizar_aranceles()
