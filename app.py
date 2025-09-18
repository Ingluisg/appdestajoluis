# app.py — Destajo con Planeación PRIV + Captura + Tablero + Admin
# - Planeación visible SOLO para roles Planeacion/Admin
# - Código único de plan: MODELO|CORRIDA|W<semana>
# - Captura con tope de planeación y alertas (overflow -> Admin; operador en espera -> Supervisor)
# - Tablero con KPIs y alertas por rol
# - Admin con export/borrado + auditoría
# - Fix: usa st.query_params y garantiza columnas ESPERA/PLAN_CODE

import os, json, base64
from datetime import datetime, date, timedelta
from typing import Dict, Any

import numpy as np
import pandas as pd
import streamlit as st

APP_TITLE = "Destajo · Planeación PRIV + Roles + Alertas"
st.set_page_config(page_title=APP_TITLE, page_icon="📅", layout="centered")

# ------------------ Paths ------------------
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
DB_FILE = os.path.join(DATA_DIR, "registros.parquet")
AUDIT_FILE = os.path.join(DATA_DIR, "audit.parquet")
PLAN_FILE = os.path.join(DATA_DIR, "planning.parquet")
ALERTS_FILE = os.path.join(DATA_DIR, "alerts.parquet")
USERS_FILE = "users.csv"  # user,role,pin

# ------------------ Catálogos base ------------------
DEPT_CATALOG = {
    "TAPIZ":      {"sub": ["LÍNEA 1","LÍNEA 2","LÍNEA 3","LÍNEA 4"], "columna": 10},
    "COSTURA":    {"sub": ["LÍNEA A","LÍNEA B","LÍNEA C"],           "columna": 4},
    "CARPINTERIA":{"sub": ["CELDA 1","CELDA 2"],                      "columna": 6},
    "COJINERIA":  {"sub": ["MÓDULO 1","MÓDULO 2"],                    "columna": 13},
    "CORTE":      {"sub": ["MESA CORTE"],                             "columna": 3},
    "ARMADO":     {"sub": ["MESA 1","MESA 2","MESA 3"],               "columna": 7},
    "HILADO":     {"sub": ["H1","H2"],                                "columna": 12},
    "COLCHONETA": {"sub": ["C1","C2"],                                "columna": 9},
    "OTRO":       {"sub": ["GENERAL"],                                "columna": 1},
}

# ------------------ Utils ------------------
def now_iso():
    return datetime.now().isoformat(timespec="seconds")

def week_number(dt):
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
    if df is None:
        return
    if df.empty:
        # fallback CSV si el host no soporta pyarrow
        try:
            df.to_parquet(path, index=False)
        except Exception:
            df.to_csv(path.replace(".parquet",".csv"), index=False)
        return
    df.to_parquet(path, index=False)

def ensure_col(df, name, default_value):
    if df is None or df.empty:
        return df
    if name not in df.columns:
        df[name] = default_value
    return df

# ------------------ Auth ------------------
def load_users():
    if os.path.exists(USERS_FILE):
        try:
            df = pd.read_csv(USERS_FILE, dtype=str)
            df.columns = [c.strip().lower() for c in df.columns]
            return df
        except Exception:
            pass
    # fallback demo
    return pd.DataFrame([
        {"user":"admin","role":"Admin","pin":"1234"},
        {"user":"supervisor","role":"Supervisor","pin":"1111"},
        {"user":"planeacion","role":"Planeacion","pin":"5555"},
        {"user":"nominas","role":"Nominas","pin":"2222"},
        {"user":"rrhh","role":"RRHH","pin":"3333"},
        {"user":"productividad","role":"Productividad","pin":"4444"},
    ])

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
    st.session_state.user = None
    st.session_state.role = None

# ------------------ Auditoría y Alertas ------------------
def log_audit(user: str, action: str, details: Dict[str, Any]):
    aud = load_parquet(AUDIT_FILE)
    row = {"ts": now_iso(), "user": user, "action": action, "details": json.dumps(details, ensure_ascii=False)}
    aud = pd.concat([aud, pd.DataFrame([row])], ignore_index=True)
    save_parquet(aud, AUDIT_FILE)

