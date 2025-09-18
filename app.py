# app.py — Destajo con Horario Laboral, Tarifas por Área (desde Excel), Catálogos por Depto, PDFs con miniaturas
# © 2025

import os, json, base64, re, hashlib, math
from datetime import datetime, date, time, timedelta
from typing import Optional, Dict, Any, List, Tuple

import numpy as np
import pandas as pd
import streamlit as st

# =========================
# Config
# =========================
APP_TITLE = "Destajo · Horario + Tarifas + Plantillas"
st.set_page_config(page_title=APP_TITLE, page_icon="🧮", layout="centered")

DATA_DIR   = "data"
os.makedirs(DATA_DIR, exist_ok=True)

DB_FILE     = os.path.join(DATA_DIR, "registros.parquet")
AUDIT_FILE  = os.path.join(DATA_DIR, "audit.parquet")
USERS_FILE  = "users.csv"

# Catálogos
CAT_EMP     = os.path.join(DATA_DIR, "cat_empleados.csv")   # columnas: departamento,empleado
CAT_MOD     = os.path.join(DATA_DIR, "cat_modelos.csv")     # columna: modelo

# Tarifas (área)
RATES_CSV   = os.path.join(DATA_DIR, "rates.csv")           # normalizado desde un Excel subido
RATES_XLSX  = os.path.join(DATA_DIR, "rates_source.xlsx")   # última subida
RATES_SHEET = "tiempos"                                     # hoja por defecto

# Documentos (PDFs)
DOCS_DIR    = os.path.join(DATA_DIR, "docs")
DOCS_INDEX  = os.path.join(DATA_DIR, "docs_index.csv")      # id,departamento,titulo,tags,filename,relpath,uploaded_by,ts
THUMBS_DIR  = os.path.join(DOCS_DIR, "thumbs")
os.makedirs(THUMBS_DIR, exist_ok=True)

DEPT_OPTIONS = ["COSTURA","TAPIZ","CARPINTERIA","COJINERIA","CORTE","ARMADO","HILADO","COLCHONETA","OTRO"]

# =========================
# Utils
# =========================
def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")

def week_number(dt: Optional[datetime]):
    if pd.isna(dt) or dt is None:
        return np.nan
    return pd.Timestamp(dt).isocalendar().week

def load_parquet(path: str) -> pd.DataFrame:
    if os.path.exists(path):
        try:
            return pd.read_parquet(path)
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()

def save_parquet(df: pd.DataFrame, path: str):
    if df is None or df.empty:
        return
    df.to_parquet(path, index=False)

def sanitize_filename(name: str) -> str:
    base = re.sub(r"[^\w\-. ]+", "_", str(name))
    return re.sub(r"\s+", "_", base).strip("_")

def hash_relpath(relpath: str) -> str:
    return hashlib.sha1(relpath.encode("utf-8")).hexdigest()[:16]

# =========================
# Horario laboral (cálculo de minutos efectivos)
# =========================
# Ventanas laborales por día:
#  - L-V: 07:30–14:00  y 15:00–18:30  (se excluye 14:00–15:00 comida)
#  - Sáb: 07:30–13:30
#  - Dom: 0
LUNCH_FROM = time(14, 0)
LUNCH_TO   = time(15, 0)

def day_windows(dt: date) -> List[Tuple[time, time]]:
    wd = dt.weekday()  # 0=Mon ... 6=Sun
    if wd <= 4:  # L-V
        return [(time(7,30), time(14,0)), (time(15,0), time(18,30))]
    if wd == 5:  # Sáb
        return [(time(7,30), time(13,30))]
    return []

