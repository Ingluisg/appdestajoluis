import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import datetime, date, time as _time
import os, unicodedata

# ----- Página -----
st.set_page_config(page_title="App de Destajo — Núcleo (Móvil)", layout="wide")
st.title("App de Destajo — Núcleo")
st.caption("Optimizada para móviles. Solo **Tiempos**, **Tabla** y **Calendario**.")

# ----- Constantes -----
EXCEL_PATH = "TIEMPOS_DESTAJO_CORE.xlsx"
BITACORA_PATH = "bitacora_cambios.csv"
VALID_SHEETS = ["Tiempos","Tabla","Calendario"]

MASTER_USER = "master"
MASTER_PASS = st.secrets.get("MASTER_PASS", "master1234")

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

# ----- Verifica Excel y carga -----
if not os.path.exists(EXCEL_PATH):
    st.error(f"No existe el archivo **{EXCEL_PATH}** en la raíz del repo.")
    st.stop()

data = load_book(EXCEL_PATH)   # <--- IMPORTANTE: data se define aquí ✅
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
    st.error("No encuentro la columna **CLAVE** en 'Tabla'. "
             "Revisa que alguna fila de encabezados contenga 'CLAVE'.")
    st.stop()

# 2) Construir cabeceras y cuerpo
tabla_headers = tabla_raw.iloc[header_row].tolist()
tabla_norm = tabla_raw.iloc[header_row+1:].copy()
tabla_norm.columns = tabla_headers

# 3) Detectar columnas reales
col_clave = match_col(tabla_norm.columns, "CLAVE")
col_desc  = match_col(tabla_norm.columns, "DESCRIPCION")  # cubre DESCRIPCIÓN
if not col_clave:
    st.error("Detecté la fila de títulos, pero no aparece la columna **CLAVE** entre: "
             + ", ".join(map(str, tabla_norm.columns)))
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

# (Opcional) Depuración
st.caption(f"🧭 Encabezados detectados en 'Tabla' (fila {header_row}): " + ", ".join(map(str, tabla_norm.columns)))
st.caption(f"Usando → CLAVE: **{col_clave}** | DESCRIPCIÓN: **{col_desc or '—'}** | Deptos: {', '.join(depto_options[:6])}…")
