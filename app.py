# app.py — Destajo con Planeación PRIV (solo Planeación/Admin), Alertas y Reglas
import os, json, base64
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any

import numpy as np
import pandas as pd
import streamlit as st

APP_TITLE = "Destajo · Planeación PRIV + Roles + Alertas"
st.set_page_config(page_title=APP_TITLE, page_icon="📅", layout="centered")

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
DB_FILE = os.path.join(DATA_DIR, "registros.parquet")
AUDIT_FILE = os.path.join(DATA_DIR, "audit.parquet")
PLAN_FILE = os.path.join(DATA_DIR, "planning.parquet")
ALERTS_FILE = os.path.join(DATA_DIR, "alerts.parquet")
USERS_FILE = "users.csv"  # user,role,pin

# ------------------ Catálogos ------------------
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

# ------------------ Utilidades ------------------
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
        try:
            df.to_parquet(path, index=False)
        except Exception:
            df.to_csv(path.replace(".parquet",".csv"), index=False)
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
    # fallback demo
    return pd.DataFrame([
        {"user":"admin","role":"Admin","pin":"1234"},
        {"user":"supervisor","role":"Supervisor","pin":"1111"},
        {"user":"planeacion","role":"Planeacion","pin":"5555"},
        {"user":"nominas","role":"Nominas","pin":"2222"},
        {"user":"rrhh","role":"RRHH","pin":"3333"},
        {"user":"productividad","role":"Productividad","pin":"4444"},
    ])

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
    if not df.empty:
        if "semana" in df.columns:
            df["semana"] = pd.to_numeric(df["semana"], errors="coerce").astype("Int64")
    return df

def save_planning(df: pd.DataFrame):
    # unicidad: modelo+corrida+semana => plan_code único
    if not df.empty:
        dup = df.duplicated(subset=["plan_code"], keep=False)
        if dup.any():
            raise ValueError("Plan_code duplicado detectado. Revisa modelo+corrida+semana.")
    save_parquet(df, PLAN_FILE)

def generate_plan_code(modelo: str, corrida: str, semana: int) -> str:
    base = f"{str(modelo).strip().upper()}|{str(corrida).strip().upper()}|W{int(semana)}"
    return base.replace(" ", "_")

def compute_plan_progress(plan_df: pd.DataFrame, registros: pd.DataFrame):
    if registros.empty or "PLAN_CODE" not in registros.columns:
        plan_df["asignado"] = 0
    else:
        asignado = registros.groupby("PLAN_CODE")["Produce"].sum(min_count=1)
        plan_df["asignado"] = plan_df["plan_code"].map(asignado).fillna(0).astype(float)
    plan_df["faltante"] = (pd.to_numeric(plan_df["programado"], errors="coerce") - plan_df["asignado"]).clip(lower=0)
    plan_df["avance_%"] = np.where(plan_df["programado"]>0, (plan_df["asignado"] / plan_df["programado"])*100, np.nan).round(1)
    return plan_df

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

# ------------------ UI ------------------
if not st.session_state.user:
    login_box(); st.stop()

role = st.session_state.role
st.sidebar.success(f"Sesión: {st.session_state.user} ({role})")
if st.sidebar.button("Cerrar sesión"):
    for k in ["user","role"]:
        st.session_state.pop(k, None)
    st.rerun()

# Construcción de tabs según permisos (Planeación es PRIVADA)
tabs_labels = []
if role in ["Planeacion","Admin"]:
    tabs_labels.append("📅 Planeación (Privado)")
tabs_labels += ["📲 Captura", "📈 Tablero", "🛠️ Admin"]
tabs = st.tabs(tabs_labels)

# -------- Planeación (solo visible si rol permitido) --------
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
                # upsert con unicidad por plan_code
                if plans.empty:
                    plans = pd.DataFrame([row])
                else:
                    if plan_code in plans["plan_code"].astype(str).tolist():
                        # update
                        mask = plans["plan_code"]==plan_code
                        for k,v in row.items():
                            plans.loc[mask, k]=v
                    else:
                        # insert
                        plans = pd.concat([plans, pd.DataFrame([row])], ignore_index=True)
                try:
                    save_planning(plans)
                except Exception as e:
                    st.error(f"No se pudo guardar: {e}")
                else:
                    st.success(f"Plan guardado ✅ Código único: {plan_code}")
                    log_audit(st.session_state.user, "plan_upsert", {"plan_code": plan_code})

        # Progreso vs registros
        db = load_parquet(DB_FILE)
        progress = compute_plan_progress(plans.copy(), db) if not plans.empty else plans
        if progress is not None and not progress.empty:
            st.dataframe(progress.sort_values(by=["semana","depto","modelo"]).reset_index(drop=True), use_container_width=True, hide_index=True)

        # Alertas auto: faltantes (para Supervisor)
        if progress is not None and not progress.empty:
            faltantes = progress[(progress["status"]=="ABIERTO") & (progress["faltante"]>0)]
            for _, r in faltantes.iterrows():
                send_alert("warning", "Supervisor",
                           "Plan con faltante por asignar",
                           f"{r['plan_code']}: faltan {int(r['faltante'])} piezas",
                           {"plan_code": r["plan_code"], "faltante": int(r["faltante"])})
    tab_idx += 1

