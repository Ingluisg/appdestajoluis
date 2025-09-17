# app.py — versión completa
import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import datetime, date, time as _time
import os, unicodedata

# ----- Página -----
st.set_page_config(page_title="App de Destajo — Núcleo (Móvil)", layout="wide")
st.title("App de Destajo — Núcleo")
st.caption("Optimizada para móviles. Solo **Tiempos**, **Tabla** y **Calendario**. Captura igual al Excel y cálculos de destajo sin añadir columnas nuevas.")

# ----- Constantes -----
EXCEL_PATH = "TIEMPOS_DESTAJO_CORE.xlsx"
BITACORA_PATH = "bitacora_cambios.csv"
VALID_SHEETS = ["Tiempos","Tabla","Calendario"]

MASTER_USER = "master"
MASTER_PASS = st.secrets.get("MASTER_PASS","master1234")

# ----- Utils -----
def _norm(s: str) -> str:
    s = str(s).strip().lower()
    s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    return s

def match_col(cols, target):
    t = _norm(target)
    for c in cols:
        if _norm(c) == t:
            return c
    return None

@st.cache_data
def load_book(path):
    xls = pd.ExcelFile(path)
    return {s: xls.parse(s) for s in xls.sheet_names if s in VALID_SHEETS}

def to_excel_bytes(dfs):
    out = BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        for n in VALID_SHEETS:
            if n in dfs:
                dfs[n].to_excel(w, sheet_name=n, index=False)
    return out.getvalue()

def append_bitacora(accion, hoja, detalle=""):
    ts = datetime.now().isoformat(timespec="seconds")
    row = {"timestamp": ts, "usuario": MASTER_USER, "accion": accion, "hoja": hoja, "detalle": detalle}
    try:
        if os.path.exists(BITACORA_PATH):
            df = pd.read_csv(BITACORA_PATH)
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        else:
            df = pd.DataFrame([row])
        df.to_csv(BITACORA_PATH, index=False)
    except Exception as e:
        st.warning(f"No se pudo registrar en bitácora: {e}")

def detect_fecha_column(df: pd.DataFrame):
    for c in df.columns:
        try:
            if pd.api.types.is_datetime64_any_dtype(df[c]):
                return c
        except Exception:
            pass
    for c in df.columns:
        name = _norm(c)
        if "fecha" in name or "dia" in name or "día" in name:
            return c
    for c in df.columns:
        try:
            if pd.to_datetime(df[c], errors="coerce").notna().sum()>0:
                return c
        except Exception:
            pass
    return None

def detect_time_column(df: pd.DataFrame, key_words=("hora i","hora inicio","inicio","entrada")):
    lk = [_norm(k) for k in key_words]
    for c in df.columns:
        name = _norm(c)
        if any(k in name for k in lk):
            return c
    return None

def detect_time_end_column(df: pd.DataFrame, key_words=("hora f","hora fin","fin","salida")):
    lk = [_norm(k) for k in key_words]
    for c in df.columns:
        name = _norm(c)
        if any(k in name for k in lk):
            return c
    return None

# ----- Verifica Excel y carga -----
if not os.path.exists(EXCEL_PATH):
    st.error(f"No existe el archivo **{EXCEL_PATH}** en la raíz del repo.")
    st.stop()

data = load_book(EXCEL_PATH)
st.caption("Hojas cargadas: " + ", ".join(list(data.keys())))

# ====================== Preparar TABLA (robusto) ======================
tabla_raw = data.get("Tabla")
if tabla_raw is None or len(tabla_raw) == 0:
    st.error("No se pudo leer la hoja **'Tabla'**.")
    st.stop()

# 1) Buscar la fila que contiene el encabezado 'CLAVE' en las primeras 10 filas
header_row = None
max_scan = min(10, len(tabla_raw))
for r in range(max_scan):
    row_vals = [_norm(v) for v in tabla_raw.iloc[r].tolist()]
    if "clave" in row_vals:
        header_row = r
        break

if header_row is None:
    st.error("No encuentro la columna **CLAVE** en 'Tabla'. Revisa que alguna fila de encabezados contenga 'CLAVE'.")
    st.stop()

# 2) Construir cabeceras y cuerpo
tabla_headers = tabla_raw.iloc[header_row].tolist()
tabla_norm = tabla_raw.iloc[header_row+1:].copy()
tabla_norm.columns = tabla_headers

