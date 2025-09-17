# app.py — Destajo Exacto + Roles + Captura
import os
from datetime import datetime, date, time, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import streamlit as st

APP_TITLE = "Destajo · Producción y Destajo (Móvil)"
st.set_page_config(page_title=APP_TITLE, page_icon="🛠️", layout="centered")

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
DB_FILE = os.path.join(DATA_DIR, "registros.parquet")
USERS_FILE = "users.csv"  # user,role,pin

# ------------------ Utilidades ------------------
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

def load_db():
    if os.path.exists(DB_FILE):
        try:
            return pd.read_parquet(DB_FILE)
        except Exception:
            try:
                return pd.read_csv(DB_FILE.replace(".parquet",".csv"))
            except Exception:
                return pd.DataFrame()
    return pd.DataFrame()

def save_db(df: pd.DataFrame):
    if df is None or df.empty:
        return
    df.to_parquet(DB_FILE, index=False)

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

    # localizar encabezado con CLAVE/DEPTO/COLUMNA/MODELO y Día/Hora
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

    # tabla departamentos (tomamos las últimas 4 columnas si encajan)
    dept_df = None
    right_block = data.iloc[:, -4:].copy()
    rb_cols = [str(c).strip().upper() for c in right_block.columns]
    if "DEPARTAMENTOS" in rb_cols and ("COLUMNA" in rb_cols) and any(x in rb_cols for x in ["$/HR","$/HR "]):
        dept_df = right_block
    else:
        # intentar localizar por nombre exacto
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
        # normalizar nombres
        col_col = [c for c in dd.columns if str(c).strip().upper()=="COLUMNA"]
        hr_col = [c for c in dd.columns if "$/HR" in str(c).upper()]
        if col_col and hr_col:
            tmp = dd[[col_col[0], hr_col[0]]].dropna()
            tmp[col_col[0]] = pd.to_numeric(tmp[col_col[0]], errors='coerce')
            tmp[hr_col[0]] = pd.to_numeric(tmp[hr_col[0]], errors='coerce')
            rate_per_hr_map = {int(r[col_col[0]]): float(r[hr_col[0]]) for _, r in tmp.dropna().iterrows()}

    # minutos de proceso (si faltan)
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

    # Eficiencia
    out['Eficiencia_calc'] = np.where(out['Minutos_Proceso']>0,
                                      (out['Produce'] * out['Minutos_Std']) / out['Minutos_Proceso'],
                                      np.nan)
    out['Eficiencia_calc'] = out['Eficiencia_calc'].clip(upper=1.0)

    # Tarifa por minuto desde COLUMNA -> $/hr / 60
    if 'COLUMNA' in out.columns and rate_per_hr_map:
        colnum = pd.to_numeric(out['COLUMNA'], errors='coerce').astype('Int64')
        out['Tarifa_hr'] = colnum.map(rate_per_hr_map).astype(float)
        out['Tarifa_min'] = out['Tarifa_hr'] / 60.0
    else:
        out['Tarifa_hr'] = np.nan
        out['Tarifa_min'] = np.nan

    # Destajo unitario y pago
    out['Destajo_Unitario_calc'] = out['Minutos_Std'] * out['Tarifa_min']
    out['Pago_total'] = out['Destajo_Unitario_calc'] * out['Produce'] * out['Eficiencia_calc']

    # Semana
    if 'Inicio' in out.columns:
        out['Semana'] = out['Inicio'].dt.isocalendar().week

    return out

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

if not st.session_state.user:
    login_box()
    st.stop()

# ------------------ UI principal ------------------
st.sidebar.success(f"Sesión: {st.session_state.user} ({st.session_state.role})")
if st.sidebar.button("Cerrar sesión"):
    for k in ["user","role"]:
        st.session_state.pop(k, None)
    st.rerun()

tabs = st.tabs(["📲 Captura", "📈 Tablero", "📚 Excel (cálculo exacto)", "🛠️ Admin"])

