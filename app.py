# app.py — Destajo con Roles, Auditoría y API (Streamlit Cloud-friendly)
import os, json, base64
from datetime import datetime, date, time, timedelta
from typing import Optional, Dict, Any

import numpy as np
import pandas as pd
import streamlit as st

APP_TITLE = "Destajo · Roles + Auditoría + API"
st.set_page_config(page_title=APP_TITLE, page_icon="🧮", layout="centered")

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
DB_FILE = os.path.join(DATA_DIR, "registros.parquet")
AUDIT_FILE = os.path.join(DATA_DIR, "audit.parquet")
USERS_FILE = "users.csv"  # user,role,pin

# ------------------ Utilidades ------------------
def now_iso():
    return datetime.now().isoformat(timespec="seconds")

def combine_date_time(d, t):
    if pd.isna(d) or pd.isna(t):
        return pd.NaT
    try:
        d2 = pd.to_datetime(d).date()
        if isinstance(t, (pd.Timestamp, datetime)):
            tt = t.time()
        else:
            tt = pd.to_datetime(str(t)).time()
        return datetime.combine(d2, tt)
    except Exception:
        return pd.NaT

def week_number(dt: Optional[datetime]):
    if pd.isna(dt) or dt is None:
        return np.nan
    return pd.Timestamp(dt).isocalendar().week

def load_parquet(path: str):
    if os.path.exists(path):
        try:
            return pd.read_parquet(path)
        except Exception:
            try:
                return pd.read_csv(path.replace(".parquet",".csv"))
            except Exception:
                return pd.DataFrame()
    return pd.DataFrame()

def save_parquet(df: pd.DataFrame, path: str):
    if df is None or df.empty:
        return
    df.to_parquet(path, index=False)

def load_users():
    if os.path.exists(USERS_FILE):
        try:
            df = pd.read_csv(USERS_FILE, dtype=str)
            df.columns = [c.strip().lower() for c in df.columns]
            return df
        except Exception:
            pass
    # fallback: demo users
    return pd.DataFrame([
        {"user":"admin","role":"Admin","pin":"1234"},
        {"user":"supervisor","role":"Supervisor","pin":"1111"},
        {"user":"nominas","role":"Nominas","pin":"2222"},
        {"user":"rrhh","role":"RRHH","pin":"3333"},
        {"user":"productividad","role":"Productividad","pin":"4444"},
    ])

# Excel helpers (cálculo exacto)
def detect_target_sheet(xl: pd.ExcelFile) -> str:
    for name in xl.sheet_names:
        key = "".join(str(name).split()).lower()
        if key in ["tiempos","tiempo","tiemposdestajo","destajo","hojadetiempos"]:
            return name
    return xl.sheet_names[0]

def read_excel_struct(file) -> dict:
    xl = pd.ExcelFile(file)
    sheet = detect_target_sheet(xl)
    df_raw = xl.parse(sheet)

    hdr_idx = None
    for i in range(min(20, len(df_raw))):
        row = " | ".join([str(x).upper() for x in df_raw.iloc[i].fillna("").tolist()])
        if all(k in row for k in ["CLAVE","DEPTO","COLUMNA","MODELO"]) and ("DÍA" in row or "DIA" in row) and ("HORA" in row):
            hdr_idx = i; break
    if hdr_idx is None:
        st.error("No se encontró encabezado en la hoja 'Tiempos'.")
        st.stop()

    headers = df_raw.iloc[hdr_idx].fillna("").tolist()
    df = df_raw.copy()
    df.columns = headers
    data = df.iloc[hdr_idx+1:].copy()

    rename_map = {
        'Horas\nProceso':'Horas_Proceso',
        'Minutos\nProceso':'Minutos_Proceso',
        'Tiempo\nUnitario\nHoras':'TU_Horas',
        'Tiempo\nUnitario\nMinutos':'TU_Minutos',
        'Minutos\nStd\n':'Minutos_Std',
        'Destajo\nUnitario\n':'Destajo_Unitario',
        'Día I':'Dia_I',
        'Dia I':'Dia_I',
        'Día F':'Dia_F',
        'Dia F':'Dia_F',
        'Hora I':'Hora_I',
        'Hora F':'Hora_F',
    }
    data.rename(columns=rename_map, inplace=True)

    # tabla departamentos (intentamos últimas 4 columnas)
    dept_df = None
    right_block = data.iloc[:, -4:].copy()
    rb_cols = [str(c).strip().upper() for c in right_block.columns]
    if "DEPARTAMENTOS" in rb_cols and ("COLUMNA" in rb_cols) and any(x in rb_cols for x in ["$/HR","$/HR "]):
        dept_df = right_block
    else:
        cols_needed = []
        for name in data.columns:
            n = str(name).strip().upper()
            if n in ["DEPARTAMENTOS","COLUMNA","$ SEMANAL","$/HR","$/HR "]:
                cols_needed.append(name)
        if cols_needed:
            dept_df = data[cols_needed].copy()

    return {"sheet": sheet, "data": data, "dept_df": dept_df}