# 3) Detectar columnas reales
col_clave = match_col(tabla_norm.columns, "CLAVE")
col_desc  = match_col(tabla_norm.columns, "DESCRIPCION")  # también cubre “DESCRIPCIÓN”
if not col_clave:
    st.error("Detecté la fila de títulos, pero no aparece la columna **CLAVE** entre: " + ", ".join(map(str, tabla_norm.columns)))
    st.stop()

# 4) Columnas de departamentos (numéricas y que no son clave/descripcion)
ignore = {"clave","descripcion","descripción","modelo","observaciones","obs"}
depto_options = []
for c in tabla_norm.columns:
    name = _norm(c)
    if name not in ignore and str(c) not in ("CLAVE","DESCRIPCION"):
        try:
            vals = pd.to_numeric(tabla_norm[c], errors="coerce")
            if vals.notna().sum() > 0:
                depto_options.append(str(c))
        except Exception:
            pass
depto_options = sorted(list(dict.fromkeys(depto_options)))

# 5) Claves disponibles
claves = [str(c).strip() for c in tabla_norm[col_clave].dropna().astype(str).tolist() if str(c).strip()]

# Depuración visible
st.caption(f"🧭 Encabezados detectados en 'Tabla' (fila {header_row}): " + ", ".join(map(str, tabla_norm.columns)))
st.caption(f"Usando → CLAVE: **{col_clave}** | DESCRIPCIÓN: **{col_desc or '—'}** | Deptos: {', '.join(depto_options[:6])}…")

# ====================== Preparar CALENDARIO ======================
cal = data.get("Calendario")
fecha_opts = []
hora_i_col = hora_f_col = None
if cal is not None and len(cal) > 0:
    fcol = detect_fecha_column(cal)
    if fcol:
        fser = pd.to_datetime(cal[fcol], errors="coerce").dt.date.dropna()
        fecha_opts = sorted(fser.unique().tolist())
    hora_i_col = detect_time_column(cal)
    hora_f_col = detect_time_end_column(cal)

# ====================== Preparar tarifas $/hr desde TIEMPOS ======================
rate_map = {}
try:
    t_raw = data.get("Tiempos")
    ti_heads = t_raw.iloc[0]
    ti = t_raw.iloc[1:].copy()
    ti.columns = ti_heads
    tmp = ti[["DEPARTAMENTOS","$/hr"]].dropna()
    tmp["DEPARTAMENTOS"] = tmp["DEPARTAMENTOS"].astype(str).str.strip()
    rate_map = tmp.groupby("DEPARTAMENTOS")["$/hr"].mean().to_dict()
except Exception:
    pass

# ====================== Tabs UI ======================
tabs = st.tabs(VALID_SHEETS)

