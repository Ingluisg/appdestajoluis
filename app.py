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
# ---------- Captura de destajo (robusta) ----------
st.subheader("Captura de destajo")

def ilike(s): return str(s).strip().lower()

# 1) Normalizar TABLA (cabeceras en fila 0, datos desde fila 2)
raw_tabla = data["Tabla"]
tabla_headers = raw_tabla.iloc[0].tolist()         # fila con títulos “reales”
tabla_norm = raw_tabla.iloc[2:].copy()
tabla_norm.columns = tabla_headers

# Columnas de departamentos = todas las que NO son clave/descripcion y contienen números
ignore = {"clave","descripción","descripcion","modelo","observaciones","obs"}
deptos = []
for c in tabla_norm.columns:
    name = ilike(c)
    if name not in ignore and c not in ("CLAVE","DESCRIPCION"):
        try:
            if pd.to_numeric(tabla_norm[c], errors="coerce").notna().any():
                deptos.append(str(c))
        except Exception:
            pass
deptos = sorted(list(dict.fromkeys(deptos)))  # únicos

# 2) Claves disponibles
claves = [c for c in tabla_norm["CLAVE"].dropna().astype(str).tolist() if c.strip()]

# 3) Calendario (fecha y horas)
cal = data["Calendario"]
# detectar columna de fecha en Calendario
def detect_fecha_column(df):
    for col in df.columns:
        try:
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                return col
        except Exception:
            pass
    for col in df.columns:
        if "fecha" in ilike(col) or "día" in ilike(col) or "dia" in ilike(col):
            return col
    for col in df.columns:
        try:
            if pd.to_datetime(df[col], errors="coerce").notna().sum()>0:
                return col
        except Exception:
            pass
    return None

fcol = detect_fecha_column(cal)
dias = []
if fcol:
    dias = sorted(pd.to_datetime(cal[fcol], errors="coerce").dt.date.dropna().unique().tolist())

def find_col(df, keywords):
    ks = [ilike(k) for k in keywords]
    for c in df.columns:
        name = ilike(c)
        if any(k in name for k in ks):
            return c
    return None

hora_i_col = find_col(cal, ["hora i","hora inicio","inicio","entrada"])
hora_f_col = find_col(cal, ["hora f","hora fin","fin","salida"])

# 4) Tarifa $/hr por DEPTO desde hoja Tiempos
t_raw = data["Tiempos"]
ti_heads = t_raw.iloc[0]
ti = t_raw.iloc[1:].copy()
ti.columns = ti_heads
tmp = ti[["DEPARTAMENTOS","$/hr"]].dropna()
tmp["DEPARTAMENTOS"] = tmp["DEPARTAMENTOS"].astype(str).str.strip()
rate_map = tmp.groupby("DEPARTAMENTOS")["$/hr"].mean().to_dict()

# ---------- Formulario ----------
c1,c2,c3 = st.columns(3)
clave = c1.selectbox("CLAVE", claves, placeholder="Selecciona la clave")
depto = c2.selectbox("DEPTO", deptos, placeholder="Selecciona el depto")
empleado = c3.text_input("Empleado / Operador")

c4,c5,c6 = st.columns(3)
if dias:
    dia = c4.selectbox("Día (desde Calendario)", options=dias, index=len(dias)-1)
else:
    dia = c4.date_input("Día")

# Horas desde Calendario si existen
from datetime import time as _time
def_hora_i, def_hora_f = _time(8,0), _time(17,0)
try:
    if dias and hora_i_col and hora_f_col:
        row = cal.loc[pd.to_datetime(cal[fcol], errors="coerce").dt.date == dia]
        if not row.empty:
            hi = row.iloc[0][hora_i_col]; hf = row.iloc[0][hora_f_col]
            if pd.notna(hi): def_hora_i = pd.to_datetime(str(hi)).time()
            if pd.notna(hf): def_hora_f = pd.to_datetime(str(hf)).time()
except Exception:
    pass

