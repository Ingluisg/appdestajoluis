# app.py — Destajo con Roles, Auditoría, API y Catálogos (Cloud-friendly)
# Ajustes: sin Columna(depto), solo Admin puede editar tiempos.

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
CAT_EMP = os.path.join(DATA_DIR, "cat_empleados.csv")
CAT_MOD = os.path.join(DATA_DIR, "cat_modelos.csv")

def load_catalog(path: str, colname: str) -> List[str]:
    if os.path.exists(path):
        try:
            df = pd.read_csv(path, dtype=str)
            if colname in df.columns:
                items = [x.strip() for x in df[colname].dropna().astype(str).tolist()]
                return sorted(list(dict.fromkeys(items)))
        except: pass
    return []

def save_catalog(path: str, colname: str, items: List[str]):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    clean = sorted(list(dict.fromkeys([str(x).strip() for x in items if str(x).strip()])))
    pd.DataFrame({colname: clean}).to_csv(path, index=False)

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
    aud = load_parquet(AUDIT_FILE)
    row = {"ts": now_iso(), "user": user, "action": action, "record_id": record_id, "details": json.dumps(details, ensure_ascii=False)}
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

# ------------------ UI ------------------
if not st.session_state.user:
    login_box(); st.stop()

perms = ROLE_PERMS.get(st.session_state.role, ROLE_PERMS["Supervisor"])
st.sidebar.success(f"Sesión: {st.session_state.user} ({st.session_state.role})")
if st.sidebar.button("Cerrar sesión"):
    for k in ["user","role"]: st.session_state.pop(k, None)
    st.rerun()

tabs = st.tabs(["📲 Captura", "📈 Tablero", "✏️ Editar / Auditar", "🛠️ Admin"])

# -------- Captura --------
with tabs[0]:
    st.subheader("Captura móvil")
    if not perms["editable"]: st.info("Sin permisos para capturar.")
    else:
        # Catálogos + historial
        db_prev = load_parquet(DB_FILE)
        empleados_hist = sorted(db_prev["EMPLEADO"].dropna().astype(str).unique().tolist()) if "EMPLEADO" in db_prev.columns else []
        modelos_hist   = sorted(db_prev["MODELO"].dropna().astype(str).unique().tolist()) if "MODELO" in db_prev.columns else []
        empleados_opts = sorted(list(dict.fromkeys(load_catalog(CAT_EMP,"empleado")+empleados_hist)))
        modelos_opts   = sorted(list(dict.fromkeys(load_catalog(CAT_MOD,"modelo")+modelos_hist)))

        with st.form("form_captura", clear_on_submit=True):
            emp_choice = st.selectbox("Empleado*", ["— Selecciona —"]+empleados_opts+["Otro…"])
            empleado_manual = st.text_input("Empleado (nuevo)*") if emp_choice=="Otro…" else ""
            modelo_choice = st.selectbox("Modelo*", ["— Selecciona —"]+modelos_opts+["Otro…"])
            modelo_manual = st.text_input("Modelo (nuevo)*") if modelo_choice=="Otro…" else ""
            produce = st.number_input("Produce (piezas)*", min_value=1, step=1, value=1)
            minutos_std = st.number_input("Minutos Std (por pieza)*", min_value=0.0, step=0.5, value=0.0)

            if st.form_submit_button("➕ Agregar registro"):
                empleado = empleado_manual if emp_choice=="Otro…" else emp_choice
                modelo = modelo_manual if modelo_choice=="Otro…" else modelo_choice
                if not empleado or empleado=="— Selecciona —" or not modelo or modelo=="— Selecciona —":
                    st.error("Empleado y Modelo obligatorios.")
                else:
                    ahora = datetime.now()
                    db = load_parquet(DB_FILE)

                    # Cerrar trabajo previo del mismo empleado
                    if not db.empty and "EMPLEADO" in db.columns:
                        abiertos = db[(db["EMPLEADO"].astype(str)==empleado) & (db["Inicio"]==db["Fin"])]
                        if not abiertos.empty:
                            idx_last = abiertos.index[-1]
                            ini_prev = pd.to_datetime(db.at[idx_last,"Inicio"])
                            db.at[idx_last,"Fin"] = ahora
                            db.at[idx_last,"Minutos_Proceso"] = (ahora-ini_prev).total_seconds()/60.0
                            db.at[idx_last,"Estimado"] = False
                            log_audit(st.session_state.user,"auto-close",int(idx_last),{"empleado":empleado})

                    # Nuevo trabajo
                    row = {
                        "DEPTO":"", "EMPLEADO":empleado, "MODELO":modelo,
                        "Produce":produce, "Inicio":ahora, "Fin":ahora,
                        "Minutos_Proceso":0.0, "Minutos_Std":minutos_std,
                        "Semana":week_number(ahora), "Usuario":st.session_state.user, "Estimado":True,
                    }
                    db = pd.concat([db,pd.DataFrame([row])], ignore_index=True)
                    save_parquet(db,DB_FILE)
                    log_audit(st.session_state.user,"create",len(db)-1,row)
                    st.success("Registro guardado ✅")

