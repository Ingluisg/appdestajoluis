# app.py — Destajo con Horarios, Tarifas desde Excel, Catálogos, PDFs, Tablero, Planeación y Nómina (día/semana)
# © 2025

import os, json, base64, re, hashlib, math, io
from datetime import datetime, date, time, timedelta
from typing import Optional, Dict, Any, List, Tuple

import numpy as np
import pandas as pd
import streamlit as st

# =========================
# Configuración
# =========================
APP_TITLE = "Destajo · Horario + Tarifas + Plantillas + Planeación"
st.set_page_config(page_title=APP_TITLE, page_icon="🧮", layout="centered")

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

DB_FILE = os.path.join(DATA_DIR, "registros.parquet")
AUDIT_FILE = os.path.join(DATA_DIR, "audit.parquet")
USERS_FILE = "users.csv"

# Catálogos
CAT_EMP = os.path.join(DATA_DIR, "cat_empleados.csv")   # columnas: departamento,empleado,(opcional) orden
CAT_MOD = os.path.join(DATA_DIR, "cat_modelos.csv")     # columna: modelo

# Tarifas (área)
RATES_CSV = os.path.join(DATA_DIR, "rates.csv")         # normalizado desde Excel (hoja 'tiempos')
RATES_XLSX = os.path.join(DATA_DIR, "rates_source.xlsx")
DEFAULT_RATE_SHEET = "tiempos"
WEEKLY_HOURS_DEFAULT = 55  # de tu hoja

# Documentos PDF
DOCS_DIR = os.path.join(DATA_DIR, "docs")
DOCS_INDEX = os.path.join(DATA_DIR, "docs_index.csv")   # id,departamento,titulo,tags,filename,relpath,uploaded_by,ts
THUMBS_DIR = os.path.join(DOCS_DIR, "thumbs")
os.makedirs(DOCS_DIR, exist_ok=True)
os.makedirs(THUMBS_DIR, exist_ok=True)

# Planeación
PLAN_FILE = os.path.join(DATA_DIR, "planeacion.parquet")  # ["Codigo","DEPTO","MODELO","Descripcion","Semana","Programado","Fecha_Inicio","Fecha_Fin","Creado_Por","ts"]

# fallback por si aún no hay tarifas
DEPT_FALLBACK = ["COSTURA", "TAPIZ", "CARPINTERIA", "COJINERIA", "CORTE", "ARMADO", "HILADO", "COLCHONETA", "RESORTE", "OTRO"]

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
    if df is None:
        return
    df.to_parquet(path, index=False)

def sanitize_filename(name: str) -> str:
    base = re.sub(r"[^\w\-. ]+", "_", str(name))
    return re.sub(r"\s+", "_", base).strip("_")

def hash_relpath(relpath: str) -> str:
    return hashlib.sha1(relpath.encode("utf-8")).hexdigest()[:16]

def num(val, default=0.0):
    """Convierte a float de forma segura; NaN/None/'' -> default."""
    try:
        x = float(val)
        if math.isnan(x):
            return default
        return x
    except Exception:
        return default

def norm_depto(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).upper().strip())

# =========================
# Horario laboral (minutos efectivos)
# =========================
#  - L-V: 07:30–14:00  y 15:00–18:30  (excluye 14:00–15:00 comida)
#  - Sáb: 07:30–13:30
#  - Dom: 0
def day_windows(dt: date) -> List[Tuple[time, time]]:
    wd = dt.weekday()  # 0=Mon ... 6=Sun
    if wd <= 4:
        return [(time(7, 30), time(14, 0)), (time(15, 0), time(18, 30))]
    if wd == 5:
        return [(time(7, 30), time(13, 30))]
    return []