def compute_destajo_exact(df: pd.DataFrame, dept_df: pd.DataFrame):
    out = df.copy()

    # tarifas por hora desde dept_df
    rate_per_hr_map = {}
    if dept_df is not None and not dept_df.empty:
        dd = dept_df.rename(columns=lambda c: str(c).strip())
        col_col = [c for c in dd.columns if str(c).strip().upper()=="COLUMNA"]
        hr_col = [c for c in dd.columns if "$/HR" in str(c).upper()]
        if col_col and hr_col:
            tmp = dd[[col_col[0], hr_col[0]]].dropna()
            tmp[col_col[0]] = pd.to_numeric(tmp[col_col[0]], errors='coerce')
            tmp[hr_col[0]] = pd.to_numeric(tmp[hr_col[0]], errors='coerce')
            rate_per_hr_map = {int(r[col_col[0]]): float(r[hr_col[0]]) for _, r in tmp.dropna().iterrows()}

    if 'Minutos_Proceso' not in out.columns or out['Minutos_Proceso'].isna().all():
        if {'Dia_I','Hora_I','Dia_F','Hora_F'}.issubset(out.columns):
            start = [combine_date_time(out.loc[i,'Dia_I'], out.loc[i,'Hora_I']) for i in out.index]
            end   = [combine_date_time(out.loc[i,'Dia_F'], out.loc[i,'Hora_F']) for i in out.index]
            out['Inicio'] = pd.to_datetime(start, errors='coerce')
            out['Fin'] = pd.to_datetime(end, errors='coerce')
            out['Minutos_Proceso'] = (out['Fin'] - out['Inicio']).dt.total_seconds() / 60.0
        else:
            out['Minutos_Proceso'] = np.nan

    out['Produce'] = pd.to_numeric(out.get('Produce', np.nan), errors='coerce')
    out['Minutos_Proceso'] = pd.to_numeric(out['Minutos_Proceso'], errors='coerce')

    # Minutos_Std
    if 'Minutos_Std' not in out.columns and 'TU_Minutos' in out.columns:
        out['Minutos_Std'] = pd.to_numeric(out['TU_Minutos'], errors='coerce')
    else:
        out['Minutos_Std'] = pd.to_numeric(out.get('Minutos_Std', np.nan), errors='coerce')

    # Eficiencia (cap en 1)
    out['Eficiencia_calc'] = np.where(out['Minutos_Proceso']>0,
                                      (out['Produce'] * out['Minutos_Std']) / out['Minutos_Proceso'],
                                      np.nan).clip(upper=1.0)

    # Tarifa por minuto desde COLUMNA -> $/hr / 60
    if 'COLUMNA' in out.columns and rate_per_hr_map:
        colnum = pd.to_numeric(out['COLUMNA'], errors='coerce').astype('Int64')
        out['Tarifa_hr'] = colnum.map(rate_per_hr_map).astype(float)
        out['Tarifa_min'] = out['Tarifa_hr'] / 60.0
    else:
        out['Tarifa_hr'] = np.nan
        out['Tarifa_min'] = np.nan

    out['Destajo_Unitario_calc'] = out['Minutos_Std'] * out['Tarifa_min']
    out['Pago_total'] = out['Destajo_Unitario_calc'] * out['Produce'] * out['Eficiencia_calc']

    if 'Inicio' in out.columns:
        out['Semana'] = out['Inicio'].dt.isocalendar().week

    return out