hora_i = c5.time_input("Hora inicio", value=def_hora_i)
hora_f = c6.time_input("Hora fin", value=def_hora_f)

c7,c8,_ = st.columns(3)
piezas = c7.number_input("Piezas producidas", min_value=1, value=1, step=1)

# ---------- Lookup Min Std (Tabla) + Tarifa (Tiempos) ----------
# depto puede venir en mayúsc/minúsc/espacios → empatar a columna real
def match_col(cols, target):
    t = ilike(target)
    for c in cols:
        if ilike(c) == t:
            return c
    return None

dcol = match_col(tabla_norm.columns, depto)
min_std = None
modelo = None
if dcol is not None and clave:
    sel = tabla_norm.loc[tabla_norm["CLAVE"].astype(str)==str(clave), dcol].dropna()
    if len(sel): min_std = float(sel.iloc[0])
    # modelo/descripción si existe
    try:
        dcol_desc = match_col(tabla_norm.columns, "descripcion")
        if dcol_desc:
            m = tabla_norm.loc[tabla_norm["CLAVE"].astype(str)==str(clave), dcol_desc].dropna()
            if len(m): modelo = str(m.iloc[0])
    except Exception:
        pass

# Tarifa $/hr (case-insensitive)
tarifa = rate_map.get(depto)
if tarifa is None:
    tarifa = {ilike(k):v for k,v in rate_map.items()}.get(ilike(depto))

st.caption(f"Min Std: **{min_std if min_std is not None else '—'}** | $/hr: **{tarifa if tarifa is not None else '—'}**")

# ---------- Calcular + Guardar ----------
if st.button("Calcular y guardar en 'Tiempos'", use_container_width=True):
    import datetime as _dt
    t1 = _dt.datetime.combine(dia, hora_i)
    t2 = _dt.datetime.combine(dia, hora_f)
    total_secs = max(0, int((t2 - t1).total_seconds()))
    total_min = total_secs/60
    unit_min = total_min/piezas if piezas>0 else None
    eficiencia = round(min_std/unit_min, 6) if (min_std and unit_min) else None
    destajo_unit = round(tarifa/60*min_std, 6) if (tarifa is not None and min_std is not None) else None
    destajo_total = round(destajo_unit*piezas, 6) if destajo_unit is not None else None

    if min_std is None or tarifa is None:
        st.error("Falta Min Std o $/hr para esa CLAVE/DEPTO. Revisa 'Tabla' y 'Tiempos'.")
    else:
        traw = data["Tiempos"]
        heads = traw.iloc[0].tolist()
        new_row = {h: None for h in heads}
        def setif(k,v): 
            if k in new_row: new_row[k]=v
        setif("CLAVE", clave)
        setif("DEPTO", depto)
        setif("EMPLEADO", empleado)
        setif("MODELO", modelo)
        setif("Produce", piezas)
        setif("Día I", dia)
        setif("Hora I", hora_i)
        setif("Dia F", dia)
        setif("Hora F", hora_f)
        setif("Minutos\nStd\n", min_std)
        setif("Tiempo\nUnitario\nMinutos", round(unit_min,6) if unit_min is not None else None)
        setif("Eficiencia", eficiencia)
        setif("Destajo\nUnitario\n", destajo_unit)
        setif("Total Hr", f"{int(total_min//60):02d}:{int(total_min%60):02d}:00")
        setif("Min", int(total_min)); setif("Seg", total_secs%60); setif("Tot Seg", total_secs)

        nuevo = pd.DataFrame([new_row])
        data["Tiempos"] = pd.concat([traw, nuevo], ignore_index=True)

        # Guardar libro completo
        from io import BytesIO
        buf = BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            for s in data:
                data[s].to_excel(w, sheet_name=s, index=False)
        with open(EXCEL_PATH, "wb") as f:
            f.write(buf.getvalue())

        st.success(f"OK: Destajo unit {destajo_unit} | Total {destajo_total}")