def overlap_minutes(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> float:
    start = max(a_start, b_start)
    end   = min(a_end, b_end)
    if end <= start:
        return 0.0
    return (end - start).total_seconds() / 60.0

def working_minutes_between(start: datetime, end: datetime) -> float:
    """Suma minutos dentro de ventanas laborales por día; excluye comida (por definición de ventanas)."""
    if pd.isna(start) or pd.isna(end):
        return 0.0
    if end < start:
        start, end = end, start
    total = 0.0
    cur = start.date()
    last = end.date()
    while cur <= last:
        windows = day_windows(cur)
        for w_from, w_to in windows:
            ws = datetime.combine(cur, w_from)
            we = datetime.combine(cur, w_to)
            total += overlap_minutes(start, end, ws, we)
        cur += timedelta(days=1)
    # redondeo a 2 decimales
    return round(total, 2)

# =========================
# Tarifas por área (desde Excel hoja "tiempos")
# =========================
def load_rates_csv() -> pd.DataFrame:
    if os.path.exists(RATES_CSV):
        try:
            df = pd.read_csv(RATES_CSV, dtype=str)
            return normalize_rates(df)
        except Exception:
            pass
    return pd.DataFrame(columns=["DEPTO","precio_minuto","precio_pieza","precio_hora"])

def normalize_rates(df_in: pd.DataFrame) -> pd.DataFrame:
    df = df_in.copy()
    df.columns = [c.strip().lower() for c in df.columns]
    # Detectar columna de departamento
    dep_col = None
    for c in df.columns:
        if c in ["depto","departamento","area","área"]:
            dep_col = c
            break
    if dep_col is None and "depto" not in df.columns:
        # si viene de otro formato, abortamos a frame vacío válido
        return pd.DataFrame(columns=["DEPTO","precio_minuto","precio_pieza","precio_hora"])

    df["DEPTO"] = df[dep_col].astype(str).str.strip().str.upper()
    # Intentar mapear precios
    def find_col(cands: List[str]) -> Optional[str]:
        for c in df.columns:
            for key in cands:
                if key in c:
                    return c
        return None
    c_min = find_col(["precio_minuto","minuto","x_min","por_min"])
    c_pza = find_col(["precio_pieza","pieza","x_pieza","por_pieza"])
    c_hr  = find_col(["precio_hora","hora","x_hora","por_hora"])

    out = pd.DataFrame({"DEPTO": df["DEPTO"].dropna().astype(str)})
    for name, col in [("precio_minuto", c_min), ("precio_pieza", c_pza), ("precio_hora", c_hr)]:
        if col and col in df.columns:
            out[name] = pd.to_numeric(df[col], errors="coerce")
        else:
            out[name] = np.nan

    # dedupe por DEPTO, tomando la 1ª aparición con datos
    out = (out.groupby("DEPTO", as_index=False)
              .agg({"precio_minuto":"max","precio_pieza":"max","precio_hora":"max"}))
    return out

def save_rates_csv(df_rates: pd.DataFrame):
    if df_rates is None or df_rates.empty:
        pd.DataFrame(columns=["DEPTO","precio_minuto","precio_pieza","precio_hora"]).to_csv(RATES_CSV, index=False)
        return
    df = normalize_rates(df_rates)
    df.to_csv(RATES_CSV, index=False)

def calc_pago_row(depto: str, produce: float, minutos_ef: float, minutos_std: float, rates: pd.DataFrame) -> Tuple[float,str,float]:
    """
    Devuelve (pago, esquema, tarifa_base)
    prioridad: precio_minuto -> precio_pieza -> precio_hora
    si no hay tarifa, intenta: produce * minutos_std * precio_minuto_global (si existiera DEPTO=GLOBAL)
    """
    dep = (depto or "").strip().upper()
    r = rates[rates["DEPTO"]==dep]
    tarifa_min = float(r["precio_minuto"].iloc[0]) if not r.empty and pd.notna(r["precio_minuto"].iloc[0]) else np.nan
    tarifa_pza = float(r["precio_pieza"].iloc[0]) if not r.empty and pd.notna(r["precio_pieza"].iloc[0]) else np.nan
    tarifa_hr  = float(r["precio_hora"].iloc[0])  if not r.empty and pd.notna(r["precio_hora"].iloc[0])  else np.nan

    if not math.isnan(tarifa_min):
        return (round(minutos_ef * tarifa_min, 2), "minuto", tarifa_min)
    if not math.isnan(tarifa_pza):
        return (round(produce * tarifa_pza, 2), "pieza", tarifa_pza)
    if not math.isnan(tarifa_hr):
        return (round((minutos_ef/60.0) * tarifa_hr, 2), "hora", tarifa_hr)

    # fallback: buscar GLOBAL por minuto
    r2 = rates[rates["DEPTO"]=="GLOBAL"]
    if not r2.empty and pd.notna(r2["precio_minuto"].iloc[0]):
        t = float(r2["precio_minuto"].iloc[0])
        base_min = produce * (float(minutos_std) if pd.notna(minutos_std) else 0.0)
        return (round(base_min * t, 2), "minuto_std", t)

    return (0.0, "sin_tarifa", 0.0)

# =========================
# Usuarios
# =========================
def load_users() -> pd.DataFrame:
    if os.path.exists(USERS_FILE):
        try:
            df = pd.read_csv(USERS_FILE, dtype=str)
            df.columns = [c.strip().lower() for c in df.columns]
            return df
        except Exception:
            pass
    # fallback
    return pd.DataFrame([
        {"user":"admin","role":"Admin","pin":"1234"},
        {"user":"supervisor","role":"Supervisor","pin":"1111"},
        {"user":"nominas","role":"Nominas","pin":"2222"},
        {"user":"rrhh","role":"RRHH","pin":"3333"},
        {"user":"productividad","role":"Productividad","pin":"4444"},
    ])

# =========================
# Catálogos
# =========================
def load_emp_catalog() -> pd.DataFrame:
    path = CAT_EMP
    if os.path.exists(path):
        try:
            df = pd.read_csv(path, dtype=str).fillna("")
            for c in ["departamento","empleado"]:
                if c not in df.columns:
                    return pd.DataFrame(columns=["departamento","empleado"])
            df["departamento"] = df["departamento"].str.strip().str.upper()
            df["empleado"] = df["empleado"].str.replace(r"\s+", " ", regex=True).str.strip()
            df = df[(df["departamento"]!="") & (df["empleado"]!="")]
            df = df.drop_duplicates(subset=["departamento","empleado"])
            return df.sort_values(["departamento","empleado"]).reset_index(drop=True)
        except Exception:
            pass
    return pd.DataFrame(columns=["departamento","empleado"])

def save_emp_catalog(df: pd.DataFrame):
    os.makedirs(os.path.dirname(CAT_EMP), exist_ok=True)
    if df.empty:
        pd.DataFrame(columns=["departamento","empleado"]).to_csv(CAT_EMP, index=False); return
    out = (df.fillna("")
             .assign(departamento=lambda d: d["departamento"].str.strip().str.upper(),
                     empleado=lambda d: d["empleado"].str.replace(r"\s+", " ", regex=True).str.strip()))
    out = out[(out["departamento"]!="") & (out["empleado"]!="")]
    out = out.drop_duplicates(subset=["departamento","empleado"]).sort_values(["departamento","empleado"])
    out.to_csv(CAT_EMP, index=False)

def emp_options_for(depto: str) -> List[str]:
    dep = str(depto).strip().upper()
    cat = load_emp_catalog()
    return sorted(cat.loc[cat["departamento"]==dep, "empleado"].dropna().astype(str).unique().tolist())

def load_model_catalog() -> List[str]:
    if os.path.exists(CAT_MOD):
        try:
            df = pd.read_csv(CAT_MOD, dtype=str)
            if "modelo" in df.columns:
                items = [x.strip() for x in df["modelo"].dropna().astype(str).tolist() if x.strip()]
                return sorted(list(dict.fromkeys(items)))
        except Exception:
            pass
    return []

def save_model_catalog(items: List[str]):
    clean = sorted(list(dict.fromkeys([str(x).strip() for x in items if str(x).strip()])))
    pd.DataFrame({"modelo": clean}).to_csv(CAT_MOD, index=False)

# =========================
# Docs (PDF) + Miniaturas
# =========================
def load_docs_index() -> pd.DataFrame:
    if os.path.exists(DOCS_INDEX):
        try:
            df = pd.read_csv(DOCS_INDEX, dtype=str)
            need = ["id","departamento","titulo","tags","filename","relpath","uploaded_by","ts"]
            for c in need:
                if c not in df.columns:
                    return pd.DataFrame(columns=need)
            return df
        except Exception:
            pass
    return pd.DataFrame(columns=["id","departamento","titulo","tags","filename","relpath","uploaded_by","ts"])

def save_docs_index(df: pd.DataFrame):
    os.makedirs(DOCS_DIR, exist_ok=True)
    df.to_csv(DOCS_INDEX, index=False)

def thumb_path_for(relpath: str) -> str:
    h = hash_relpath(relpath)
    base = os.path.splitext(os.path.basename(relpath))[0]
    return os.path.join(THUMBS_DIR, f"{base}_{h}.png")

def ensure_pdf_thumbnail(relpath: str, max_w: int = 360, dpi: int = 110) -> Optional[str]:
    png_path = thumb_path_for(relpath)
    abs_pdf = relpath if os.path.isabs(relpath) else os.path.join(".", relpath)
    try:
        if os.path.exists(png_path):
            return png_path
        import fitz  # PyMuPDF
        doc = fitz.open(abs_pdf)
        if doc.page_count == 0:
            return None
        page = doc.load_page(0)
        pix = page.get_pixmap(dpi=dpi)
        if pix.width > max_w:
            scale = max_w / pix.width
            mat = fitz.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=mat, dpi=dpi)
        pix.save(png_path)
        doc.close()
        return png_path if os.path.exists(png_path) else None
    except Exception:
        return None