# ------------------ Permisos por rol ------------------
ROLE_PERMS = {
    "Admin": {
        "editable": True,
        "columns_view": "all",
        "can_delete": True,
    },
    "Supervisor": {
        "editable": True,
        "columns_view": ["DEPTO","COLUMNA","EMPLEADO","MODELO","Produce","Inicio","Fin","Minutos_Proceso","Minutos_Std","Semana","Fuente","Usuario"],
        "can_delete": False,
    },
    "Productividad": {
        "editable": False,
        "columns_view": "all",
        "can_delete": False,
    },
    "Nominas": {
        "editable": False,
        "columns_view": ["DEPTO","COLUMNA","EMPLEADO","MODELO","Produce","Minutos_Proceso","Minutos_Std","Semana"],
        "can_delete": False,
    },
    "RRHH": {
        "editable": False,
        "columns_view": ["DEPTO","EMPLEADO","MODELO","Produce","Semana"],
        "can_delete": False,
    },
}

CORE_COLUMNS = ["DEPTO","COLUMNA","EMPLEADO","MODELO","Produce","Inicio","Fin","Minutos_Proceso","Minutos_Std","Semana","Fuente","Usuario"]

# ------------------ Auditoría ------------------
def log_audit(user: str, action: str, record_id: Optional[int], details: Dict[str, Any]):
    aud = load_parquet(AUDIT_FILE)
    row = {
        "ts": now_iso(),
        "user": user,
        "action": action,
        "record_id": record_id,
        "details": json.dumps(details, ensure_ascii=False),
    }
    aud = pd.concat([aud, pd.DataFrame([row])], ignore_index=True)
    save_parquet(aud, AUDIT_FILE)

# ------------------ Login ------------------
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
            st.success(f"Bienvenido, {st.session_state.user} ({st.session_state.role})")
            st.rerun()
        else:
            st.error("Usuario o PIN incorrectos.")

if "user" not in st.session_state:
    st.session_state.user = None
    st.session_state.role = None

# ------------------ Modo API vía query params ------------------
# Reemplazo: usar st.query_params en vez de st.experimental_get_query_params
# ?api=ingest&token=XYZ&data=<base64json>
qp = st.query_params
if qp.get("api", [None])[0] == "ingest":
    token = qp.get("token", [None])[0]
    allowed = token and (token == (st.secrets.get("API_TOKEN") if hasattr(st, "secrets") else os.getenv("API_TOKEN","devtoken")))
    if not allowed:
        st.write({"ok": False, "error": "TOKEN_INVALIDO"})
        st.stop()
    b64 = qp.get("data", [None])[0]
    if not b64:
        st.write({"ok": False, "error": "FALTA_DATA"})
        st.stop()
    try:
        payload = json.loads(base64.urlsafe_b64decode(b64 + "==="))
    except Exception as e:
        st.write({"ok": False, "error": f"JSON_INVALIDO: {e}"})
        st.stop()
    required = ["DEPTO","COLUMNA","EMPLEADO","MODELO","Produce","Inicio","Fin","Minutos_Std"]
    missing = [k for k in required if k not in payload]
    if missing:
        st.write({"ok": False, "error": f"FALTAN_CAMPOS: {missing}"})
        st.stop()
    db = load_parquet(DB_FILE)
    inicio = pd.to_datetime(payload["Inicio"], errors="coerce")
    fin = pd.to_datetime(payload["Fin"], errors="coerce")
    minutos_proceso = (fin - inicio).total_seconds()/60.0 if pd.notna(inicio) and pd.notna(fin) else np.nan
    row = {
        "DEPTO": payload["DEPTO"],
        "COLUMNA": payload["COLUMNA"],
        "EMPLEADO": payload["EMPLEADO"],
        "MODELO": payload["MODELO"],
        "Produce": payload["Produce"],
        "Inicio": inicio,
        "Fin": fin,
        "Minutos_Proceso": minutos_proceso,
        "Minutos_Std": payload["Minutos_Std"],
        "Semana": week_number(inicio),
        "Fuente": "API",
        "Usuario": "api-client",
    }
    db = pd.concat([db, pd.DataFrame([row])], ignore_index=True)
    save_parquet(db, DB_FILE)
    log_audit("api-client", "create", int(len(db)-1), {"via":"api", "row": row})
    st.write({"ok": True, "inserted_id": int(len(db)-1)})
    st.stop()

# ------------------ Flujo normal (UI) ------------------
if not st.session_state.user:
    login_box()
    st.stop()

st.sidebar.success(f"Sesión: {st.session_state.user} ({st.session_state.role})")
if st.sidebar.button("Cerrar sesión"):
    for k in ["user","role"]:
        st.session_state.pop(k, None)
    st.rerun()