def overlap_minutes(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> float:
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    if end <= start:
        return 0.0
    return (end - start).total_seconds() / 60.0

def working_minutes_between(start: datetime, end: datetime) -> float:
    """Minutos dentro de ventanas laborales por día; la comida queda fuera por definición de ventanas."""
    if pd.isna(start) or pd.isna(end):
        return 0.0
    if end < start:
        start, end = end, start
    total = 0.0
    cur = start.date()
    last = end.date()
    while cur <= last:
        for w_from, w_to in day_windows(cur):
            ws = datetime.combine(cur, w_from)
            we = datetime.combine(cur, w_to)
            total += overlap_minutes(start, end, ws, we)
        cur += timedelta(days=1)
    return round(total, 2)

# =========================
# Tarifas por área (Excel -> CSV normalizado)
# =========================
def find_col(df: pd.DataFrame, keys: List[str]) -> Optional[str]:
    for key in keys:
        for c in df.columns:
            if key in c:
                return c
    return None

def normalize_rates(df_in: pd.DataFrame) -> pd.DataFrame:
    cols_out = ["DEPTO", "precio_minuto", "precio_pieza", "precio_hora"]
    if df_in is None or df_in.empty:
        return pd.DataFrame(columns=cols_out)

    df = df_in.copy()
    df.columns = [c.strip().lower() for c in df.columns]

    dep_col = None
    for c in df.columns:
        if c in ["depto", "departamento", "area", "área"]:
            dep_col = c
            break
    if dep_col is None:
        cand = [c for c in df.columns if "dept" in c or "area" in c or "área" in c]
        dep_col = cand[0] if cand else None
    if dep_col is None:
        return pd.DataFrame(columns=cols_out)

    out = pd.DataFrame({"DEPTO": df[dep_col].astype(str).map(norm_depto)})

    c_hr = find_col(df, ["$/hr", "precio_hora", "por_hora", "x_hora", "hora"])
    c_week = find_col(df, ["sem", "semana", "semanal", "$ semana", "$/sem"])
    c_min = find_col(df, ["precio_minuto", "por_min", "x_min", "minuto"])
    c_pza = find_col(df, ["precio_pieza", "por_pieza", "x_pieza", "pieza"])

    if c_hr and c_hr in df.columns:
        precio_hora = pd.to_numeric(df[c_hr], errors="coerce")
    elif c_week and c_week in df.columns:
        semanal = pd.to_numeric(df[c_week], errors="coerce")
        precio_hora = (semanal / float(WEEKLY_HOURS_DEFAULT)).round(2)
    else:
        precio_hora = pd.Series([np.nan] * len(df))

    if c_min and c_min in df.columns:
        precio_min = pd.to_numeric(df[c_min], errors="coerce")
    else:
        precio_min = (precio_hora / 60.0).round(4)

    if c_pza and c_pza in df.columns:
        precio_pza = pd.to_numeric(df[c_pza], errors="coerce")
    else:
        precio_pza = pd.Series([np.nan] * len(df))

    out["precio_hora"] = precio_hora
    out["precio_minuto"] = precio_min
    out["precio_pieza"] = precio_pza

    out = (out.groupby("DEPTO", as_index=False)
             .agg({"precio_minuto":"max","precio_pieza":"max","precio_hora":"max"}))
    return out[cols_out]

def load_rates_csv() -> pd.DataFrame:
    if os.path.exists(RATES_CSV):
        try:
            df = pd.read_csv(RATES_CSV)
            for c in ["DEPTO", "precio_minuto", "precio_pieza", "precio_hora"]:
                if c not in df.columns:
                    return pd.DataFrame(columns=["DEPTO", "precio_minuto", "precio_pieza", "precio_hora"])
            df["DEPTO"] = df["DEPTO"].map(norm_depto)
            return df
        except Exception:
            pass
    return pd.DataFrame(columns=["DEPTO", "precio_minuto", "precio_pieza", "precio_hora"])

def save_rates_csv(df_rates: pd.DataFrame):
    df = normalize_rates(df_rates)
    df.to_csv(RATES_CSV, index=False)

def calc_pago_row(depto: str, produce: float, minutos_ef: float, minutos_std: float, rates: pd.DataFrame) -> Tuple[float, str, float]:
    """Devuelve (pago, esquema, tarifa_base) con prioridad: minuto → pieza → hora."""
    dep = norm_depto(depto)
    r = rates[rates["DEPTO"] == dep]
    tarifa_min = float(r["precio_minuto"].iloc[0]) if not r.empty and pd.notna(r["precio_minuto"].iloc[0]) else math.nan
    tarifa_pza = float(r["precio_pieza"].iloc[0]) if not r.empty and pd.notna(r["precio_pieza"].iloc[0]) else math.nan
    tarifa_hr  = float(r["precio_hora"].iloc[0])  if not r.empty and pd.notna(r["precio_hora"].iloc[0])  else math.nan

    if not math.isnan(tarifa_min):
        return (round(minutos_ef * tarifa_min, 2), "minuto", tarifa_min)
    if not math.isnan(tarifa_pza):
        return (round(produce * tarifa_pza, 2), "pieza", tarifa_pza)
    if not math.isnan(tarifa_hr):
        return (round((minutos_ef / 60.0) * tarifa_hr, 2), "hora", tarifa_hr)
    return (0.0, "sin_tarifa", 0.0)

# =========================
# Usuarios y roles
# =========================
def load_users() -> pd.DataFrame:
    if os.path.exists(USERS_FILE):
        try:
            df = pd.read_csv(USERS_FILE, dtype=str)
            df.columns = [c.strip().lower() for c in df.columns]
            return df
        except Exception:
            pass
    return pd.DataFrame([
        {"user": "admin", "role": "Admin", "pin": "1234"},
        {"user": "supervisor", "role": "Supervisor", "pin": "1111"},
        {"user": "nominas", "role": "Nominas", "pin": "2222"},
        {"user": "rrhh", "role": "RRHH", "pin": "3333"},
        {"user": "productividad", "role": "Productividad", "pin": "4444"},
        {"user": "planeacion", "role": "Planeacion", "pin": "5555"},
    ])

ROLE_PERMS = {
    "Admin": {"editable": True, "can_delete": True},
    "Supervisor": {"editable": True, "can_delete": False},
    "Productividad": {"editable": False, "can_delete": False},
    "Nominas": {"editable": False, "can_delete": False},
    "RRHH": {"editable": False, "can_delete": False},
    "Planeacion": {"editable": True, "can_delete": False},
}

def login_box():
    st.header("Iniciar sesión")
    users = load_users()
    u = st.text_input("Usuario")
    p = st.text_input("PIN", type="password")
    if st.button("Entrar", use_container_width=True):
        row = users[(users["user"].str.lower() == str(u).lower()) & (users["pin"] == str(p))]
        if not row.empty:
            st.session_state.user = row.iloc[0]["user"]
            st.session_state.role = row.iloc[0]["role"]
            st.rerun()
        else:
            st.error("Usuario o PIN incorrectos.")

if "user" not in st.session_state:
    st.session_state.user, st.session_state.role = None, None

if not st.session_state.user:
    login_box()
    st.stop()

perms = ROLE_PERMS.get(st.session_state.role, ROLE_PERMS["Supervisor"])
st.sidebar.success(f"Sesión: {st.session_state.user} ({st.session_state.role})")
if st.sidebar.button("Cerrar sesión"):
    for k in ["user", "role"]:
        st.session_state.pop(k, None)
    st.rerun()

# =========================
# Catálogos (preservar orden del CSV)
# =========================
def load_emp_catalog() -> pd.DataFrame:
    """Lee cat_empleados.csv y preserva el orden de aparición; si hay columna 'orden', la usa dentro de cada depto."""
    if os.path.exists(CAT_EMP):
        try:
            df = pd.read_csv(CAT_EMP, dtype=str, keep_default_na=False)
            df.columns = [c.strip().lower() for c in df.columns]
            if not {"departamento","empleado"}.issubset(df.columns):
                return pd.DataFrame(columns=["departamento","empleado"])
            df["departamento"] = df["departamento"].map(norm_depto)
            df["empleado"] = df["empleado"].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
            df = df[(df["departamento"]!="") & (df["empleado"]!="")]
            df = df.drop_duplicates(subset=["departamento","empleado"], keep="first")
            if "orden" in df.columns:
                df["__orden"] = pd.to_numeric(df["orden"], errors="coerce")
                df = df.sort_values(by=["departamento","__orden"], kind="stable")
                df = df.drop(columns=["__orden"])
            return df.reset_index(drop=True)
        except Exception:
            pass
    return pd.DataFrame(columns=["departamento","empleado"])

def save_emp_catalog(df: pd.DataFrame):
    os.makedirs(os.path.dirname(CAT_EMP), exist_ok=True)
    if df is None:
        df = pd.DataFrame(columns=["departamento","empleado"])
    df = df.fillna("")
    df.columns = [c.strip().lower() for c in df.columns]
    if "departamento" in df.columns:
        df["departamento"] = df["departamento"].map(norm_depto)
    if "empleado" in df.columns:
        df["empleado"] = df["empleado"].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    df = df[(df["departamento"]!="") & (df["empleado"]!="")]
    df = df.drop_duplicates(subset=["departamento","empleado"], keep="first")
    df.to_csv(CAT_EMP, index=False)

def emp_options_for(depto: str) -> List[str]:
    dep = norm_depto(depto)
    cat = load_emp_catalog()
    return cat.loc[cat["departamento"]==dep, "empleado"].astype(str).tolist()

def load_model_catalog() -> List[str]:
    if os.path.exists(CAT_MOD):
        try:
            df = pd.read_csv(CAT_MOD, dtype=str)
            if "modelo" in df.columns:
                items = [x.strip() for x in df["modelo"].dropna().astype(str).tolist() if x.strip()]
                return list(dict.fromkeys(items))  # preserva orden de archivo
        except Exception:
            pass
    return []

def save_model_catalog(items: List[str]):
    clean = list(dict.fromkeys([str(x).strip() for x in items if str(x).strip()]))
    pd.DataFrame({"modelo": clean}).to_csv(CAT_MOD, index=False)

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
# PDFs (miniaturas + visor)
# =========================
def load_docs_index() -> pd.DataFrame:
    if os.path.exists(DOCS_INDEX):
        try:
            df = pd.read_csv(DOCS_INDEX, dtype=str)
            need = ["id", "departamento", "titulo", "tags", "filename", "relpath", "uploaded_by", "ts"]
            for c in need:
                if c not in df.columns:
                    return pd.DataFrame(columns=need)
            return df
        except Exception:
            pass
    return pd.DataFrame(columns=["id", "departamento", "titulo", "tags", "filename", "relpath", "uploaded_by", "ts"])

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
# Planeación helpers
# =========================
def load_plan() -> pd.DataFrame:
    df = load_parquet(PLAN_FILE)
    if df.empty:
        cols = ["Codigo","DEPTO","MODELO","Descripcion","Semana","Programado",
                "Fecha_Inicio","Fecha_Fin","Creado_Por","ts"]
        return pd.DataFrame(columns=cols)
    if "DEPTO" in df.columns:
        df["DEPTO"] = df["DEPTO"].map(norm_depto)
    if "MODELO" in df.columns:
        df["MODELO"] = df["MODELO"].astype(str).str.strip()
    if "Programado" in df.columns:
        df["Programado"] = pd.to_numeric(df["Programado"], errors="coerce").fillna(0.0)
    return df

def save_plan(df: pd.DataFrame):
    save_parquet(df, PLAN_FILE)

def plan_progress(plan_code: str, db: Optional[pd.DataFrame] = None) -> Tuple[float, float, float]:
    """Devuelve (asignado_total, programado_total, restante) para un Código dado."""
    if db is None:
        db = load_parquet(DB_FILE)
    plan = load_plan()
    row = plan[plan["Codigo"] == plan_code]
    if row.empty:
        return (0.0, 0.0, 0.0)
    programado = float(row["Programado"].iloc[0] or 0.0)
    if db.empty or "PLAN_CODIGO" not in db.columns:
        asignado = 0.0
    else:
        asignado = pd.to_numeric(
            db.loc[db["PLAN_CODIGO"].astype(str) == str(plan_code), "Produce"], errors="coerce"
        ).fillna(0).sum()
    restante = max(programado - asignado, 0.0)
    return (asignado, programado, restante)

def available_plan_codes_for(depto: str, modelo: str) -> pd.DataFrame:
    """Planeación por Depto/Modelo + columna Restante."""
    p = load_plan()
    if p.empty:
        return p
    p = p[(p["DEPTO"] == norm_depto(depto)) & (p["MODELO"].astype(str) == str(modelo))]
    if p.empty:
        return p
    db = load_parquet(DB_FILE)
    vals = []
    for _, r in p.iterrows():
        _, _, restante = plan_progress(str(r["Codigo"]), db)
        vals.append(restante)
    p = p.copy()
    p["Restante"] = vals
    p = p.sort_values(by=["Semana","Codigo"])
    return p

# =========================
# Derivados en vivo (minutos/pago) y export Nómina
# =========================
def compute_minutes_and_pay(df: pd.DataFrame, rates: pd.DataFrame) -> pd.DataFrame:
    """Agrega Minutos_Calc, Pago_Calc, Esquema_Calc, Tarifa_Calc y rellena Minutos_Proceso/Pago vacíos."""
    if df.empty:
        return df
    d = df.copy()

    # Normalización de columnas base
    if "DEPTO" in d.columns:
        d["DEPTO"] = d["DEPTO"].map(norm_depto)
    if "Inicio" in d.columns:
        d["Inicio"] = pd.to_datetime(d["Inicio"], errors="coerce")
    if "Fin" in d.columns:
        d["Fin"] = pd.to_datetime(d["Fin"], errors="coerce")

    now = datetime.now()

    def mins_row(r):
        ini, fin = r.get("Inicio"), r.get("Fin")
        if pd.notna(ini) and (pd.isna(fin) or ini == fin):
            return working_minutes_between(ini,
