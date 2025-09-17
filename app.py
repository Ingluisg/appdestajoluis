import streamlit as st
import pandas as pd
from datetime import datetime

# Rutas de los archivos
EXCEL_PATH = "TIEMPOS_DESTAJO_CORE.xlsx"

# Cargar hojas
@st.cache_data
def load_excel(path):
    xls = pd.ExcelFile(path)
    return {sheet: xls.parse(sheet) for sheet in xls.sheet_names}

data = load_excel(EXCEL_PATH)

# --- Configuración de página ---
st.set_page_config(page_title="App de Destajo — Núcleo", layout="wide")
st.title("App de Destajo — Núcleo")

# Hojas disponibles
tabla_df = data["Tabla"]
calendario_df = data["Calendario"]
tiempos_df = data["Tiempos"]

# --- Sección de captura ---
st.subheader("Captura de destajo")

# Desplegable de claves y departamentos desde hoja "Tabla"
clave = st.selectbox("Clave", tabla_df["CLAVE"].dropna().unique())
depto = st.selectbox("Departamento", tabla_df["DEPTO"].dropna().unique())

empleado = st.text_input("Empleado")

# Fecha desde Calendario
dias_disponibles = calendario_df["DIA"].dropna().unique()
dia = st.selectbox("Día", dias_disponibles)

hora_inicio = st.time_input("Hora inicio", value=datetime.strptime("08:00", "%H:%M").time())
hora_fin = st.time_input("Hora fin", value=datetime.strptime("17:00", "%H:%M").time())

piezas = st.number_input("Piezas producidas", min_value=1, step=1)

if st.button("Calcular y guardar"):
    # Buscar el minuto estándar y tarifa en la hoja Tabla
    fila = tabla_df[(tabla_df["CLAVE"] == clave) & (tabla_df["DEPTO"] == depto)]
    
    if not fila.empty:
        minuto_std = float(fila["MINUTO_STD"].values[0])
        tarifa = float(fila["$/HR"].values[0])

        # Calcular tiempos
        minutos_totales = piezas * minuto_std
        pago = (minutos_totales / 60) * tarifa

        st.success(f"Minutos totales: {minutos_totales:.2f} | Pago: ${pago:.2f}")

        # Guardar en hoja Tiempos (en memoria por ahora)
        nuevo = pd.DataFrame([{
            "Empleado": empleado,
            "Clave": clave,
            "Depto": depto,
            "Día": dia,
            "Hora inicio": hora_inicio.strftime("%H:%M"),
            "Hora fin": hora_fin.strftime("%H:%M"),
            "Piezas": piezas,
            "Pago calculado": pago
        }])
        st.dataframe(pd.concat([tiempos_df, nuevo], ignore_index=True))
    else:
        st.error("No se encontró minuto estándar o tarifa para esa combinación.")