def show_pdf_file(path: str, height: int = 680):
    try:
        with open(path, "rb") as f:
            data = f.read()
        b64 = base64.b64encode(data).decode("utf-8")
        try:
            from streamlit_pdf_viewer import pdf_viewer
            pdf_viewer(b64, width=0, height=height, scrolling=True)
        except Exception:
            st.components.v1.html(
                f"""<iframe src="data:application/pdf;base64,{b64}" width="100%" height="{height}" style="border:none;"></iframe>""",
                height=height+10,
            )
        colA, colB = st.columns(2)
        with colA:
            st.markdown(
                f"""<a href="data:application/pdf;base64,{b64}" target="_blank" rel="noopener"
                style="display:inline-block;padding:0.6rem 1rem;border:1px solid #777;border-radius:6px;text-decoration:none">
                🔎 Abrir en pestaña nueva</a>""",
                unsafe_allow_html=True,
            )
        with colB:
            st.download_button("⬇️ Descargar PDF", data=data, file_name=os.path.basename(path), mime="application/pdf", use_container_width=True)
    except Exception as e:
        st.error(f"No se pudo mostrar/servir el PDF: {e}")

# =========================
# Permisos
# =========================
ROLE_PERMS = {
    "Admin": {"editable": True, "columns_view": "all", "can_delete": True},
    "Supervisor": {"editable": True, "columns_view": "all", "can_delete": False},
    "Productividad": {"editable": False, "columns_view": "all", "can_delete": False},
    "Nominas": {"editable": False, "columns_view": "all", "can_delete": False},
    "RRHH": {"editable": False, "columns_view": "all", "can_delete": False},
}