# -------- Captura (con tope de planeación y ESPERA) --------
with tabs[tab_idx]:
    st.subheader("Captura móvil")
    deptos = list(DEPT_CATALOG.keys())
    depto = st.selectbox("Departamento*", options=deptos, index=deptos.index("TAPIZ") if "TAPIZ" in deptos else 0)
    subs = DEPT_CATALOG[depto]["sub"]
    sub = st.selectbox("Subunidad*", options=subs, index=0)

    # planes abiertos de la semana actual
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

            # Enforce límite de planeación y alertar Admin en intento de overflow
            if sel_code:
                rowp = plans[plans["plan_code"]==sel_code]
                if rowp.empty:
                    st.error("El plan seleccionado ya no existe."); st.stop()
                programado = int(rowp.iloc[0]["programado"] or 0)
                db = load_parquet(DB_FILE)
                asignado_actual = db.loc[db["PLAN_CODE"]==sel_code, "Produce"].sum()
                if asignado_actual + int(produce) > programado:
                    send_alert("error", "Admin",
                               "Intento de captura excede plan",
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
            db = pd.concat([db, pd.DataFrame([row])], ignore_index=True)
            save_parquet(db, DB_FILE)

            if espera:
                send_alert("info", "Supervisor", "Operador en espera", f"{operador} en {depto}/{sub} sin plan asignado", {"empleado": operador, "depto": depto, "subunidad": sub})

            st.success("Registro guardado ✅")
            log_audit(st.session_state.user, "capture_create", {"row": row})

# -------- Tablero (muestra alertas) --------
with tabs[tab_idx+1]:
    st.subheader("Producción en vivo + Alertas")
    base = load_parquet(DB_FILE)
    al = load_parquet(ALERTS_FILE)

    # KPIs
    if not base.empty:
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Piezas", f"{pd.to_numeric(base['Produce'], errors='coerce').sum(skipna=True):,.0f}")
        k2.metric("Minutos proceso", f"{pd.to_numeric(base['Minutos_Proceso'], errors='coerce').sum(skipna=True):,.0f}")
        k3.metric("Registros", f"{len(base):,}")
        k4.metric("En espera", f"{int(base['ESPERA'].fillna(False).sum())}")

    # Filtros básicos
    c1, c2 = st.columns(2)
    f_depto = c1.multiselect("Departamento", sorted(base["DEPTO"].dropna().astype(str).unique().tolist()) if not base.empty else [])
    f_semana = c2.multiselect("Semana", sorted(pd.to_numeric(base["Semana"], errors="coerce").dropna().unique().tolist()) if not base.empty else [])
    fdf = base.copy()
    if not fdf.empty:
        if f_depto: fdf = fdf[fdf["DEPTO"].astype(str).isin(f_depto)]
        if f_semana: fdf = fdf[pd.to_numeric(fdf["Semana"], errors="coerce").isin(f_semana)]
        st.dataframe(fdf.sort_values(by="Inicio", ascending=False), use_container_width=True, hide_index=True)
    else:
        st.info("Sin registros aún.")

    st.markdown("---")
    st.subheader("Alertas")
    if not al.empty:
        # Mostrar solo alertas del público del rol actual
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

# -------- Admin --------
with tabs[tab_idx+2]:
    if role != "Admin":
        st.info("Solo Admin puede administrar.")
    else:
        st.subheader("Administración")
        st.markdown("**Usuarios (users.csv)** — columnas: `user, role, pin`. Incluye rol `Planeacion`.")
        st.code("user,role,pin\nadmin,Admin,1234\nsupervisor,Supervisor,1111\nplaneacion,Planeacion,5555\nnominas,Nominas,2222\nrrhh,RRHH,3333\nproductividad,Productividad,4444", language="text")

        st.markdown("**Base de datos de registros**")
        db = load_parquet(DB_FILE)
        st.write(f"Registros: {len(db)}")
        if not db.empty:
            st.dataframe(db.tail(50), use_container_width=True, hide_index=True)
            colA, colB = st.columns(2)
            colA.download_button("⬇️ Exportar CSV", data=db.to_csv(index=False).encode("utf-8"), file_name="registros.csv", mime="text/csv")
            if colB.button("🗑️ Borrar todo (irrevocable)"):
                os.remove(DB_FILE) if os.path.exists(DB_FILE) else None
                st.success("Base de datos borrada"); st.rerun()

        st.markdown("---")
        st.markdown("**Planeación**")
        plans = load_planning()
        st.write(f"Planes: {0 if plans is None else len(plans)}")
        if plans is not None and not plans.empty:
            st.dataframe(plans.sort_values(by=['semana','depto']).tail(100), use_container_width=True, hide_index=True)
            st.download_button("⬇️ Exportar Planeación CSV", data=plans.to_csv(index=False).encode("utf-8"), file_name="planning.csv", mime="text/csv")
