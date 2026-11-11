File "/home/runner/.../sync_aranceles.py", line 1
  File "/home/runner/.../sync_aranceles.py", line 11
SyntaxError: invalid syntax
```[cite: 20]

Esto ocurrió porque en la **línea 1** de `sync_aranceles.py` quedó pegado el propio mensaje de error de la terminal (`File ".../sync_aranceles.py"`)[cite: 20]. Python intenta ejecutar ese texto en la primera línea y se detiene de inmediato por sintaxis inválida[cite: 20].

---

### Solución

1. Ve a tu repositorio en GitHub y abre **`sync_aranceles.py`**[cite: 20].
2. Haz clic en el ícono del **lápiz** (Edit this file).
3. Selecciona **todo el texto** (`Ctrl + A` en Windows o `Cmd + A` en Mac) y presiona **Supr / Delete** para dejar el editor completamente en blanco[cite: 20].
4. Pega exactamente el siguiente código (que inicia formalmente con `import os` en la línea 1):

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
BATCH_SIZE = 5000

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

        # Convierte todos los valores a texto para prevenir errores de tipo Timestamp en el JSON
        df = df.astype(str).replace({"nan": "", "NaT": "", "None": ""})
        
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

    if ws.row_count < fila_fin:
        filas_agregar = (fila_fin - ws.row_count) + 500
        print(f"Expandiendo hoja en {filas_agregar} filas...")
        ws.add_rows(filas_agregar)

    print(f"Insertando {total_filas} filas por lotes desde la fila {FILA_INICIO}...")

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