def send_alert(level: str, audience: str, title: str, message: str, payload: Dict[str,Any]):
    al = load_parquet(ALERTS_FILE)
    row = {"ts": now_iso(), "level": level, "audience": audience, "title": title, "message": message, "payload": json.dumps(payload, ensure_ascii=False)}
    al = pd.concat([al, pd.DataFrame([row])], ignore_index=True)
    save_parquet(al, ALERTS_FILE)

# ------------------ Planeación ------------------
def load_planning():
    df = load_parquet(PLAN_FILE)
    if not df.empty and "semana" in df.columns:
        df["semana"] = pd.to_numeric(df["semana"], errors="coerce").astype("Int64")
    return df

def save_planning(df: pd.DataFrame):
    if not df.empty:
        dup = df.duplicated(subset=["plan_code"], keep=False)
        if dup.any():
            raise ValueError("Plan_code duplicado. Revisa modelo+corrida+semana.")
    save_parquet(df, PLAN_FILE)

def generate_plan_code(modelo: str, corrida: str, semana: int) -> str:
    base = f"{str(modelo).strip().upper()}|{str(corrida).strip().upper()}|W{int(semana)}"
    return base.replace(" ", "_")

def compute_plan_progress(plan_df: pd.DataFrame, registros: pd.DataFrame):
    if plan_df is None or plan_df.empty:
        return plan_df
    if registros.empty or "PLAN_CODE" not in registros.columns:
        plan_df["asignado"] = 0
    else:
        asignado = registros.groupby("PLAN_CODE")["Produce"].sum(min_count=1)
        plan_df["asignado"] = plan_df["plan_code"].map(asignado).fillna(0).astype(float)
    plan_df["faltante"] = (pd.to_numeric(plan_df["programado"], errors="coerce") - plan_df["asignado"]).clip(lower=0)
    plan_df["avance_%"] = np.where(plan_df["programado"]>0, (plan_df["asignado"] / plan_df["programado"])*100, np.nan).round(1)
    return plan_df

# ------------------ API lite (ingest) — con st.query_params ------------------
qp = st.query_params  # reemplaza al experimental
api = qp.get("api")
if api == "ingest":
    token = qp.get("token")
    if not token:
        st.write({"ok": False, "error": "TOKEN_INVALIDO"}); st.stop()
    b64 = qp.get("data")
    if not b64:
        st.write({"ok": False, "error": "FALTA_DATA"}); st.stop()
    try:
        payload = json.loads(base64.urlsafe_b64decode(b64 + "==="))
    except Exception as e:
        st.write({"ok": False, "error": f"JSON_INVALIDO: {e}"}); st.stop()

    required = ["DEPTO","COLUMNA","EMPLEADO","MODELO","Produce","Inicio","Fin","Minutos_Std"]
    miss = [k for k in required if k not in payload]
    if miss: st.write({"ok": False, "error": f"FALTAN_CAMPOS: {miss}"}); st.stop()

    db = load_parquet(DB_FILE)
    db = ensure_col(db, "ESPERA", False)
    db = ensure_col(db, "PLAN_CODE", None)

    inicio = pd.to_datetime(payload["Inicio"], errors="coerce")
    fin = pd.to_datetime(payload["Fin"], errors="coerce")
    minutos_proceso = (fin - inicio).total_seconds()/60.0 if pd.notna(inicio) and pd.notna(fin) else np.nan

    plan_code = payload.get("PLAN_CODE")
    if plan_code:
        plans = load_planning()
        rowp = plans[plans["plan_code"]==plan_code]
        if rowp.empty:
            st.write({"ok": False, "error": "PLAN_CODE_NO_EXISTE"}); st.stop()
        programado = int(rowp.iloc[0]["programado"] or 0)
        asignado_actual = db.loc[db["PLAN_CODE"]==plan_code, "Produce"].sum()
        if asignado_actual + float(payload["Produce"]) > programado:
            st.write({"ok": False, "error": "LIMITE_PLAN_SUPERADO"}); st.stop()

    row = {
        "DEPTO": payload["DEPTO"],
        "SUBUNIDAD": payload.get("SUBUNIDAD"),
        "PLAN_CODE": plan_code,
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
        "ESPERA": False if plan_code else True,
    }
    db = pd.concat([db, pd.DataFrame([row])], ignore_index=True)
    save_parquet(db, DB_FILE)
    st.write({"ok": True}); st.stop()