tabs = st.tabs(["📲 Captura", "📈 Tablero", "✏️ Editar / Auditar", "📚 Excel (exacto)", "🛠️ Admin"])

# -------- Captura --------
with tabs[0]:
    if st.session_state.role not in ["Supervisor","Productividad","Admin"]:
        st.info("Tu rol no tiene permisos para capturar.")
    else:
        st.subheader("Captura móvil")

        # Listas desplegables desde historial
        db_prev = load_parquet(DB_FILE)
        empleados_hist = sorted([x for x in db_prev["EMPLEADO"].dropna().astype(str).unique().tolist()]) if not db_prev.empty and "EMPLEADO" in db_prev.columns else []
        modelos_hist = sorted([x for x in db_prev["MODELO"].dropna().astype(str).unique().tolist()]) if not db_prev.empty and "MODELO" in db_prev.columns else []
if perms["editable"]:
            with st.form("edit_form"):
                c1, c2 = st.columns(2)
                with c1:
                    empleado = st.text_input("Empleado", value=str(row.get("EMPLEADO","")))
                    depto = st.text_input("DEPTO", value=str(row.get("DEPTO","")))
                    columna = st.number_input("COLUMNA", value=int(row.get("COLUMNA") or 1), min_value=1, step=1)
                    modelo = st.text_input("MODELO", value=str(row.get("MODELO","")))
                    produce = st.number_input("Produce", value=int(row.get("Produce") or 0), min_value=0, step=1)
                with c2:
                    # --- Compat: usar date_input + time_input en vez de datetime_input ---
                    ini_raw = pd.to_datetime(row.get("Inicio"), errors="coerce")
                    fin_raw = pd.to_datetime(row.get("Fin"), errors="coerce")

                    ini_date = st.date_input("Inicio (fecha)", value=(ini_raw.date() if pd.notna(ini_raw) else date.today()))
                    ini_time = st.time_input("Inicio (hora)", value=(ini_raw.time() if pd.notna(ini_raw) else datetime.now().time().replace(second=0, microsecond=0)))

                    fin_date = st.date_input("Fin (fecha)", value=(fin_raw.date() if pd.notna(fin_raw) else date.today()))
                    fin_time = st.time_input("Fin (hora)", value=(fin_raw.time() if pd.notna(fin_raw) else (datetime.now().time().replace(second=0, microsecond=0))))

                    # recombinar
                    inicio = datetime.combine(ini_date, ini_time)
                    fin = datetime.combine(fin_date, fin_time)

                    min_std = st.number_input("Minutos_Std", value=float(row.get("Minutos_Std") or 0.0), min_value=0.0, step=0.5)

                submitted = st.form_submit_button("💾 Guardar cambios")
                if submitted:
                    before = db.iloc[int(idx)].to_dict()
                    db.at[int(idx), "EMPLEADO"] = empleado
                    db.at[int(idx), "DEPTO"] = depto
                    db.at[int(idx), "COLUMNA"] = columna
                    db.at[int(idx), "MODELO"] = modelo
                    db.at[int(idx), "Produce"] = produce
                    db.at[int(idx), "Inicio"] = inicio
                    db.at[int(idx), "Fin"] = fin
                    db.at[int(idx), "Minutos_Proceso"] = (pd.to_datetime(fin) - pd.to_datetime(inicio)).total_seconds()/60.0
                    db.at[int(idx), "Minutos_Std"] = min_std
                    db.at[int(idx), "Semana"] = week_number(inicio)
                    save_parquet(db, DB_FILE)
                    after = db.iloc[int(idx)].to_dict()
                    log_audit(st.session_state.user, "update", int(idx), {"before": before, "after": after})
                    st.success("Actualizado ✅")
        

