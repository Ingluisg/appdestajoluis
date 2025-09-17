# app.py — Destajo con Roles, Auditoría, API y Catálogos por Departamento
# - Departamento controla el desplegable de Empleado
# - Solo Admin puede editar tiempos
# - Cierre automático del trabajo previo del mismo empleado
# - Sin campo "Columna (depto)"

import os, json, base64
from datetime import datetime, date
from typing import Optional, Dict, Any, List

import numpy as np
import pandas as pd
import streamlit as st

APP_TITLE = "Destajo · Roles + Auditoría + API"
st.set_page_config(page_title=APP_TITLE, page_icon="🧮", layout="centered")

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
DB_FILE = os.path.join(DATA_DIR, "registros.parquet")
AUDIT_FILE = os.path.join(DATA_DIR, "audit.parquet")
USERS_FILE = "users.csv"

# ------------------ Constantes ------------------
DEPT_OPTIONS = ["COSTURA","TAPIZ","CARPINTERIA","COJINERIA","CORTE","ARMADO","HILADO","COLCHONETA","OTRO"]

# ------------------ Utilidades ------------------
def now_iso(): return datetime.now().isoformat(timespec="seconds")

def week_number(dt: Optional[datetime]):
    if pd.isna(dt) or dt is None: return np.nan
    return pd.Timestamp(dt).isocalendar().week

def load_parquet(path: str):
    if os.path.exists(path):
        try: return pd.read_parquet(path)
        except: return pd.DataFrame()
    return pd.DataFrame()

def save_parquet(df: pd.DataFrame, path: str):
    if df is None or df.empty: return
    df.to_parquet(path, index=False)

def load_users():
    if os.path.exists(USERS_FILE):
        try:
            df = pd.read_csv(USERS_FILE, dtype=str)
            df.columns = [c.strip().lower() for c in df.columns]
            return df
        except: pass
    return pd.DataFrame([
        {"user":"admin","role":"Admin","pin":"1234"},
        {"user":"supervisor","role":"Supervisor","pin":"1111"},
        {"user":"nominas","role":"Nominas","pin":"2222"},
        {"user":"rrhh","role":"RRHH","pin":"3333"},
        {"user":"productividad","role":"Productividad","pin":"4444"},
    ])

# ------------------ Catálogos ------------------
CAT_EMP = os.path.join(DATA_DIR, "cat_empleados.csv")  # columnas: departamento,empleado
CAT_MOD = os.path.join(DATA_DIR, "cat_modelos.csv")    # columna: modelo

def load_emp_catalog() -> pd.DataFrame:
    if os.path.exists(CAT_EMP):
        try:
            df = pd.read_csv(CAT_EMP, dtype=str)
            want = ["departamento","empleado"]
            for c in want:
                if c not in df.columns: return pd.DataFrame(columns=want)
            df = df.dropna(subset=["empleado"])
            df["departamento"] = df["departamento"].str.strip().str.upper()
            df["empleado"] = df["empleado"].str.strip()
            # dedupe
            df = df.drop_duplicates(subset=["departamento","empleado"]).sort_values(["departamento","empleado"])
            return df
        except:
            pass
    return pd.DataFrame(columns=["departamento","empleado"])

def save_emp_catalog(df: pd.DataFrame):
    os.makedirs(os.path.dirname(CAT_EMP), exist_ok=True)
    if not {"departamento","empleado"}.issubset(df.columns):
        return
    out = (df.dropna(subset=["empleado"])
             .assign(departamento=lambda d: d["departamento"].str.strip().str.upper(),
                     empleado=lambda d: d["empleado"].str.strip()))
    out = out[(out["departamento"]!="") & (out["empleado"]!="")]
    out.drop_duplicates(subset=["departamento","empleado"]).sort_values(["departamento","empleado"]).to_csv(CAT_EMP, index=False)