# ------------------ UI ------------------
if not st.session_state.user:
    login_box(); st.stop()

role = st.session_state.role
st.sidebar.success(f"Sesión: {st.session_state.user} ({role})")
if st.sidebar.button("Cerrar sesión"):
    for k in ["user","role"]:
        st.session_state.pop(k, None)
    st.rerun()

# Tabs por rol (Planeación es privada)
tabs_labels = []
if role in ["Planeacion","Admin"]:
    tabs_labels.append("📅 Planeación (Privado)")
tabs_labels += ["📲 Captura", "📈 Tablero", "🛠️ Admin"]
tabs = st.tabs(tabs_labels)

# ---- Planeación (privado) ----
tab_idx = 0
if role in ["Planeacion","Admin"]:
    with tabs[tab_idx]:
        st.subheader("Planeación semanal (solo Planeación/Admin)")
        plans = load_planning()

        with st.form("plan_form", clear_on_submit=True):
            c1,c2,c3 = st.columns(3)
            semana = c1.number_input("Semana ISO*", min_value=1, max_value=53, value= int(date.today().isocalendar().week))
            modelo = c2.text_input("Modelo*", placeholder="Ej. MARIE 2 GAIA")
            corrida = c3.text_input("Corrida (código)*", placeholder="Ej. R1 / Noche / LoteB")

            c4,c5,c6 = st.columns(3)
            depto = c4.selectbox("Departamento*", options=list(DEPT_CATALOG.keys()))
            sub = c5.selectbox("Subunidad", options=DEPT_CATALOG[depto]["sub"])
            programado = c6.number_input("Producción programada*", min_value=1, step=1, value=10)

            submitted = st.form_submit_button("➕ Agregar / Actualizar plan")
            if submitted:
                plan_code = generate_plan_code(modelo, corrida, int(semana))
                row = {
                    "plan_code": plan_code,
                    "semana": int(semana),
                    "modelo": modelo,
                    "corrida": corrida,
                    "depto": depto,
                    "subunidad": sub,
                    "programado": int(programado),
                    "status": "ABIERTO",
                    "creado_por": st.session_state.user,
                    "creado_ts": now_iso(),
                }
                if plans.empty:
                    plans = pd.DataFrame([row])
                else:
                    if plan_code in plans["plan_code"].astype(str).tolist():
                        mask = plans["plan_code"]==plan_code
                        for k,v in row.items():
                            plans.loc[mask, k]=v
                    else:
                        plans = pd.concat([plans, pd.DataFrame([row])], ignore_index=True)
                try:
                    save_planning(plans)
                    st.success(f"Plan guardado ✅ Código único: {plan_code}")
                    log_audit(st.session_state.user, "plan_upsert", {"plan_code": plan_code})
                except Exception as e:
                    st.error(f"No se pudo guardar: {e}")

        db = load_parquet(DB_FILE)
        db = ensure_col(db, "ESPERA", False)
        db = ensure_col(db, "PLAN_CODE", None)

        progress = compute_plan_progress(plans.copy(), db) if not plans.empty else plans
        if progress is not None and not progress.empty:
            st.dataframe(progress.sort_values(by=["semana","depto","modelo"]).reset_index(drop=True), use_container_width=True, hide_index=True)

    tab_idx += 1

