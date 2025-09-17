import streamlit as st
import pandas as pd
import os
from io import BytesIO
from datetime import datetime

st.set_page_config(page_title="App de Destajo — Núcleo (Móvil)", layout="wide")

EXCEL_PATH = "TIEMPOS_DESTAJO_CORE.xlsx"
BITACORA_PATH = "bitacora_cambios.csv"
VALID_SHEETS = ["Tiempos", "Tabla", "Calendario"]

MASTER_USER = "master"
MASTER_PASS = st.secrets.get("MASTER_PASS", "master1234")

# Cargar datos
@st.cache_data
def load_book(path):
    xls = pd.ExcelFile(path)
    data = {s: pd.read_excel(path, sheet_name=s) for s in xls.sheet_names if s in VALID_SHEETS}
    return data

def save_book(data, path):
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet, df in data.items():
            df.to_excel(writer, sheet_name=sheet, index=False)

def log_action(user, action):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if os.path.exists(BITACORA_PATH):
        log = pd.read_csv(BITACORA_PATH)
    else:
        log = pd.DataFrame(columns=["timestamp","user","action"])
    log.loc[len(log)] = [now,user,action]
    log.to_csv(BITACORA_PATH,index=False)

book = load_book(EXCEL_PATH)
tiempos = book["Tiempos"]
tabla = book["Tabla"]

st.sidebar.title("Acceso")
modo = st.sidebar.radio("Modo", ["Usuario", "Máster"])
if modo == "Máster":
    user = st.text_input("Usuario", value="")
    pwd = st.text_input("Contraseña", type="password")
    if user == MASTER_USER and pwd == MASTER_PASS:
        st.sidebar.success("Acceso concedido")
        master = True
    else:
        st.sidebar.error("Acceso denegado")
        master = False
else:
    master = False

st.title("App de Destajo — Núcleo")
st.caption("Optimizada para móviles.")

tabs = st.tabs(["Tiempos", "Tabla", "Calendario"])

# ---- TIEMPOS ----
with tabs[0]:
    st.subheader("Captura rápida (igual a Excel)")

    col1, col2 = st.columns(2)
    with col1:
        clave = st.text_input("CLAVE (ej. GMARIE2)").strip()
        depto = st.text_input("DEPTO (ej. COSTURA)").strip()
        empleado = st.text_input("Empleado").strip()
        produce = st.number_input("Piezas producidas", min_value=1, value=1)
    with col2:
        modelo = st.text_input("Modelo").strip()
        dia_i = st.date_input("Día inicio")
        hora_i = st.time_input("Hora inicio")
        dia_f = st.date_input("Día fin")
        hora_f = st.time_input("Hora fin")

    if st.button("Calcular y guardar en 'Tiempos'"):
        # Buscar minuto estándar en Tabla
        std = None
        try:
            row = tabla.loc[tabla["CLAVE"].astype(str).str.strip() == clave]
            if not row.empty and depto in row.columns:
                std = float(row[depto].values[0])
        except Exception:
            pass

        # Buscar $/hr en Tiempos base
        try:
            base = tiempos[["DEPARTAMENTOS","$/hr"]].dropna()
            rate = base.loc[base["DEPARTAMENTOS"].astype(str).str.contains(depto, case=False), "$/hr"].values[0]
        except:
            rate = 0

        if std and rate:
            dest_unit = (rate/60.0) * std
            dest_total = dest_unit * produce
            st.success(f"Destajo unitario: ${dest_unit:.2f} | Total: ${dest_total:.2f}")

            # Guardar en Tiempos
            new_row = {
                "CLAVE": clave, "DEPTO": depto, "EMPLEADO": empleado,
                "MODELO": modelo, "Produce": produce,
                "Dia I": dia_i, "Hora I": hora_i.strftime("%H:%M:%S"),
                "Dia F": dia_f, "Hora F": hora_f.strftime("%H:%M:%S"),
                "Minutos Std": std, "$/hr": rate,
                "Destajo Unitario": dest_unit, "Destajo Total": dest_total
            }
            tiempos = pd.concat([tiempos, pd.DataFrame([new_row])], ignore_index=True)
            book["Tiempos"] = tiempos
            save_book(book, EXCEL_PATH)
            log_action(modo, f"Captura {empleado} {produce} piezas clave {clave}")
        else:
            st.error("No se encontró minuto estándar o tarifa $/hr para esa combinación.")

    st.subheader("Vista completa de Tiempos")
    st.dataframe(tiempos, use_container_width=True)

# ---- TABLA ----
with tabs[1]:
    st.dataframe(tabla, use_container_width=True)

# ---- CALENDARIO ----
with tabs[2]:
    st.dataframe(book["Calendario"], use_container_width=True)

# ---- BITÁCORA ----
st.sidebar.subheader("Bitácora")
if os.path.exists(BITACORA_PATH):
    log = pd.read_csv(BITACORA_PATH)
    st.sidebar.dataframe(log, height=200)
else:
    st.sidebar.write("Aún no hay bitácora.")