# =========================
# Auditoría
# =========================
def log_audit(user: str, action: str, record_id: Optional[int], details: Dict[str, Any]):
    payload = json.dumps(details, ensure_ascii=False,
                         default=lambda o: o.isoformat() if hasattr(o, "isoformat") else str(o))
    aud = load_parquet(AUDIT_FILE)
    row = {"ts": now_iso(), "user": user, "action": action,
           "record_id": int(record_id) if record_id is not None else None, "details": payload}
    aud = pd.concat([aud, pd.DataFrame([row])], ignore_index=True)
    save_parquet(aud, AUDIT_FILE)

# =========================
# Login
# =========================
def login_box():
    st.header("Iniciar sesión")
    users = load_users()
    u = st.text_input("Usuario")
    p = st.text_input("PIN", type="password")
    if st.button("Entrar", use_container_width=True):
        row = users[(users['user'].str.lower()==str(u).lower()) & (users['pin']==str(p))]
        if not row.empty:
            st.session_state.user = row.iloc[0]['user']
            st.session_state.role = row.iloc[0]['role']
            st.rerun()
        else:
            st.error("Usuario o PIN incorrectos.")

if "user" not in st.session_state:
    st.session_state.user, st.session_state.role = None, None

if not st.session_state.user:
    login_box(); st.stop()

perms = ROLE_PERMS.get(st.session_state.role, ROLE_PERMS["Supervisor"])

st.sidebar.success(f"Sesión: {st.session_state.user} ({st.session_state.role})")
if st.sidebar.button("Cerrar sesión"):
    for k in ["user","role"]:
        st.session_state.pop(k, None)
    st.rerun()

# =========================
# Tabs
# =========================
tabs = st.tabs([
    "📲 Captura",
    "📈 Tablero",
    "📚 Plantillas & Diagramas",
    "✏️ Editar / Auditar",
    "🛠️ Admin",
])

# =========================
# 📲 Captura
# =========================
with st.form("form_captura", clear_on_submit=True):
    c1, c2 = st.columns(2)
    with c1:
        depto = st.selectbox("Departamento*", options=DEPT_OPTIONS, index=0)
        empleados_opts = emp_options_for(depto)
        emp_choice = st.selectbox("Empleado*", ["— Selecciona —"] + empleados_opts)
    with c2:
        modelos_opts = load_model_catalog()
        modelo_choice = st.selectbox("Modelo*", ["— Selecciona —"] + modelos_opts)
        produce = st.number_input("Produce (piezas)*", min_value=1, step=1, value=1)
        minutos_std = st.number_input("Minutos Std (por pieza)*", min_value=0.0, step=0.5, value=0.0)

    if st.form_submit_button("➕ Agregar registro", use_container_width=True):
        empleado = emp_choice if emp_choice != "— Selecciona —" else ""
        modelo   = modelo_choice if modelo_choice != "— Selecciona —" else ""
        # ... (resto de tu lógica de guardado)