# ---- Captura ----
with tabs[tab_idx]:
    st.subheader("Captura móvil")
    deptos = list(DEPT_CATALOG.keys())
    depto = st.selectbox("Departamento*", options=deptos, index=deptos.index("TAPIZ") if "TAPIZ" in deptos else 0)
    subs = DEPT_CATALOG[depto]["sub"]
    sub = st.selectbox("Subunidad*", options=subs, index=0)

    semana_hoy = int(date.today().isocalendar().week)
    plans = load_planning()
    planes_open = plans[(plans["status"]=="ABIERTO") & (plans["depto"]==depto) & (plans["subunidad"]==sub) & (plans["semana"]==semana_hoy)] if not plans.empty else pd.DataFrame()
    opciones_plan = ["— ESPERA (sin plan) —"] + (planes_open["plan_code"].tolist() if not planes_open.empty else [])
    plan_code_sel = st.selectbox("Plan (corrida)*", options=opciones_plan)

    col_depto = DEPT_CATALOG[depto]["columna"]

    with st.form("form_captura", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            operador = st.text_input("Empleado*", placeholder="Nombre o ID")
            modelo = st.text_input("Modelo*", placeholder="Ej. MARIE 2 GAIA")
            produce = st.number_input("Produce (piezas)*", min_value=1, step=1, value=1)
            minutos_std = st.number_input("Minutos Std (por pieza)*", min_value=0.0, step=0.5)
        with c2:
            dia = st.date_input("Fecha*", value=date.today())
            hora_i = st.time_input("Hora inicio*", value=pd.Timestamp.now().time().replace(second=0, microsecond=0))
            auto_fin = st.checkbox("Autocalcular fin (Produce×Minutos_Std)", value=True)
            if auto_fin:
                minutos_totales = produce * minutos_std
                hora_f = (pd.Timestamp.combine(dia, hora_i) + pd.Timedelta(minutes=minutos_totales)).time()
            else:
                hora_f = st.time_input("Hora fin*", value=(pd.Timestamp.now()+pd.Timedelta(minutes=30)).time().replace(second=0, microsecond=0))

        if st.form_submit_button("➕ Agregar registro", use_container_width=True):
            inicio = pd.Timestamp.combine(dia, hora_i)
            fin = pd.Timestamp.combine(dia, hora_f)
            if fin <= inicio:
                st.error("La hora fin debe ser mayor a la de inicio."); st.stop()
            if produce <= 0 or minutos_std <= 0:
                st.error("Produce y Minutos_Std deben ser > 0."); st.stop()

            espera = (plan_code_sel == "— ESPERA (sin plan) —")
            sel_code = None if espera else plan_code_sel

            # Enforce plan limit
            if sel_code:
                rowp = plans[plans["plan_code"]==sel_code]
                if rowp.empty:
                    st.error("El plan seleccionado ya no existe."); st.stop()
                programado = int(rowp.iloc[0]["programado"] or 0)
                db = load_parquet(DB_FILE)
                db = ensure_col(db, "ESPERA", False)
                db = ensure_col(db, "PLAN_CODE", None)
                asignado_actual = db.loc[db["PLAN_CODE"]==sel_code, "Produce"].sum()
                if asignado_actual + int(produce) > programado:
                    send_alert("error", "Admin","Intento de captura excede plan",
                               f"Plan {sel_code}: programado={programado}, intento={int(produce)}, asignado_actual={int(asignado_actual)}",
                               {"plan_code": sel_code, "programado": programado, "asignado_actual": int(asignado_actual), "intento": int(produce)})
                    st.error("❌ Límite de planeación superado. Contacta al Admin."); st.stop()

            row = {
                "DEPTO": depto,
                "SUBUNIDAD": sub,
                "PLAN_CODE": sel_code,
                "COLUMNA": col_depto,
                "EMPLEADO": operador,
                "MODELO": modelo,
                "Produce": int(produce),
                "Inicio": inicio,
                "Fin": fin,
                "Minutos_Proceso": (fin - inicio).total_seconds()/60.0,
                "Minutos_Std": float(minutos_std),
                "Semana": week_number(inicio),
                "Fuente": "CAPTURA_APP",
                "Usuario": st.session_state.user,
                "ESPERA": bool(espera),
            }
            db = load_parquet(DB_FILE)
            db = ensure_col(db, "ESPERA", False)
            db = ensure_col(db, "PLAN_CODE", None)
            db = pd.concat([db, pd.DataFrame([row])], ignore_index=True)
            save_parquet(db, DB_FILE)

            if espera:
                send_alert("info", "Supervisor", "Operador en espera", f"{operador} en {depto}/{sub} sin plan asignado", {"empleado": operador, "depto": depto, "subunidad": sub})

            st.success("Registro guardado ✅")
            log_audit(st.session_state.user, "capture_create", {"row": row})

# ---- Tablero ----
with tabs[tab_idx+1]:
    st.subheader("Producción en vivo + Alertas")
    base = load_parquet(DB_FILE)
    base = ensure_col(base, "ESPERA", False)
    base = ensure_col(base, "PLAN_CODE", None)

    al = load_parquet(ALERTS_FILE)

    if not base.empty:
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Piezas", f"{pd.to_numeric(base.get('Produce'), errors='coerce').sum(skipna=True):,.0f}")
        k2.metric("Minutos proceso", f"{pd.to_numeric(base.get('Minutos_Proceso'), errors='coerce').sum(skipna=True):,.0f}")
        k3.metric("Registros", f"{len(base):,}")
        k4.metric("En espera", f"{int(base['ESPERA'].fillna(False).sum())}")
    else:
        st.info("Sin registros aún.")

    st.markdown("---")
    st.subheader("Alertas")
    if not al.empty:
        if role == "Admin":
            vis = al.sort_values(by="ts", ascending=False).head(200)
        elif role == "Supervisor":
            vis = al[al["audience"].isin(["Supervisor"])].sort_values(by="ts", ascending=False).head(200)
        else:
            vis = al[al["audience"].isin(["Supervisor"])].sort_values(by="ts", ascending=False).head(200)
        if vis.empty:
            st.caption("Sin alertas para tu rol.")
        else:
            st.dataframe(vis, use_container_width=True, hide_index=True)
    else:
        st.caption("Aún no hay alertas.")

# ---- Admin ----
with tabs[tab_idx+2]:
    if role != "Admin":
        st.info("Solo Admin puede administrar.")
    else:
        st.subheader("Administración")
        st.markdown("**Usuarios (users.csv)** — columnas: `user, role, pin`. Incluye rol `Planeacion`.")
        st.code("user,role,pin\nadmin,Admin,1234\nsupervisor,Supervisor,1111\nplaneacion,Planeacion,5555\nnominas,Nominas,2222\nrrhh,RRHH,3333\nproductividad,Productividad,4444", language="text")

        st.markdown("**Base de datos de registros**")
        db = load_parquet(DB_FILE)
        db = ensure_col(db, "ESPERA", False)
        db = ensure_col(db, "PLAN_CODE", None)
        st.write(f"Registros: {len(db)}")
        if not db.empty:
            st.dataframe(db.tail(50), use_container_width=True, hide_index=True)
            colA, colB = st.columns(2)
            colA.download_button("⬇️ Exportar CSV", data=db.to_csv(index=False).encode("utf-8"), file_name="registros.csv", mime="text/csv")
            if colB.button("🗑️ Borrar todo (irrevocable)"):
                try:
                    os.remove(DB_FILE)
                except FileNotFoundError:
                    pass
                st.success("Base de datos borrada"); st.rerun()

        st.markdown("---")
        st.markdown("**Planeación**")
        plans = load_planning()
        st.write(f"Planes: {0 if plans is None else len(plans)}")
        if plans is not None and not plans.empty:
            st.dataframe(plans.sort_values(by=['semana','depto']).tail(100), use_container_width=True, hide_index=True)
            st.download_button("⬇️ Exportar Planeación CSV", data=plans.to_csv(index=False).encode("utf-8"), file_name="planning.csv", mime="text/csv")