# ---------------------- Tiempos (Captura) ----------------------
with tabs[0]:
    st.subheader("Captura rápida (igual a Excel)")

    c1,c2,c3 = st.columns(3)
    clave = c1.selectbox("CLAVE", options=claves, placeholder="Selecciona la clave")
    depto = c2.selectbox("DEPTO", options=depto_options or ["COSTURA","TAPIZ","ARMADO","CARPINTERIA"], placeholder="Selecciona el departamento")
    empleado = c3.text_input("Empleado / Operador")

    c4,c5,c6 = st.columns(3)
    if fecha_opts:
        dia = c4.selectbox("Día (desde Calendario)", options=fecha_opts, index=len(fecha_opts)-1)
    else:
        dia = c4.date_input("Día", value=date.today())

    # Horas por defecto desde Calendario si existen
    def_hi, def_hf = _time(8,0), _time(17,0)
    try:
        if fecha_opts and hora_i_col and hora_f_col:
            row = cal.loc[pd.to_datetime(cal[detect_fecha_column(cal)], errors="coerce").dt.date == dia]
            if not row.empty:
                hi = row.iloc[0][hora_i_col]; hf = row.iloc[0][hora_f_col]
                if pd.notna(hi): def_hi = pd.to_datetime(str(hi)).time()
                if pd.notna(hf): def_hf = pd.to_datetime(str(hf)).time()
    except Exception:
        pass
    hora_i = c5.time_input("Hora inicio", value=def_hi)
    hora_f = c6.time_input("Hora fin", value=def_hf)

    c7,_,_ = st.columns(3)
    produce = c7.number_input("Piezas producidas", min_value=1, value=1, step=1)

    # Lookup Min Std (Tabla) + Tarifa (Tiempos)
    std_min = None
    modelo = None
    dcol = match_col(tabla_norm.columns, depto)
    if dcol is not None and clave:
        sel = tabla_norm.loc[tabla_norm[col_clave].astype(str) == str(clave), dcol].dropna()
        if len(sel):
            std_min = float(sel.iloc[0])
        if col_desc:
            md = tabla_norm.loc[tabla_norm[col_clave].astype(str) == str(clave), col_desc].dropna()
            if len(md):
                modelo = str(md.iloc[0])

    tarifa = rate_map.get(depto)
    if tarifa is None:
        tarifa = {_norm(k):v for k,v in rate_map.items()}.get(_norm(depto))

    st.caption(f"Min Std: **{std_min if std_min is not None else '—'}** | $/hr: **{tarifa if tarifa is not None else '—'}**")

    if st.button("Calcular y guardar en 'Tiempos'", use_container_width=True):
        import datetime as _dt
        t1 = _dt.datetime.combine(dia, hora_i)
        t2 = _dt.datetime.combine(dia, hora_f)
        total_secs = max(0, int((t2 - t1).total_seconds()))
        total_min = total_secs/60
        unit_min = total_min/produce if produce>0 else None
        eficiencia = round(std_min/unit_min, 6) if (std_min and unit_min) else None
        destajo_unit = round(tarifa/60*std_min, 6) if (tarifa is not None and std_min is not None) else None
        destajo_total = round(destajo_unit*produce, 6) if destajo_unit is not None else None

        if std_min is None or tarifa is None:
            st.error("No se encontró **Min Std** o **$/hr** para esa CLAVE/DEPTO. Revisa 'Tabla' y 'Tiempos'.")
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
            setif("Produce", produce)
            setif("Día I", dia)
            setif("Hora I", hora_i)
            setif("Dia F", dia)
            setif("Hora F", hora_f)
            setif("Minutos\nStd\n", std_min)
            setif("Tiempo\nUnitario\nMinutos", round(unit_min,6) if unit_min is not None else None)
            setif("Eficiencia", eficiencia)
            setif("Destajo\nUnitario\n", destajo_unit)
            setif("Total Hr", f"{int(total_min//60):02d}:{int(total_min%60):02d}:00")
            setif("Min", int(total_min)); setif("Seg", total_secs%60); setif("Tot Seg", total_secs)

            nuevo = pd.DataFrame([new_row])
            data["Tiempos"] = pd.concat([traw, nuevo], ignore_index=True)

            with open(EXCEL_PATH,"wb") as f:
                f.write(to_excel_bytes(data))

            append_bitacora("captura_rapida","Tiempos", f"clave={clave}, depto={depto}, pzas={produce}, unit={destajo_unit}, total={destajo_total}")
            st.success(f"✅ Guardado | Destajo unit: {destajo_unit} | Destajo total: {destajo_total}")

    st.markdown("**Vista de la hoja 'Tiempos' (actual):**")
    st.dataframe(data["Tiempos"], use_container_width=True, height=320)

# ---------------------- Tabla ----------------------
with tabs[1]:
    st.subheader("Tabla")
    st.dataframe(tabla_norm, use_container_width=True, height=450)
    st.caption("Las columnas de departamento (ej. COSTURA, TAPIZ, ARMADO…) se usan para el cálculo de Min Std.")

# ---------------------- Calendario ----------------------
with tabs[2]:
    st.subheader("Calendario")
    if cal is not None:
        st.dataframe(cal, use_container_width=True, height=450)
        st.caption("El selector de día (y horas si existen) se alimenta desde aquí.")
    else:
        st.info("No se encontró la hoja 'Calendario'.")

# ---------------------- Descargas ----------------------
st.markdown("---")
c1, c2 = st.columns(2)
with c1:
    st.download_button("Descargar Excel (3 hojas)",
                       to_excel_bytes(data),
                       file_name="TIEMPOS_DESTAJO_CORE_actualizado.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       use_container_width=True)
with c2:
    if os.path.exists(BITACORA_PATH):
        bit = pd.read_csv(BITACORA_PATH)
        st.download_button("Descargar Bitácora (CSV)",
                           bit.to_csv(index=False).encode("utf-8"),
                           file_name="bitacora_cambios.csv",
                           mime="text/csv",
                           use_container_width=True)
