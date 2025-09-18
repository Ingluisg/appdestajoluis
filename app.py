# app.py — Destajo con Horarios, Tarifas desde Excel, Catálogos, PDFs, Tablero y Nómina (día/semana)
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
APP_TITLE = "Destajo · Horario + Tarifas + Plantillas"
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
    """
    Normaliza tarifas por área desde tu Excel:
      - Detecta columna de departamento (depto/area/área/…)
      - Si hay columna $/hr, la usa como precio_hora
      - Si hay columna semanal ($ sem, semana, semanal), deriva precio_hora = semanal / WEEKLY_HOURS_DEFAULT
      - Calcula precio_minuto = precio_hora / 60 si hace falta
    """
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
    ])

ROLE_PERMS = {
    "Admin": {"editable": True, "can_delete": True},
    "Supervisor": {"editable": True, "can_delete": False},
    "Productividad": {"editable": False, "can_delete": False},
    "Nominas": {"editable": False, "can_delete": False},
    "RRHH": {"editable": False, "can_delete": False},
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
# Derivados en vivo (minutos/pago) y export Nómina
# =========================
def compute_minutes_and_pay(df: pd.DataFrame, rates: pd.DataFrame) -> pd.DataFrame:
    """Agrega columnas derivadas: Minutos_Calc (en vivo: si Inicio==Fin, usa ahora), Pago_Calc, Esquema_Calc, Tarifa_Calc.
       Si Minutos_Proceso/Pago están vacíos o 0, muestra los calculados."""
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
        # "Abierto": Inicio==Fin o Fin nulo → tomar ahora como Fin para mostrar avance
        if pd.notna(ini) and (pd.isna(fin) or ini == fin):
            return working_minutes_between(ini, now)
        if pd.notna(ini) and pd.notna(fin):
            return working_minutes_between(ini, fin)
        return float(r.get("Minutos_Proceso", 0) or 0)

    d["Minutos_Calc"] = d.apply(mins_row, axis=1).astype(float)

    def pay_row(r):
        p, esq, tar = calc_pago_row(
            str(r.get("DEPTO","")).upper(),
            num(r.get("Produce"), 0.0),
            float(r.get("Minutos_Calc", 0.0)),
            num(r.get("Minutos_Std"), 0.0),
            rates
        )
        return pd.Series({"Pago_Calc": p, "Esquema_Calc": esq, "Tarifa_Calc": tar})

    d = pd.concat([d, d.apply(pay_row, axis=1)], axis=1)

    if "Minutos_Proceso" in d.columns:
        d["Minutos_Proceso"] = np.where(pd.to_numeric(d["Minutos_Proceso"], errors="coerce").fillna(0) > 0,
                                        d["Minutos_Proceso"], d["Minutos_Calc"])
    else:
        d["Minutos_Proceso"] = d["Minutos_Calc"]

    if "Pago" in d.columns:
        d["Pago"] = np.where(pd.to_numeric(d["Pago"], errors="coerce").fillna(0) > 0,
                             d["Pago"], d["Pago_Calc"])
    else:
        d["Pago"] = d["Pago_Calc"]

    d["Minutos_Proceso"] = d["Minutos_Proceso"].round(2)
    d["Pago"] = d["Pago"].round(2)

    # auxiliares para agrupaciones
    if "Inicio" in d.columns:
        d["Fecha"] = d["Inicio"].dt.date
    if "Semana" not in d.columns and "Inicio" in d.columns:
        d["Semana"] = d["Inicio"].dt.isocalendar().week

    return d

def export_nomina(df: pd.DataFrame) -> bytes:
    """Genera un XLSX con:
       - Detalle por registro
       - Totales por empleado/fecha (día)
       - Totales por empleado/semana
    """
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as xw:
        # Detalle
        detalle_cols = [c for c in ["DEPTO","EMPLEADO","MODELO","Produce","Inicio","Fin","Minutos_Proceso","Pago","Semana","Fecha"] if c in df.columns]
        df[detalle_cols].to_excel(xw, index=False, sheet_name="Detalle")

        # Día
        if {"EMPLEADO","Fecha","Pago","Minutos_Proceso"}.issubset(df.columns):
            dia = (df.groupby(["EMPLEADO","Fecha"], dropna=False)
                     .agg(Pagos=("Pago","sum"), Minutos=("Minutos_Proceso","sum"), Piezas=("Produce","sum"))
                     .reset_index())
            dia["Horas"] = (dia["Minutos"] / 60).round(2)
            dia["Pagos"] = dia["Pagos"].round(2)
            dia.to_excel(xw, index=False, sheet_name="Nomina_Diaria")

        # Semana
        if {"EMPLEADO","Semana","Pago","Minutos_Proceso"}.issubset(df.columns):
            sem = (df.groupby(["EMPLEADO","Semana"], dropna=False)
                     .agg(Pagos=("Pago","sum"), Minutos=("Minutos_Proceso","sum"), Piezas=("Produce","sum"))
                     .reset_index())
            sem["Horas"] = (sem["Minutos"] / 60).round(2)
            sem["Pagos"] = sem["Pagos"].round(2)
            sem.to_excel(xw, index=False, sheet_name="Nomina_Semanal")
    return output.getvalue()

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
# 📲 Captura  (CORREGIDO: Empleado depende de Depto en tiempo real)
# =========================
PLACEHOLDER_EMP = "— Selecciona —"

def _reset_emp_on_depto_change():
    # Al cambiar el depto, reiniciar la selección del empleado para forzar lista limpia
    st.session_state["cap_emp_choice"] = PLACEHOLDER_EMP

with tabs[0]:
    st.subheader("Captura móvil")
    rates = load_rates_csv()
    # departamentos dinámicos desde tarifas (si no hay, usar fallback)
    if not rates.empty:
        dept_options = sorted(list(set(DEPT_FALLBACK) | set(rates["DEPTO"].dropna().astype(str).tolist())))
    else:
        dept_options = DEPT_FALLBACK

    # Departamento FUERA del form, con on_change que reinicia empleado
    depto = st.selectbox(
        "Departamento*",
        options=dept_options,
        index=0 if "cap_depto" not in st.session_state or st.session_state.get("cap_depto") not in dept_options
              else dept_options.index(st.session_state.get("cap_depto")),
        key="cap_depto",
        on_change=_reset_emp_on_depto_change,
        help="Al cambiar, se reinicia y recarga el catálogo de empleados."
    )

    # opciones dependientes del depto seleccionado
    empleados_opts = emp_options_for(depto)
    modelos_opts = load_model_catalog()

    # Asegurar valor por defecto coherente con la lista actual
    if st.session_state.get("cap_emp_choice") not in ([PLACEHOLDER_EMP] + empleados_opts):
        st.session_state["cap_emp_choice"] = PLACEHOLDER_EMP

    with st.form("form_captura", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            emp_choice = st.selectbox(
                "Empleado*",
                [PLACEHOLDER_EMP] + empleados_opts,
                key="cap_emp_choice",
                help="Catálogo dependiente del departamento seleccionado."
            )
        with c2:
            modelo_choice = st.selectbox("Modelo*", [PLACEHOLDER_EMP] + modelos_opts, key="cap_modelo_choice")
            produce = st.number_input("Produce (piezas)*", min_value=1, step=1, value=1, key="cap_produce")
            minutos_std = st.number_input("Minutos Std (por pieza)*", min_value=0.0, step=0.5, value=0.0, key="cap_min_std")

        if st.form_submit_button("➕ Agregar registro", use_container_width=True):
            empleado = emp_choice if emp_choice != PLACEHOLDER_EMP else ""
            modelo = modelo_choice if modelo_choice != PLACEHOLDER_EMP else ""
            if not empleado:
                st.error("Selecciona un **Empleado** (agrégalo en 🛠️ Admin si no aparece).")
                st.stop()
            if not modelo:
                st.error("Selecciona un **Modelo** (agrégalo en 🛠️ Admin si no aparece).")
                st.stop()

            ahora = datetime.now()
            db = load_parquet(DB_FILE)

            # Cerrar trabajo abierto del mismo empleado (Inicio==Fin)
            if not db.empty and {"EMPLEADO", "Inicio", "Fin"}.issubset(db.columns):
                try:
                    db["Inicio"] = pd.to_datetime(db["Inicio"], errors="coerce")
                    db["Fin"] = pd.to_datetime(db["Fin"], errors="coerce")
                except Exception:
                    pass

                abiertos = db[
                    (db["EMPLEADO"].astype(str) == str(empleado)) &
                    db["Inicio"].notna() & db["Fin"].notna() &
                    (db["Inicio"] == db["Fin"])
                ]

                if not abiertos.empty:
                    idx_last = abiertos.index[-1]
                    ini_prev = pd.to_datetime(db.at[idx_last, "Inicio"])
                    fin_prev = ahora

                    minutos_ef = working_minutes_between(ini_prev, fin_prev)
                    produce_prev = num(db.at[idx_last, "Produce"] if "Produce" in db.columns else 0.0)
                    min_std_prev = num(db.at[idx_last, "Minutos_Std"] if "Minutos_Std" in db.columns else 0.0)

                    db.at[idx_last, "Fin"] = fin_prev
                    db.at[idx_last, "Minutos_Proceso"] = minutos_ef

                    pago, esquema, tarifa = calc_pago_row(
                        str(db.at[idx_last, "DEPTO"]).strip().upper(),
                        produce_prev,
                        minutos_ef,
                        min_std_prev,
                        rates
                    )
                    db.at[idx_last, "Pago"] = pago
                    db.at[idx_last, "Esquema_Pago"] = esquema
                    db.at[idx_last, "Tarifa_Base"] = tarifa
                    db.at[idx_last, "Estimado"] = False

                    save_parquet(db, DB_FILE)
                    log_audit(
                        st.session_state.user, "auto-close", int(idx_last),
                        {"empleado": empleado, "cerrado": fin_prev, "minutos_efectivos": minutos_ef, "pago": pago}
                    )

            # Nuevo registro "abierto"
            row = {
                "DEPTO": norm_depto(depto),
                "EMPLEADO": empleado,
                "MODELO": modelo,
                "Produce": produce,
                "Inicio": ahora,
                "Fin": ahora,            # abierto (se cerrará con la siguiente asignación)
                "Minutos_Proceso": 0.0,  # se calcula al cerrar
                "Minutos_Std": minutos_std,
                "Semana": week_number(ahora),
                "Usuario": st.session_state.user,
                "Estimado": True,
                "Pago": 0.0,
                "Esquema_Pago": "",
                "Tarifa_Base": 0.0,
            }

            db = load_parquet(DB_FILE)
            db = pd.concat([db, pd.DataFrame([row])], ignore_index=True)
            save_parquet(db, DB_FILE)
            log_audit(st.session_state.user, "create", int(len(db) - 1), {"via": "ui", "row": row})
            st.success("Registro guardado ✅ (si había uno abierto, se cerró con minutos efectivos y pago).")

# =========================
# 📈 Tablero (con cálculo en vivo, diarios/semanales y export)
# =========================
with tabs[1]:
    st.subheader("Producción en vivo")
    base = load_parquet(DB_FILE)
    rates = load_rates_csv()
    if base.empty:
        st.info("Sin registros.")
    else:
        show = compute_minutes_and_pay(base, rates)

        # Avisar si hay deptos sin tarifa
        if not rates.empty and "DEPTO" in show.columns:
            sin_tarifa = sorted(set(show["DEPTO"].dropna()) - set(rates["DEPTO"].dropna()))
            if sin_tarifa:
                st.warning("Áreas sin tarifa en rates.csv: " + ", ".join(sin_tarifa))

        c1, c2, c3 = st.columns(3)
        f_depto = c1.multiselect("Departamento", sorted(show["DEPTO"].dropna().astype(str).unique().tolist()) if "DEPTO" in show.columns else [])
        f_semana = c2.multiselect("Semana", sorted(pd.to_numeric(show["Semana"], errors="coerce").dropna().unique().tolist()) if "Semana" in show.columns else [])
        f_emp = c3.text_input("Empleado (contiene)")

        fdf = show.copy()
        if not fdf.empty:
            if f_depto:
                fdf = fdf[fdf["DEPTO"].astype(str).isin(f_depto)]
            if f_semana:
                fdf = fdf[pd.to_numeric(fdf["Semana"], errors="coerce").isin(f_semana)]
            if f_emp:
                fdf = fdf[fdf["EMPLEADO"].astype(str).str.contains(f_emp, case=False, na=False)]

        cols = [c for c in ["DEPTO","EMPLEADO","MODELO","Produce","Inicio","Fin","Minutos_Proceso","Pago","Semana","Fecha"] if c in fdf.columns]
        st.dataframe(fdf.sort_values(by="Inicio", ascending=False)[cols],
                     use_container_width=True, hide_index=True)

        # Totales por día (empleado/fecha)
        st.markdown("### Pagos por día")
        if {"EMPLEADO","Fecha","Pago","Minutos_Proceso"}.issubset(fdf.columns):
            dia = (fdf.groupby(["EMPLEADO","Fecha"], dropna=False)
                     .agg(Pagos=("Pago","sum"), Minutos=("Minutos_Proceso","sum"), Piezas=("Produce","sum"))
                     .reset_index())
            dia["Horas"] = (dia["Minutos"] / 60).round(2)
            dia["Pagos"] = dia["Pagos"].round(2)
            st.dataframe(dia.sort_values(["Fecha","EMPLEADO"]), use_container_width=True, hide_index=True)

        # Totales por semana (empleado/semana)
        st.markdown("### Pagos por semana")
        if {"EMPLEADO","Semana","Pago","Minutos_Proceso"}.issubset(fdf.columns):
            sem = (fdf.groupby(["EMPLEADO","Semana"], dropna=False)
                     .agg(Pagos=("Pago","sum"), Minutos=("Minutos_Proceso","sum"), Piezas=("Produce","sum"))
                     .reset_index())
            sem["Horas"] = (sem["Minutos"] / 60).round(2)
            sem["Pagos"] = sem["Pagos"].round(2)
            st.dataframe(sem.sort_values(["Semana","EMPLEADO"]), use_container_width=True, hide_index=True)

            # Exportar nómina
            xls = export_nomina(fdf)
            st.download_button("⬇️ Exportar nómina (Excel)", data=xls, file_name=f"nomina_{date.today().isoformat()}.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

# =========================
# 📚 Plantillas & Diagramas (PDF)
# =========================
def load_docs_index_or_empty():
    idx = load_docs_index()
    return idx if not idx.empty else pd.DataFrame(columns=["id", "departamento", "titulo", "tags", "filename", "relpath", "uploaded_by", "ts"])

with tabs[2]:
    st.subheader("Plantillas & Diagramas (PDF)")
    st.caption("Sube y consulta PDFs por departamento. Vista previa + descarga.")

    if st.session_state.role == "Admin":
        with st.expander("⬆️ Subir nuevo PDF", expanded=False):
            up_depto = st.selectbox("Departamento", sorted(list(set(DEPT_FALLBACK) | set(load_rates_csv()["DEPTO"].dropna().astype(str).tolist()))))
            up_title = st.text_input("Título o descripción")
            up_tags = st.text_input("Etiquetas (separadas por comas)", placeholder="corte, guía, plantilla A")
            up_file = st.file_uploader("Archivo PDF", type=["pdf"])
            if st.button("Guardar PDF", type="primary"):
                if not up_file:
                    st.error("Adjunta un PDF.")
                else:
                    dep_dir = os.path.join(DOCS_DIR, sanitize_filename(up_depto))
                    os.makedirs(dep_dir, exist_ok=True)
                    safe_name = sanitize_filename(up_file.name)
                    save_path = os.path.join(dep_dir, safe_name)
                    with open(save_path, "wb") as f:
                        f.write(up_file.read())
                    relpath = os.path.relpath(save_path, ".").replace("\\", "/")

                    idx = load_docs_index()
                    new_id = str(int(idx["id"].max()) + 1) if not idx.empty else "1"
                    row = {"id": new_id,
                           "departamento": norm_depto(up_depto),
                           "titulo": (up_title.strip() if up_title else safe_name),
                           "tags": up_tags.strip(),
                           "filename": safe_name,
                           "relpath": relpath,
                           "uploaded_by": st.session_state.user,
                           "ts": now_iso()}
                    idx = pd.concat([idx, pd.DataFrame([row])], ignore_index=True)
                    save_docs_index(idx)
                    ensure_pdf_thumbnail(relpath)
                    st.success("PDF guardado e indexado ✅")

    idx = load_docs_index_or_empty()
    if idx.empty:
        st.info("Aún no hay documentos. (Admin puede subirlos arriba)")
    else:
        c1, c2 = st.columns([1, 2])
        dept_filter = c1.multiselect("Departamento", sorted(list(set(DEPT_FALLBACK) | set(load_rates_csv()["DEPTO"].dropna().astype(str).tolist()))))
        q = c2.text_input("Buscar (título / tags / archivo)", placeholder="ej. corte, plantilla, tapiz...")

        df = idx.copy()
        if dept_filter:
            df = df[df["departamento"].isin([norm_depto(d) for d in dept_filter])]
        if q.strip():
            qq = q.strip().lower()
            df = df[df.apply(lambda r: any(qq in str(r[col]).lower() for col in ["titulo", "tags", "filename"]), axis=1)]

        df = df.sort_values(by="ts", ascending=False).reset_index(drop=True)
        st.write(f"{len(df)} documento(s) encontrado(s).")

        cols_per_row = 3
        for i in range(0, len(df), cols_per_row):
            cols = st.columns(cols_per_row)
            for j, (_, r) in enumerate(df.iloc[i:i + cols_per_row].iterrows()):
                with cols[j]:
                    path = r["relpath"]
                    abs_path = path if os.path.isabs(path) else os.path.join(".", path)
                    thumb = ensure_pdf_thumbnail(path)
                    if thumb and os.path.exists(thumb):
                        st.image(thumb, use_container_width=True)
                    st.markdown(f"**{r['titulo']}**")
                    st.caption(f"{r['departamento']} · {r['filename']}")
                    cta1, cta2 = st.columns(2)
                    with cta1:
                        if st.button("👁️ Ver", key=f"ver_{r['id']}"):
                            st.session_state[f"open_{r['id']}"] = True
                    with cta2:
                        try:
                            with open(abs_path, "rb") as f:
                                data = f.read()
                            st.download_button("⬇️ Descargar", data=data, file_name=os.path.basename(abs_path),
                                               mime="application/pdf", key=f"dl_{r['id']}", use_container_width=True)
                        except Exception as e:
                            st.error(f"Descarga falló: {e}")
                    if st.session_state.get(f"open_{r['id']}"):
                        show_pdf_file(abs_path, height=600)
                        st.divider()
                    st.caption(f"Etiquetas: {r['tags'] or '—'} · Por: {r['uploaded_by']} · {r['ts']}")

# =========================
# ✏️ Editar / Auditar
# =========================
with tabs[3]:
    st.subheader("Edición (solo Admin mueve tiempos) + Bitácora")
    db = load_parquet(DB_FILE)
    rates = load_rates_csv()
    if db.empty:
        st.info("No hay datos para editar.")
    else:
        idx_num = st.number_input("ID de registro (0 .. n-1)", min_value=0, max_value=len(db) - 1, step=1, value=0)
        row = db.iloc[int(idx_num)].to_dict()

        if st.session_state.role != "Admin":
            st.warning("Solo **Admin** puede modificar horas Inicio/Fin.")
        with st.form("edit_form"):
            c1, c2 = st.columns(2)
            with c1:
                depto = st.selectbox("Departamento", options=sorted(list(set(DEPT_FALLBACK) | set(rates["DEPTO"].dropna().astype(str).tolist()))) or DEPT_FALLBACK,
                                     index=0)
                empleado = st.text_input("Empleado", value=str(row.get("EMPLEADO", "")))
                modelo = st.text_input("Modelo", value=str(row.get("MODELO", "")))
                produce = st.number_input("Produce", value=int(num(row.get("Produce"), 0)), min_value=0)
                min_std = st.number_input("Minutos_Std", value=float(num(row.get("Minutos_Std"), 0.0)), min_value=0.0, step=0.5)
            with c2:
                ini_raw = pd.to_datetime(row.get("Inicio"), errors="coerce")
                fin_raw = pd.to_datetime(row.get("Fin"), errors="coerce")
                if st.session_state.role == "Admin":
                    ini_date = st.date_input("Inicio (fecha)", ini_raw.date() if pd.notna(ini_raw) else date.today())
                    ini_time = st.time_input("Inicio (hora)", ini_raw.time() if pd.notna(ini_raw) else datetime.now().time().replace(second=0, microsecond=0))
                    fin_date = st.date_input("Fin (fecha)", fin_raw.date() if pd.notna(fin_raw) else date.today())
                    fin_time = st.time_input("Fin (hora)", fin_raw.time() if pd.notna(fin_raw) else datetime.now().time().replace(second=0, microsecond=0))
                    inicio = datetime.combine(ini_date, ini_time)
                    fin = datetime.combine(fin_date, fin_time)
                else:
                    st.write("Inicio:", ini_raw)
                    st.write("Fin:", fin_raw)
                    inicio, fin = ini_raw, fin_raw

            submitted = st.form_submit_button("💾 Guardar cambios")
            if submitted:
                before = db.iloc[int(idx_num)].to_dict()
                db.at[int(idx_num), "DEPTO"] = norm_depto(depto)
                db.at[int(idx_num), "EMPLEADO"] = empleado
                db.at[int[idx_num), "MODELO"] = modelo
                db.at[int[idx_num), "Produce"] = num(produce)
                db.at[int[idx_num), "Minutos_Std"] = num(min_std)
                if st.session_state.role == "Admin":
                    db.at[int[idx_num), "Inicio"] = inicio
                    db.at[int[idx_num), "Fin"] = fin
                    minutos_ef = working_minutes_between(inicio, fin)
                    db.at[int[idx_num), "Minutos_Proceso"] = minutos_ef
                    pago, esquema, tarifa = calc_pago_row(
                        norm_depto(depto), num(produce), minutos_ef, num(min_std), rates
                    )
                    db.at[int[idx_num), "Pago"] = pago
                    db.at[int[idx_num), "Esquema_Pago"] = esquema
                    db.at[int[idx_num), "Tarifa_Base"] = tarifa
                save_parquet(db, DB_FILE)
                after = db.iloc[int(idx_num)].to_dict()
                log_audit(st.session_state.user, "update", int(idx_num), {"before": before, "after": after})
                st.success("Actualizado ✅")

        st.markdown("---")
        st.subheader("Bitácora")
        audit = load_parquet(AUDIT_FILE)
        if audit.empty:
            st.caption("Sin eventos aún.")
        else:
            st.dataframe(audit.sort_values(by="ts", ascending=False).head(400),
                         use_container_width=True, hide_index=True)

# =========================
# 🛠️ Admin
# =========================
with tabs[4]:
    if st.session_state.role != "Admin":
        st.info("Solo Admin puede administrar.")
    else:
        st.subheader("Catálogo de Empleados por Departamento")
        emp_cat = load_emp_catalog()
        cA, cB = st.columns([1, 2])
        with cA:
            dep_new = st.selectbox("Departamento", sorted(list(set(DEPT_FALLBACK) | set(load_rates_csv()["DEPTO"].dropna().astype(str).tolist()))), index=0, key="dep_new")
            emp_new = st.text_input("➕ Empleado nuevo")
            if st.button("Guardar empleado"):
                merged = pd.concat([emp_cat, pd.DataFrame([{"departamento": dep_new, "empleado": emp_new}])], ignore_index=True)
                save_emp_catalog(merged)
                st.success("Empleado agregado al catálogo")
                st.rerun()
        with cB:
            st.dataframe(emp_cat, use_container_width=True, hide_index=True)
        st.download_button("⬇️ Descargar cat_empleados.csv",
                           data=emp_cat.to_csv(index=False).encode("utf-8"),
                           file_name="cat_empleados.csv", mime="text/csv")
        up_emp = st.file_uploader("Subir cat_empleados.csv", type=["csv"])
        if up_emp is not None:
            try:
                dfu = pd.read_csv(up_emp, dtype=str)
                if {"departamento", "empleado"}.issubset(dfu.columns):
                    merged = pd.concat([emp_cat, dfu], ignore_index=True)
                    save_emp_catalog(merged)
                    st.success("Catálogo de empleados actualizado")
                    st.rerun()
                else:
                    st.error("El CSV debe tener columnas: departamento, empleado")
            except Exception as e:
                st.error(f"CSV inválido: {e}")

        st.markdown("---")
        st.subheader("Catálogo de Modelos (global)")
        mod_cat_list = load_model_catalog()
        st.dataframe(pd.DataFrame({"modelo": mod_cat_list}), use_container_width=True, hide_index=True)
        nuevo_mod = st.text_input("➕ Modelo nuevo")
        if st.button("Guardar modelo"):
            save_model_catalog(list(set(mod_cat_list + ([nuevo_mod] if nuevo_mod.strip() else []))))
            st.success("Modelo agregado")
            st.rerun()
        st.download_button("⬇️ Descargar cat_modelos.csv",
                           data=pd.DataFrame({"modelo": load_model_catalog()}).to_csv(index=False).encode("utf-8"),
                           file_name="cat_modelos.csv", mime="text/csv")
        up_mod = st.file_uploader("Subir cat_modelos.csv", type=["csv"], key="up_mod")
        if up_mod is not None:
            try:
                dfm = pd.read_csv(up_mod, dtype=str)
                if "modelo" in dfm.columns:
                    save_model_catalog(list(set(mod_cat_list + dfm["modelo"].dropna().astype(str).tolist())))
                    st.success("Catálogo de modelos actualizado")
                    st.rerun()
                else:
                    st.error("El CSV debe tener columna: modelo")
            except Exception as e:
                st.error(f"CSV inválido: {e}")

        st.markdown("---")
        st.subheader("Tarifas por Área (desde Excel)")
        rates = load_rates_csv()
        if rates.empty:
            st.info("Aún no hay tarifas. Sube el Excel de la hoja 'tiempos'.")
        else:
            st.dataframe(rates, use_container_width=True, hide_index=True)
        rates_file = st.file_uploader("Subir Excel de tarifas (hoja 'tiempos')", type=["xlsx", "xls"])
        sheet_name = st.text_input("Nombre de hoja (default 'tiempos')", value=DEFAULT_RATE_SHEET)
        if st.button("Procesar tarifas"):
            if not rates_file:
                st.error("Adjunta un archivo Excel.")
            else:
                try:
                    xdf = pd.read_excel(rates_file, sheet_name=sheet_name)
                    save_rates_csv(xdf)
                    with open(RATES_XLSX, "wb") as f:
                        f.write(rates_file.getbuffer())
                    st.success("Tarifas cargadas y normalizadas ✅")
                    st.rerun()
                except Exception as e:
                    st.error(f"No pude leer el Excel: {e}")

st.caption("© 2025 · Destajo móvil con horarios, tarifas por área, catálogos, visor de PDFs, tablero y nómina (día/semana).")
