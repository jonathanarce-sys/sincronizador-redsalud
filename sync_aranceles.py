import pandas as pd

ARCHIVO_DIPRECA = "data/raw/DIPRECA _ Arancel Consolidado [Clientes Sector Público].xlsx"
HOJAS_REQUERIDAS = ["2026_Prestaciones", "2026_Paquetes", "2026_HMQ"]

def extraer_hojas_dipreca(ruta_archivo):
    xl = pd.ExcelFile(ruta_archivo)
    print("Hojas disponibles en el archivo:", xl.sheet_names)
    
    datos_extraidos = {}
    
    for hoja in HOJAS_REQUERIDAS:
        # Búsqueda tolerante por si los nombres traen espacios adicionales
        nombre_real = next((s for s in xl.sheet_names if s.strip().lower() == hoja.strip().lower()), None)
        
        if nombre_real:
            print(f"Cargando hoja: {nombre_real}...")
            df = pd.read_excel(xl, sheet_name=nombre_real, dtype=object)
            df = df.fillna("")
            
            # Etiqueta de trazabilidad para saber a qué sección de DIPRECA corresponde cada fila
            df["tipo_arancel_dipreca"] = hoja
            
            datos_extraidos[hoja] = df
            print(f" -> {len(df)} registros cargados de {hoja}. Columnas: {list(df.columns[:5])}...")
        else:
            print(f"Aviso: La hoja '{hoja}' no se encontró en el archivo.")
            
    return datos_extraidos

if __name__ == "__main__":
    tablas = extraer_hojas_dipreca(ARCHIVO_DIPRECA)
