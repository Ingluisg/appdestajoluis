# app.py — Luis Destajo App (API + Excel fallback)
import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import datetime, date, time as _time
import os, unicodedata, requests

# =============== Config ===============
st.set_page_config(page_title="App de Destajo — Núcleo (Móvil)", layout="wide")
st.title("App de Destajo — Núcleo")
st.caption("Captura idéntica al Excel (Tiempos/Tabla/Calendario), con soporte para API y modo móvil.")

EXCEL_PATH = "TIEMPOS_DESTAJO_CORE.xlsx"
BITACORA_PATH = "bitacora_cambios.csv"
VALID_SHEETS = ["Tiempos","Tabla","Calendario"]

# Secrets / Env para API + Máster
API_URL  = st.secrets.get("API_URL", os.getenv("API_URL","")).strip()
API_USER = st.secrets.get("API_USER", os.getenv("API_USER","")).strip()
API_PASS = st.secrets.get("API_PASS", os.getenv("API_PASS","")).strip()
MASTER_USER = "master"
MASTER_PASS = st.secrets.get("MASTER_PASS","master1234")

# =============== Utils comunes ===============
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
    row = {"timestamp": ts, "usuario": st.session_state.get("auth_user","app"), "accion": accion, "hoja": hoja, "detalle": detalle}
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

# =============== API helpers ===============
def api_enabled():
    return bool(API_URL and API_USER and API_PASS)

def api_login():
    if not api_enabled(): return None
    if "token" in st.session_state and st.session_state["token"]:
        return st.session_state["token"]
    try:
        r = requests.post(f"{API_URL}/auth/login", json={"username": API_USER, "password": API_PASS}, timeout=20)
        if r.ok:
            st.session_state["token"] = r.json()["access_token"]
            st.session_state["auth_user"] = API_USER
            return st.session_state["token"]
        else:
            st.warning(f"No pude iniciar sesión en API: {r.status_code} {r.text}")
    except Exception as e:
        st.warning(f"No pude conectar a API: {e}")
    return None

def api_headers():
    tok = api_login()
    return {"Authorization": f"Bearer {tok}"} if tok else {}

def api_summary(date_from: date, date_to: date, depto: str | None):
    if not api_enabled(): return None
    try:
        r = requests.get(f"{API_URL}/dashboard/summary",
                         params={"date_from": str(date_from), "date_to": str(date_to), "depto": depto or ""},
                         headers=api_headers(), timeout=20)
        return r.json() if r.ok else None
    except Exception:
        return None

# =============== Sidebar / Acceso ===============
with st.sidebar:
    st.header("Acceso")
    modo = st.radio("Modo", ["Usuario","Máster"], horizontal=True)
    if modo == "Máster":
        u = st.text_input("Usuario", value=MASTER_USER)
        p = st.text_input("Contraseña", type="password")
        if st.button("Entrar", use_container_width=True):
            st.session_state["is_master"] = (u == MASTER_USER and p == MASTER_PASS)
            st.session_state["auth_user"] = u if st.session_state["is_master"] else "app"
            if st.session_state["is_master"]:
                st.success("Acceso máster concedido.")
            else:
                st.error("Credenciales inválidas.")
    else:
        st.session_state["is_master"] = False
        st.session_state["auth_user"] = "app"

    st.divider()
    st.subheader("Modo de trabajo")
    if api_enabled():
        st.success("API habilitada ✅")
    else:
        st.info("Modo Excel (sin API)")

is_master = bool(st.session_state.get("is_master", False))

# =============== Carga Excel (si no hay API para catálogos) ===============
if not os.path.exists(EXCEL_PATH) and not api_enabled():
    st.error(f"No existe el archivo **{EXCEL_PATH}** en la raíz del repo.")
    st.stop()

data = load_book(EXCEL_PATH) if os.path.exists(EXCEL_PATH) else {}

# =============== Preparar TABLA (robusto) ===============
tabla_raw = data.get("Tabla")
if tabla_raw is None and not api_enabled():
    st.error("No se pudo leer la hoja **'Tabla'** y no hay API. Sube el Excel o configura la API.")
    st.stop()

header_row = None
tabla_norm = None
col_clave = col_desc = None
depto_options = []
claves = []