# -------- Tablero --------
with tabs[1]:
    st.subheader("Producción en vivo")
    base = load_parquet(DB_FILE)
    if base.empty: st.info("Sin registros.")
    else: st.dataframe(base.sort_values(by="Inicio",ascending=False), use_container_width=True)

# -------- Editar / Auditar --------
with tabs[2]:
    st.subheader("Editar registros (solo Admin puede mover tiempos)")
    db = load_parquet(DB_FILE)
    if db.empty: st.info("No hay datos.")
    else:
        idx = st.number_input("ID",0,len(db)-1,0)
        row = db.iloc[int(idx)].to_dict()
        st.write("Registro actual:", row)

        if perms["editable"]:
            with st.form("edit_form"):
                empleado = st.text_input("Empleado", value=str(row.get("EMPLEADO","")))
                modelo = st.text_input("Modelo", value=str(row.get("MODELO","")))
                produce = st.number_input("Produce", value=int(row.get("Produce") or 0), min_value=0)
                min_std = st.number_input("Minutos_Std", value=float(row.get("Minutos_Std") or 0.0), min_value=0.0, step=0.5)

                if st.session_state.role=="Admin":
                    ini_raw = pd.to_datetime(row.get("Inicio"))
                    fin_raw = pd.to_datetime(row.get("Fin"))
                    ini_date = st.date_input("Inicio (fecha)", ini_raw.date() if pd.notna(ini_raw) else date.today())
                    ini_time = st.time_input("Inicio (hora)", ini_raw.time() if pd.notna(ini_raw) else datetime.now().time())
                    fin_date = st.date_input("Fin (fecha)", fin_raw.date() if pd.notna(fin_raw) else date.today())
                    fin_time = st.time_input("Fin (hora)", fin_raw.time() if pd.notna(fin_raw) else datetime.now().time())
                    inicio = datetime.combine(ini_date,ini_time)
                    fin = datetime.combine(fin_date,fin_time)
                else:
                    st.write("Inicio:", row.get("Inicio"))
                    st.write("Fin:", row.get("Fin"))
                    inicio, fin = row.get("Inicio"), row.get("Fin")

                if st.form_submit_button("💾 Guardar cambios"):
                    db.at[int(idx),"EMPLEADO"]=empleado
                    db.at[int(idx),"MODELO"]=modelo
                    db.at[int(idx),"Produce"]=produce
                    db.at[int(idx),"Minutos_Std"]=min_std
                    if st.session_state.role=="Admin":
                        db.at[int(idx),"Inicio"]=inicio
                        db.at[int(idx),"Fin"]=fin
                        db.at[int(idx),"Minutos_Proceso"]=(pd.to_datetime(fin)-pd.to_datetime(inicio)).total_seconds()/60.0
                    save_parquet(db,DB_FILE)
                    log_audit(st.session_state.user,"update",int(idx),{"after":db.iloc[int(idx)].to_dict()})
                    st.success("Actualizado ✅")

# -------- Admin --------
with tabs[3]:
    if st.session_state.role!="Admin": st.info("Solo Admin puede administrar.")
    else:
        st.subheader("Administración básica")
        st.dataframe(load_parquet(DB_FILE), use_container_width=True)