# -------- Tablero --------
with tabs[1]:
    st.subheader("Producción en vivo")
    base = load_parquet(DB_FILE)

    perms = ROLE_PERMS.get(st.session_state.role, ROLE_PERMS["Supervisor"])
    if perms["columns_view"] == "all":
        view_cols = base.columns.tolist()
    else:
        view_cols = [c for c in perms["columns_view"] if c in base.columns]

    c1, c2, c3 = st.columns(3)
    f_depto = c1.multiselect("Departamento", sorted(base["DEPTO"].dropna().astype(str).unique().tolist()) if not base.empty else [])
    f_semana = c2.multiselect("Semana", sorted(pd.to_numeric(base["Semana"], errors="coerce").dropna().unique().tolist()) if not base.empty else [])
    f_emp = c3.text_input("Empleado (contiene)")

    fdf = base.copy()
    if not fdf.empty:
        if f_depto: fdf = fdf[fdf["DEPTO"].astype(str).isin(f_depto)]
        if f_semana: fdf = fdf[pd.to_numeric(fdf["Semana"], errors="coerce").isin(f_semana)]
        if f_emp: fdf = fdf[fdf["EMPLEADO"].astype(str).str.contains(f_emp, case=False, na=False)]

        k1, k2, k3 = st.columns(3)
        k1.metric("Piezas", f"{pd.to_numeric(fdf['Produce'], errors='coerce').sum(skipna=True):,.0f}")
        k2.metric("Minutos proceso", f"{pd.to_numeric(fdf['Minutos_Proceso'], errors='coerce').sum(skipna=True):,.0f}")
        k3.metric("Registros", f"{len(fdf):,}")

        st.dataframe(fdf[view_cols].sort_values(by="Inicio", ascending=False), use_container_width=True, hide_index=True)
    else:
        st.info("Sin registros aún.")

# -------- Editar / Auditar --------
with tabs[2]:
    perms = ROLE_PERMS.get(st.session_state.role, ROLE_PERMS["Supervisor"])
    st.subheader("Edición controlada y bitácora")

    db = load_parquet(DB_FILE)
    if db.empty:
        st.info("No hay datos para editar.")
    else:
        idx = st.number_input("ID de registro (0 .. n-1)", min_value=0, max_value=len(db)-1, step=1, value=0)
        row = db.iloc[int(idx)].to_dict()
        st.write("Registro actual:", row)

        if perms["editable"]:
            with st.form("edit_form"):
                c1, c2 = st.columns(2)
                with c1:
                    empleado = st.text_input("Empleado", value=str(row.get("EMPLEADO","")))
                    depto = st.text_input("DEPTO", value=str(row.get("DEPTO","")))
                    columna = st.number_input("COLUMNA", value=int(row.get("COLUMNA") or 1), min_value=1, step=1)
                    modelo = st.text_input("MODELO", value=str(row.get("MODELO","")))
                    produce = st.number_input("Produce", value=int(row.get("Produce") or 0), min_value=0, step=1)
                with c2:
                    inicio = st.datetime_input("Inicio", value=pd.to_datetime(row.get("Inicio")) if pd.notna(row.get("Inicio")) else datetime.now())
                    fin = st.datetime_input("Fin", value=pd.to_datetime(row.get("Fin")) if pd.notna(row.get("Fin")) else datetime.now())
                    min_std = st.number_input("Minutos_Std", value=float(row.get("Minutos_Std") or 0.0), min_value=0.0, step=0.5)
                submitted = st.form_submit_button("💾 Guardar cambios")
                if submitted:
                    before = db.iloc[int(idx)].to_dict()
                    db.at[int(idx), "EMPLEADO"] = empleado
                    db.at[int(idx), "DEPTO"] = depto
                    db.at[int(idx), "COLUMNA"] = columna
                    db.at[int(idx), "MODELO"] = modelo
                    db.at[int(idx), "Produce"] = produce
                    db.at[int(idx), "Inicio"] = inicio
                    db.at[int(idx), "Fin"] = fin
                    db.at[int(idx), "Minutos_Proceso"] = (pd.to_datetime(fin) - pd.to_datetime(inicio)).total_seconds()/60.0
                    db.at[int(idx), "Minutos_Std"] = min_std
                    db.at[int(idx), "Semana"] = week_number(inicio)
                    save_parquet(db, DB_FILE)
                    after = db.iloc[int(idx)].to_dict()
                    log_audit(st.session_state.user, "update", int(idx), {"before": before, "after": after})
                    st.success("Actualizado ✅")

        if perms["can_delete"]:
            if st.button("🗑️ Eliminar registro seleccionado"):
                before = db.iloc[int(idx)].to_dict()
                db = db.drop(db.index[int(idx)]).reset_index(drop=True)
                save_parquet(db, DB_FILE)
                log_audit(st.session_state.user, "delete", int(idx), {"before": before})
                st.success("Eliminado ✅")

        st.markdown("---")
        st.subheader("Bitácora de auditoría")
        audit = load_parquet(AUDIT_FILE)
        if audit.empty:
            st.caption("Sin eventos aún.")
        else:
            st.dataframe(audit.sort_values(by="ts", ascending=False).head(200), use_container_width=True, hide_index=True)

