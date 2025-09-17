# ====================== Preparar TABLA (robusto) ======================
import unicodedata
def _norm(s: str) -> str:
    s = str(s).strip().lower()
    s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    return s

tabla_raw = data.get("Tabla")
if tabla_raw is None or len(tabla_raw) == 0:
    st.error("No se pudo leer la hoja **'Tabla'**.")
    st.stop()

# 1) Encontrar la fila que contiene el encabezado "CLAVE"
header_row = None
max_scan = min(10, len(tabla_raw))  # escaneamos las primeras 10 filas como máximo
for r in range(max_scan):
    row_vals = [ _norm(v) for v in tabla_raw.iloc[r].tolist() ]
    if "clave" in row_vals:
        header_row = r
        break

if header_row is None:
    st.error("No encuentro la columna **CLAVE** en la hoja 'Tabla'. "
             "Revisa que alguna de las primeras filas contenga 'CLAVE'.")
    st.stop()

# 2) Construir cabeceras y cuerpo
tabla_headers = tabla_raw.iloc[header_row].tolist()
tabla_norm = tabla_raw.iloc[header_row+1:].copy()
tabla_norm.columns = tabla_headers

# 3) Detectar nombres reales de columnas (CLAVE / DESCRIPCIÓN)
def match_col(cols, target):
    t = _norm(target)
    for c in cols:
        if _norm(c) == t:
            return c
    return None

col_clave = match_col(tabla_norm.columns, "CLAVE")
col_desc  = match_col(tabla_norm.columns, "DESCRIPCION")  # cubre DESCRIPCIÓN

if not col_clave:
    st.error("Detecté la fila de títulos, pero no aparece la columna **CLAVE** entre: "
             + ", ".join(map(str, tabla_norm.columns)))
    st.stop()

# 4) Columnas de departamento = numéricas que NO son clave/descripcion
ignore = {"clave", "descripcion", "descripción", "modelo", "observaciones", "obs"}
depto_options = []
for c in tabla_norm.columns:
    name = _norm(c)
    if name not in ignore and str(c) not in ("CLAVE", "DESCRIPCION"):
        try:
            vals = pd.to_numeric(tabla_norm[c], errors="coerce")
            if vals.notna().sum() > 0:
                depto_options.append(str(c))
        except Exception:
            pass
depto_options = sorted(list(dict.fromkeys(depto_options)))

# 5) Claves disponibles (limpias)
claves = [str(c).strip() for c in tabla_norm[col_clave].dropna().astype(str).tolist() if str(c).strip()]

# (Opcional) Muestra de depuración
st.caption(f"🧭 Encabezados detectados en 'Tabla' (fila {header_row}): "
           + ", ".join(map(str, tabla_norm.columns)))
st.caption(f"Usando → CLAVE: **{col_clave}** | DESCRIPCIÓN: **{col_desc or '—'}**")