if tabla_raw is not None:
    # Detectar fila de encabezado que contenga 'CLAVE'
    for r in range(min(10, len(tabla_raw))):
        vals = [_norm(v) for v in tabla_raw.iloc[r].tolist()]
        if "clave" in vals:
            header_row = r; break
    if header_row is None:
        st.error("No encuentro la columna **CLAVE** en 'Tabla'. Revisa el Excel.")
        st.stop()

    tabla_headers = tabla_raw.iloc[header_row].tolist()
    tabla_norm = tabla_raw.iloc[header_row+1:].copy()
    tabla_norm.columns = tabla_headers

    col_clave = match_col(tabla_norm.columns, "CLAVE")
    col_desc  = match_col(tabla_norm.columns, "DESCRIPCION")
    if not col_clave:
        st.error("No aparece la columna **CLAVE** en 'Tabla' tras normalizar encabezados.")
        st.stop()

    # Deptos = columnas numéricas ≠ CLAVE/DESCRIPCION
    ignore = {"clave","descripcion","descripción","modelo","observaciones","obs"}
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
    claves = [str(c).strip() for c in tabla_norm[col_clave].dropna().astype(str).tolist() if str(c).strip()]

# =============== Calendario ===============
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

# =============== Tarifas $/hr desde Tiempos (robusto) ===============
rate_map = {}
t_raw = data.get("Tiempos")
if t_raw is not None and len(t_raw)>1:
    try:
        heads_t = t_raw.iloc[0].tolist()
        body_t  = t_raw.iloc[1:].copy(); body_t.columns = heads_t
        dept_col = None; rate_col = None
        for c in body_t.columns:
            if "depart" in _norm(c): dept_col = c
            n = _norm(c)
            if "$" in n or "/hr" in n or n=="hr" or "por hora" in n or "tarifa" in n:
                rate_col = c
        if dept_col and rate_col:
            tmp = body_t[[dept_col, rate_col]].copy()
            tmp[dept_col] = tmp[dept_col].astype(str).str.strip().str.upper()
            tmp[rate_col] = pd.to_numeric(tmp[rate_col], errors="coerce")
            tmp = tmp.dropna()
            for k, g in tmp.groupby(dept_col):
                rate_map[str(k)] = float(g[rate_col].mean())
    except Exception:
        pass

# =============== Tabs UI ===============
tabs = st.tabs(VALID_SHEETS)

# ----------- TIEMPOS (captura) -----------
with tabs[0]:
    st.subheader("Captura rápida (igual a Excel)")
    # Si no hay Excel (porque solo está API), obten opciones desde API (catálogos)
    if not depto_options and api_enabled():
        try:
            r = requests.get(f"{API_URL}/catalog/departments", headers=api_headers(), timeout=20)
            if r.ok:
                depto_options = [d["code"] for d in r.json()]
        except Exception:
            pass
    if not claves and api_enabled():
        try:
            r = requests.get(f"{API_URL}/catalog/operations", headers=api_headers(), timeout=20)
            if r.ok:
                claves = [o["clave"] for o in r.json()]
        except Exception:
            pass

    c1,c2,c3 = st.columns(3)
    clave = c1.selectbox("CLAVE", options=claves, placeholder="Selecciona la clave")
    depto = c2.selectbox("DEPTO", options=depto_options or ["COSTURA","TAPIZ","ARMADO","CARPINTERIA"],
                         placeholder="Selecciona el departamento")
    empleado = c3.text_input("Empleado / Operador")

    c4,c5,c6 = st.columns(3)
    # Día desde Calendario si existe, si no usa hoy
    if fecha_opts:
        dia = c4.selectbox("Día (desde Calendario)", options=fecha_opts, index=len(fecha_opts)-1)
    else:
        dia = c4.date_input("Día", value=date.today())

    # Horas por defecto desde Calendario si existen
    def_hi, def_hf = _time(8,0), _time(17,0)
    try:
        if cal is not None and fecha_opts and hora_i_col and hora_f_col:
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

    # --- Lookup Min Std ---
    std_min = None; modelo = None
    if tabla_norm is not None and clave and depto:
        dcol = match_col(tabla_norm.columns, depto)
        if dcol is not None:
            sel = tabla_norm.loc[tabla_norm[col_clave].astype(str) == str(clave), dcol].dropna()
            if len(sel):
                std_min = float(sel.iloc[0])
            if col_desc:
                md = tabla_norm.loc[tabla_norm[col_clave].astype(str) == str(clave), col_desc].dropna()
                if len(md): modelo = str(md.iloc[0])
    # Si hay API y no encontramos min_std, pregúntale a la API
    if std_min is None and api_enabled() and clave and depto:
        try:
            r = requests.get(f"{API_URL}/catalog/std/{clave}/{str(depto).strip().upper()}",
                             headers=api_headers(), timeout=20)
            if r.ok:
                std_min = r.json().get("min_std", None)
        except Exception:
            pass

    # --- Lookup tarifa ---
    tarifa = rate_map.get(str(depto).strip().upper())
    if tarifa is None and api_enabled() and depto:
        try:
            r = requests.get(f"{API_URL}/catalog/rate/{str(depto).strip().upper()}",
                             headers=api_headers(), timeout=20)
            if r.ok:
                tarifa = r.json().get("rate_per_hour", None)
        except Exception:
            pass

    st.caption(f"Min Std: **{std_min if std_min is not None else '—'}** | $/hr: **{tarifa if tarifa is not None else '—'}**")

    # Fallback manual de tarifa si no existe
    tarifa_manual = st.number_input("$/hr (si no aparece en tarifas)", min_value=0.0, value=0.0, step=0.5)
    if tarifa is None and tarifa_manual > 0:
        tarifa = tarifa_manual

    # --- Calcular / Guardar (API -> Excel fallback) ---
    if st.button("Calcular y guardar", use_container_width=True):
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
            st.error("Falta Min Std o $/hr. Revisa 'Tabla'/'Tiempos' o usa el campo manual.")
        else:
            # Intento API primero
            saved_in_api = False
            if api_enabled():
                token = api_login()
                if token:
                    payload = {
                        "work_date": str(dia),
                        "employee_code": str(empleado).strip() or "SIN-COD",
                        "department_code": str(depto).strip().upper(),
                        "clave": str(clave),
                        "pieces": int(produce),
                        "start_time": str(hora_i),
                        "end_time": str(hora_f),
                    }
                    try:
                        r = requests.post(f"{API_URL}/entries", json=payload,
                                          headers={"Authorization": f"Bearer {token}"}, timeout=20)
                        if r.ok:
                            st.success("✅ Guardado en **API**")
                            saved_in_api = True
                        else:
                            st.warning(f"API dijo: {r.status_code} — {r.text}")
                    except Exception as e:
                        st.warning(f"No pude llamar a API: {e}")

            # Si no hay API o falló, guardar en Excel como antes
            if not saved_in_api:
                if "Tiempos" not in data:
                    st.error("No existe hoja 'Tiempos' para guardar (modo Excel).")
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
                    st.success(f"✅ Guardado en **Excel** | Destajo unit: {destajo_unit} | Total: {destajo_total}")

            append_bitacora("captura", "Tiempos", f"clave={clave}, depto={depto}, pzas={produce}, unit={destajo_unit}, total={destajo_total}")

    st.markdown("**Vista de la hoja 'Tiempos' (actual / Excel):**")
    if "Tiempos" in data:
        st.dataframe(data["Tiempos"], use_container_width=True, height=320)
    else:
        st.caption("Sin Excel o sin hoja 'Tiempos' (si hay API, consulta reportes desde el dashboard de la API).")