# -------- Excel (exacto) --------
with tabs[3]:
    st.subheader("Cálculo exacto desde Excel")
    up = st.file_uploader("Sube tu Excel original (.xlsx) con hoja **Tiempos**", type=["xlsx"])
    if up is not None:
        struct = read_excel_struct(up)
        data = struct["data"]
        dept_df = struct["dept_df"]
        result = compute_destajo_exact(data, dept_df)

        core_cols = ['DEPTO','COLUMNA','EMPLEADO','MODELO','Produce','Minutos_Proceso','Minutos_Std','Eficiencia_calc','Tarifa_hr','Tarifa_min','Destajo_Unitario_calc','Pago_total']
        core = result[[c for c in core_cols if c in result.columns]].copy()

        k1, k2, k3 = st.columns(3)
        k1.metric("Piezas", f"{pd.to_numeric(core['Produce'], errors='coerce').sum(skipna=True):,.0f}")
        k2.metric("Minutos proceso", f"{pd.to_numeric(core['Minutos_Proceso'], errors='coerce').sum(skipna=True):,.0f}")
        k3.metric("Pago total", f"${pd.to_numeric(core['Pago_total'], errors='coerce').sum(skipna=True):,.2f}")

        st.dataframe(core, use_container_width=True, hide_index=True)
        csv = core.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Descargar CSV (cálculo exacto)", data=csv, file_name="destajo_exacto.csv", mime="text/csv")
    else:
        st.caption("Súbelo y replicamos Eficiencia, Destajo Unitario y Pago total.")

# -------- Admin --------
with tabs[4]:
    if st.session_state.role != "Admin":
        st.info("Solo Admin puede administrar.")
    else:
        st.subheader("Administración")
        st.markdown("**Usuarios (users.csv)** — columnas: `user, role, pin`. Roles válidos: Admin, Supervisor, Nominas, RRHH, Productividad.")
        st.code("user,role,pin\nadmin,Admin,1234\nsupervisor,Supervisor,1111\nnominas,Nominas,2222\nrrhh,RRHH,3333\nproductividad,Productividad,4444", language="text")

        st.markdown("**API** (token via `st.secrets['API_TOKEN']` o var de entorno `API_TOKEN`):")
        st.code("""# GET
# ?api=ingest&token=TU_TOKEN&data=<base64url(JSON)>
# JSON ejemplo:
{
  "DEPTO":"TAPIZ","COLUMNA":10,"EMPLEADO":"L1-36","MODELO":"SALLY 3-2",
  "Produce":12,
  "Inicio":"2025-09-17T08:00:00",
  "Fin":"2025-09-17T09:00:00",
  "Minutos_Std":20
}""", language="json")
        st.markdown("**cURL ejemplo (Linux/Mac):**")
        st.code("""DATA='{"DEPTO":"TAPIZ","COLUMNA":10,"EMPLEADO":"L1-36","MODELO":"SALLY 3-2","Produce":12,"Inicio":"2025-09-17T08:00:00","Fin":"2025-09-17T09:00:00","Minutos_Std":20}'
B64=$(python - <<'EOF'
import base64,sys; print(base64.urlsafe_b64encode(sys.argv[1].encode()).decode().rstrip('='))
EOF "$DATA")
echo "https://<tu-app-streamlit>/?api=ingest&token=<TU_TOKEN>&data=$B64"
""", language="bash")

        st.markdown("---")
        st.markdown("**Base de datos**")
        db = load_parquet(DB_FILE)
        st.write(f"Registros: {len(db)}")
        if not db.empty:
            st.dataframe(db.tail(50), use_container_width=True, hide_index=True)
            colA, colB = st.columns(2)
            if colA.download_button("⬇️ Exportar CSV", data=db.to_csv(index=False).encode("utf-8"), file_name="registros.csv", mime="text/csv"):
                pass
            if colB.button("🗑️ Borrar todo (irrevocable)"):
                os.remove(DB_FILE) if os.path.exists(DB_FILE) else None
                st.success("Base de datos borrada")
                st.rerun()

st.caption("© 2025 · Destajo móvil con roles, auditoría y API por query params. Para producción real, considera FastAPI detrás de un reverse proxy.")