# -------- Captura (Supervisor/Productividad/Admin) --------
with tabs[0]:
    if st.session_state.role not in ["Supervisor","Productividad","Admin"]:
        st.info("Tu rol no tiene permisos para capturar.")

    else:
        st.subheader("Captura móvil de tiempos")
        with st.form("form_captura", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                operador = st.text_input("Empleado*", placeholder="Nombre o ID")
                depto = st.selectbox("Departamento*", options=["TAPIZ","COSTURA","CARPINTERIA","COJINERIA","CORTE","ARMADO","HILADO","COLCHONETA","OTRO"])
                col_depto = st.number_input("Columna (depto)*", min_value=1, step=1)
                modelo = st.text_input("Modelo*", placeholder="Ej. MARIE 2 GAIA")
                produce = st.number_input("Produce (piezas)*", min_value=1, step=1, value=1)
            with c2:
                dia_i = st.date_input("Día inicio*", value=date.today())
                hora_i = st.time_input("Hora inicio*", value=datetime.now().time().replace(second=0, microsecond=0))
                dia_f = st.date_input("Día fin*", value=date.today())
                hora_f = st.time_input("Hora fin*", value=(datetime.now()+timedelta(minutes=30)).time().replace(second=0, microsecond=0))
                minutos_std = st.number_input("Minutos Std (por pieza)*", min_value=0.0, step=0.5)

            if st.form_submit_button("➕ Agregar registro", use_container_width=True):
                inicio = datetime.combine(dia_i, hora_i)
                fin = datetime.combine(dia_f, hora_f)
                minutos_proceso = (fin - inicio).total_seconds()/60.0
                row = {
                    "DEPTO": depto,
                    "COLUMNA": col_depto,
                    "EMPLEADO": operador,
                    "MODELO": modelo,
                    "Produce": produce,
                    "Inicio": inicio,
                    "Fin": fin,
                    "Minutos_Proceso": minutos_proceso,
                    "Minutos_Std": minutos_std,
                    "Semana": week_number(inicio),
                    "Fuente": "CAPTURA_APP",
                    "Usuario": st.session_state.user,
                }
                db = load_db()
                db = pd.concat([db, pd.DataFrame([row])], ignore_index=True)
                save_db(db)
                st.success("Registro guardado ✅")

# -------- Tablero (todas las áreas) --------
with tabs[1]:
    st.subheader("Producción en vivo")
    base = load_db()

    # filtros
    c1, c2, c3 = st.columns(3)
    f_depto = c1.multiselect("Departamento", sorted(base["DEPTO"].dropna().astype(str).unique().tolist()) if not base.empty else [])
    f_semana = c2.multiselect("Semana", sorted(pd.to_numeric(base["Semana"], errors="coerce").dropna().unique().tolist()) if not base.empty else [])
    f_emp = c3.text_input("Empleado (contiene)")

    fdf = base.copy()
    if not fdf.empty:
        if f_depto: fdf = fdf[fdf["DEPTO"].astype(str).isin(f_depto)]
        if f_semana: fdf = fdf[pd.to_numeric(fdf["Semana"], errors="coerce").isin(f_semana)]
        if f_emp: fdf = fdf[fdf["EMPLEADO"].astype(str).str.contains(f_emp, case=False, na=False)]

        # KPIs
        k1, k2, k3 = st.columns(3)
        k1.metric("Piezas", f"{pd.to_numeric(fdf['Produce'], errors='coerce').sum(skipna=True):,.0f}")
        k2.metric("Minutos proceso", f"{pd.to_numeric(fdf['Minutos_Proceso'], errors='coerce').sum(skipna=True):,.0f}")
        # pago estimado se calculará en la pestaña Excel; aquí opcionalmente mostramos suma si existe
        k3.metric("Registros", f"{len(fdf):,}")

        st.dataframe(
            fdf.sort_values(by="Inicio", ascending=False),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("Sin registros aún.")

# -------- Excel (cálculo exacto 1:1) --------
with tabs[2]:
    st.subheader("Cálculo exacto desde Excel (como tu plantilla)")
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

# -------- Admin (solo Admin) --------
with tabs[3]:
    if st.session_state.role != "Admin":
        st.info("Solo Admin puede administrar usuarios y datos.")
    else:
        st.subheader("Administración")
        st.markdown("**Usuarios (users.csv)** — columnas: `user, role, pin`. Roles válidos: Admin, Supervisor, Nominas, RRHH, Productividad.")
        st.code("user,role,pin\nadmin,Admin,1234\nsupervisor,Supervisor,1111\nnominas,Nominas,2222\nrrhh,RRHH,3333\nproductividad,Productividad,4444", language="text")

        st.markdown("---")
        st.markdown("**Base de datos local**")
        db = load_db()
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

st.caption("© 2025 · Destajo móvil con roles. Fórmulas exactas basadas en tu hoja 'Tiempos'.")