# ----------- TABLA -----------
with tabs[1]:
    st.subheader("Tabla")
    if tabla_norm is not None:
        st.dataframe(tabla_norm, use_container_width=True, height=450)
        st.caption("Las columnas de departamento (COSTURA, TAPIZ, ARMADO, etc.) se usan para el Min Std.")
    else:
        st.info("Sin Excel (solo API).")

# ----------- CALENDARIO -----------
with tabs[2]:
    st.subheader("Calendario")
    if cal is not None:
        st.dataframe(cal, use_container_width=True, height=450)
        st.caption("El selector de día (y horas si existen) se alimenta desde aquí.")
    else:
        st.info("Sin Excel (solo API).")
# ----------- Descargas / KPI API -----------
st.markdown("---")
c1, c2, c3 = st.columns(3)

with c1:
    if data:
        st.download_button(
            "Descargar Excel (3 hojas)",
            to_excel_bytes(data),
            file_name="TIEMPOS_DESTAJO_CORE_actualizado.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

with c2:
    if os.path.exists(BITACORA_PATH):
        bit = pd.read_csv(BITACORA_PATH)
        st.download_button(
            "Descargar Bitácora (CSV)",
            bit.to_csv(index=False).encode("utf-8"),
            file_name="bitacora_cambios.csv",
            mime="text/csv",
            use_container_width=True,
        )

with c3:
    st.subheader("KPI (API)")
    df = st.date_input("Rango", value=(date.today(), date.today()))
    dept_f = st.text_input("Depto (opcional)").strip().upper()
    if st.button("Consultar KPI API", use_container_width=True):
        if api_enabled():
            res = api_summary(
                df[0] if isinstance(df, tuple) else date.today(),
                df[1] if isinstance(df, tuple) else date.today(),
                dept_f or None,
            )
            if res:
                st.success(
                    f"Piezas: {res.get('pieces')} | Destajo total: {res.get('destajo_total')} | "
                    f"Eficiencia prom.: {res.get('efficiency_avg')}"
                )
            else:
                st.error("No pude obtener KPI de la API (revisa API_URL/credenciales).")
        else:
            st.info("Configura la API en Secrets para KPIs en vivo.")