def emp_options_for(depto: str, db_hist: pd.DataFrame) -> List[str]:
    cat = load_emp_catalog()
    dep = str(depto).strip().upper()
    cat_list = cat.loc[cat["departamento"]==dep, "empleado"].dropna().astype(str).tolist()
    hist_list = []
    if not db_hist.empty and "EMPLEADO" in db_hist.columns and "DEPTO" in db_hist.columns:
        hist_list = db_hist.loc[db_hist["DEPTO"].astype(str).str.upper()==dep, "EMPLEADO"].dropna().astype(str).unique().tolist()
    merged = sorted(list(dict.fromkeys(cat_list + hist_list)))
    return merged

def add_emp_to_catalog(depto: str, empleado: str):
    dep = str(depto).strip().upper()
    emp = str(empleado).strip()
    if not dep or not emp: return
    cat = load_emp_catalog()
    cat = pd.concat([cat, pd.DataFrame([{"departamento": dep, "empleado": emp}])], ignore_index=True)
    save_emp_catalog(cat)

def load_model_catalog() -> List[str]:
    if os.path.exists(CAT_MOD):
        try:
            df = pd.read_csv(CAT_MOD, dtype=str)
            if "modelo" in df.columns:
                items = [x.strip() for x in df["modelo"].dropna().astype(str).tolist() if x.strip()]
                return sorted(list(dict.fromkeys(items)))
        except: pass
    return []

def save_model_catalog(items: List[str]):
    clean = sorted(list(dict.fromkeys([str(x).strip() for x in items if str(x).strip()])))
    pd.DataFrame({"modelo": clean}).to_csv(CAT_MOD, index=False)

# ------------------ Permisos ------------------
ROLE_PERMS = {
    "Admin": {"editable": True, "columns_view": "all", "can_delete": True},
    "Supervisor": {"editable": True, "columns_view": "all", "can_delete": False},
    "Productividad": {"editable": False, "columns_view": "all", "can_delete": False},
    "Nominas": {"editable": False, "columns_view": "all", "can_delete": False},
    "RRHH": {"editable": False, "columns_view": "all", "can_delete": False},
}

# ------------------ Auditoría ------------------
def log_audit(user: str, action: str, record_id: Optional[int], details: Dict[str, Any]):
    payload = json.dumps(details, ensure_ascii=False,
                         default=lambda o: o.isoformat() if hasattr(o, "isoformat") else str(o))
    aud = load_parquet(AUDIT_FILE)
    row = {"ts": now_iso(), "user": user, "action": action, "record_id": int(record_id) if record_id is not None else None, "details": payload}
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
            st.rerun()
        else: st.error("Usuario o PIN incorrectos.")

if "user" not in st.session_state: st.session_state.user, st.session_state.role = None, None

# ------------------ API "lite" por query params ------------------
qp = st.query_params
if qp.get("api", [None])[0] == "ingest":
    token = qp.get("token", [None])[0]
    allowed = token and (token == (st.secrets.get("API_TOKEN") if hasattr(st, "secrets") else os.getenv("API_TOKEN","devtoken")))
    if not allowed:
        st.write({"ok": False, "error": "TOKEN_INVALIDO"}); st.stop()
    b64 = qp.get("data", [None])[0]
    if not b64:
        st.write({"ok": False, "error": "FALTA_DATA"}); st.stop()
    try:
        payload = json.loads(base64.urlsafe_b64decode(b64 + "==="))
    except Exception as e:
        st.write({"ok": False, "error": f"JSON_INVALIDO: {e}"}); st.stop()
    required = ["DEPTO","EMPLEADO","MODELO","Produce","Inicio","Fin","Minutos_Std"]
    missing = [k for k in required if k not in payload]
    if missing:
        st.write({"ok": False, "error": f"FALTAN_CAMPOS: {missing}"}); st.stop()
    db = load_parquet(DB_FILE)
    inicio = pd.to_datetime(payload["Inicio"], errors="coerce")
    fin = pd.to_datetime(payload["Fin"], errors="coerce")
    minutos_proceso = (fin - inicio).total_seconds()/60.0 if pd.notna(inicio) and pd.notna(fin) else np.nan
    row = {
        "DEPTO": str(payload["DEPTO"]).strip().upper(), "EMPLEADO": payload["EMPLEADO"], "MODELO": payload["MODELO"],
        "Produce": payload["Produce"], "Inicio": inicio, "Fin": fin,
        "Minutos_Proceso": minutos_proceso, "Minutos_Std": payload["Minutos_Std"],
        "Semana": week_number(inicio), "Usuario": "api-client", "Estimado": False,
    }
    db = pd.concat([db, pd.DataFrame([row])], ignore_index=True)
    save_parquet(db, DB_FILE); log_audit("api-client", "create", int(len(db)-1), {"via":"api", "row": row})
    st.write({"ok": True, "inserted_id": int(len(db)-1)}); st.stop()

# ------------------ UI ------------------
if not st.session_state.user:
    login_box(); st.stop()

perms = ROLE_PERMS.get(st.session_state.role, ROLE_PERMS["Supervisor"])
st.sidebar.success(f"Sesión: {st.session_state.user} ({st.session_state.role})")
if st.sidebar.button("Cerrar sesión"):
    for k in ["user","role"]: st.session_state.pop(k, None)
    st.rerun()

tabs = st.tabs(["📲 Captura", "📈 Tablero", "✏️ Editar / Auditar", "🛠️ Admin"])

# -------- 📲 Captura --------
with tabs[0]:
    st.subheader("Captura móvil")
    if not perms["editable"]:
        st.info("Sin permisos para capturar.")
    else:
        db_prev = load_parquet(DB_FILE)

        with st.form("form_captura", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                depto = st.selectbox("Departamento*", options=DEPT_OPTIONS, index=0)
                # Empleado depende del departamento
                empleados_opts = emp_options_for(depto, db_prev)
                emp_choice = st.selectbox("Empleado*", ["— Selecciona —"] + empleados_opts + ["Otro…"])
                empleado_manual = st.text_input("Empleado (nuevo)*", placeholder="Nombre/ID") if emp_choice=="Otro…" else ""
            with c2:
                # Modelos (globales, pero puedes segmentarlos igual si lo pides)
                modelos_hist = sorted(db_prev["MODELO"].dropna().astype(str).unique().tolist()) if "MODELO" in db_prev.columns else []
                modelos_cat = load_model_catalog()
                modelos_opts = sorted(list(dict.fromkeys(modelos_cat + modelos_hist)))
                modelo_choice = st.selectbox("Modelo*", ["— Selecciona —"] + modelos_opts + ["Otro…"])
                modelo_manual = st.text_input("Modelo (nuevo)*", placeholder="Ej. MARIE 2 GAIA") if modelo_choice=="Otro…" else ""
                produce = st.number_input("Produce (piezas)*", min_value=1, step=1, value=1)
                minutos_std = st.number_input("Minutos Std (por pieza)*", min_value=0.0, step=0.5, value=0.0)

            # --- Botón agregar ---
            if st.form_submit_button("➕ Agregar registro", use_container_width=True):
                empleado = empleado_manual if emp_choice=="Otro…" else (emp_choice if emp_choice!="— Selecciona —" else "")
                modelo = modelo_manual if modelo_choice=="Otro…" else (modelo_choice if modelo_choice!="— Selecciona —" else "")
                if not empleado or not modelo:
                    st.error("Empleado y Modelo son obligatorios.")
                else:
                    # Aprender en catálogos
                    if emp_choice=="Otro…":
                        add_emp_to_catalog(depto, empleado)
                    if modelo_choice=="Otro…":
                        save_model_catalog(list(set(load_model_catalog()+[modelo])))

                    # Cerrar trabajo abierto del mismo empleado
                    ahora = datetime.now()
                    db = load_parquet(DB_FILE)
                    if not db.empty and {"EMPLEADO","Inicio","Fin"}.issubset(db.columns):
                        try:
                            db["Inicio"] = pd.to_datetime(db["Inicio"], errors="coerce")
                            db["Fin"] = pd.to_datetime(db["Fin"], errors="coerce")
                        except: pass
                        abiertos = db[(db["EMPLEADO"].astype(str)==str(empleado)) & db["Inicio"].notna() & db["Fin"].notna() & (db["Inicio"]==db["Fin"])]
                        if not abiertos.empty:
                            idx_last = abiertos.index[-1]
                            ini_prev = pd.to_datetime(db.at[idx_last,"Inicio"])
                            db.at[idx_last,"Fin"] = ahora
                            db.at[idx_last,"Minutos_Proceso"] = (ahora - ini_prev).total_seconds()/60.0
                            db.at[idx_last,"Estimado"] = False
                            save_parquet(db, DB_FILE)
                            log_audit(st.session_state.user, "auto-close", int(idx_last), {"empleado": empleado, "cerrado": ahora})

                    # Insertar nuevo registro abierto
                    row = {
                        "DEPTO": str(depto).strip().upper(),
                        "EMPLEADO": empleado,
                        "MODELO": modelo,
                        "Produce": produce,
                        "Inicio": ahora,
                        "Fin": ahora,                # abierto hasta que se asigne otra tarea o se cierre
                        "Minutos_Proceso": 0.0,      # se calculará al cerrar
                        "Minutos_Std": minutos_std,
                        "Semana": week_number(ahora),
                        "Usuario": st.session_state.user,
                        "Estimado": True,
                    }
                    db = load_parquet(DB_FILE)
                    db = pd.concat([db, pd.DataFrame([row])], ignore_index=True)
                    save_parquet(db, DB_FILE)
                    log_audit(st.session_state.user, "create", int(len(db)-1), {"via":"ui", "row": row})
                    st.success("Registro guardado ✅ (cierre automático del previo si existía)")

# -------- 📈 Tablero --------
with tabs[1]:
    st.subheader("Producción en vivo")
    base = load_parquet(DB_FILE)
    if base.empty:
        st.info("Sin registros.")
    else:
        c1, c2, c3 = st.columns(3)
        f_depto = c1.multiselect("Departamento", sorted(base["DEPTO"].dropna().astype(str).unique().tolist()) if "DEPTO" in base.columns else [])
        f_semana = c2.multiselect("Semana", sorted(pd.to_numeric(base["Semana"], errors="coerce").dropna().unique().tolist()) if "Semana" in base.columns else [])
        f_emp = c3.text_input("Empleado (contiene)")

        fdf = base.copy()
        if not fdf.empty:
            if f_depto: fdf = fdf[fdf["DEPTO"].astype(str).isin(f_depto)]
            if f_semana: fdf = fdf[pd.to_numeric(fdf["Semana"], errors="coerce").isin(f_semana)]
            if f_emp: fdf = fdf[fdf["EMPLEADO"].astype(str).str.contains(f_emp, case=False, na=False)]

        st.dataframe(fdf.sort_values(by="Inicio", ascending=False), use_container_width=True, hide_index=True)

# -------- ✏️ Editar / Auditar --------
with tabs[2]:
    st.subheader("Edición (solo Admin mueve tiempos) + Bitácora")
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
                    depto = st.selectbox("Departamento", options=DEPT_OPTIONS, index=max(0, DEPT_OPTIONS.index(str(row.get("DEPTO","OTRO")).upper())) if str(row.get("DEPTO","")).upper() in DEPT_OPTIONS else 0)
                    empleado = st.text_input("Empleado", value=str(row.get("EMPLEADO","")))
                    modelo = st.text_input("Modelo", value=str(row.get("MODELO","")))
                    produce = st.number_input("Produce", value=int(row.get("Produce") or 0), min_value=0)
                    min_std = st.number_input("Minutos_Std", value=float(row.get("Minutos_Std") or 0.0), min_value=0.0, step=0.5)
                with c2:
                    ini_raw = pd.to_datetime(row.get("Inicio"), errors="coerce")
                    fin_raw = pd.to_datetime(row.get("Fin"), errors="coerce")
                    if st.session_state.role=="Admin":
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
                    before = db.iloc[int(idx)].to_dict()
                    db.at[int(idx),"DEPTO"] = str(depto).strip().upper()
                    db.at[int(idx),"EMPLEADO"] = empleado
                    db.at[int(idx),"MODELO"] = modelo
                    db.at[int(idx),"Produce"] = produce
                    db.at[int(idx),"Minutos_Std"] = min_std
                    if st.session_state.role=="Admin":
                        db.at[int(idx),"Inicio"] = inicio
                        db.at[int(idx),"Fin"] = fin
                        db.at[int(idx),"Minutos_Proceso"] = (pd.to_datetime(fin) - pd.to_datetime(inicio)).total_seconds()/60.0
                    save_parquet(db, DB_FILE)
                    after = db.iloc[int(idx)].to_dict()
                    log_audit(st.session_state.user, "update", int(idx), {"before": before, "after": after})
                    st.success("Actualizado ✅")

        st.markdown("---")
        st.subheader("Bitácora")
        audit = load_parquet(AUDIT_FILE)
        if audit.empty:
            st.caption("Sin eventos aún.")
        else:
            st.dataframe(audit.sort_values(by="ts", ascending=False).head(300), use_container_width=True, hide_index=True)

# -------- 🛠️ Admin --------
with tabs[3]:
    if st.session_state.role!="Admin":
        st.info("Solo Admin puede administrar.")
    else:
        st.subheader("Catálogo de Empleados por Departamento")
        emp_cat = load_emp_catalog()
        # Editor simple
        cA, cB = st.columns([1,2])
        with cA:
            dep_new = st.selectbox("Departamento", DEPT_OPTIONS, index=0, key="dep_new")
            emp_new = st.text_input("➕ Empleado nuevo")
            if st.button("Guardar empleado"):
                if emp_new.strip():
                    add_emp_to_catalog(dep_new, emp_new.strip())
                    st.success("Empleado agregado al catálogo"); st.rerun()
        with cB:
            st.dataframe(emp_cat, use_container_width=True, hide_index=True)
        st.download_button("⬇️ Descargar cat_empleados.csv", data=emp_cat.to_csv(index=False).encode("utf-8"),
                           file_name="cat_empleados.csv", mime="text/csv")
        up_emp = st.file_uploader("Subir cat_empleados.csv", type=["csv"])
        if up_emp is not None:
            try:
                dfu = pd.read_csv(up_emp, dtype=str)
                if {"departamento","empleado"}.issubset(dfu.columns):
                    save_emp_catalog(dfu)
                    st.success("Catálogo de empleados actualizado"); st.rerun()
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
            st.success("Modelo agregado"); st.rerun()
        st.download_button("⬇️ Descargar cat_modelos.csv",
                           data=pd.DataFrame({"modelo": load_model_catalog()}).to_csv(index=False).encode("utf-8"),
                           file_name="cat_modelos.csv", mime="text/csv")
        up_mod = st.file_uploader("Subir cat_modelos.csv", type=["csv"], key="up_mod")
        if up_mod is not None:
            try:
                dfm = pd.read_csv(up_mod, dtype=str)
                if "modelo" in dfm.columns:
                    save_model_catalog(dfm["modelo"].dropna().astype(str).tolist())
                    st.success("Catálogo de modelos actualizado"); st.rerun()
                else:
                    st.error("El CSV debe tener columna: modelo")
            except Exception as e:
                st.error(f"CSV inválido: {e}")

st.caption("© 2025 · Destajo móvil con roles, auditoría, API y catálogos por departamento.")
