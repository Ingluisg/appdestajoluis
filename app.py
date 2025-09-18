# app.py — Destajo con Horario Laboral, Tarifas por Área, Catálogos y PDFs
# © 2025

import os, json, base64, re, hashlib, math
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

DATA_DIR   = "data"
os.makedirs(DATA_DIR, exist_ok=True)

DB_FILE     = os.path.join(DATA_DIR, "registros.parquet")
AUDIT_FILE  = os.path.join(DATA_DIR, "audit.parquet")
USERS_FILE  = "users.csv"

# Catálogos
CAT_EMP     = os.path.join(DATA_DIR, "cat_empleados.csv")
CAT_MOD     = os.path.join(DATA_DIR, "cat_modelos.csv")

# Tarifas
RATES_CSV   = os.path.join(DATA_DIR, "rates.csv")

# Documentos PDF
DOCS_DIR    = os.path.join(DATA_DIR, "docs")
DOCS_INDEX  = os.path.join(DATA_DIR, "docs_index.csv")
THUMBS_DIR  = os.path.join(DOCS_DIR, "thumbs")
os.makedirs(THUMBS_DIR, exist_ok=True)

DEPT_OPTIONS = ["COSTURA","TAPIZ","CARPINTERIA","COJINERIA","CORTE","ARMADO","HILADO","COLCHONETA","OTRO"]

# =========================
# Funciones utilitarias
# =========================
def now_iso(): return datetime.now().isoformat(timespec="seconds")
def week_number(dt): return pd.Timestamp(dt).isocalendar().week if pd.notna(dt) else np.nan
def load_parquet(path): return pd.read_parquet(path) if os.path.exists(path) else pd.DataFrame()
def save_parquet(df,path): df.to_parquet(path,index=False)

# =========================
# Horario laboral
# =========================
def day_windows(dt: date):
    wd = dt.weekday()
    if wd <= 4:  # L-V
        return [(time(7,30), time(14,0)), (time(15,0), time(18,30))]
    if wd == 5:  # Sábado
        return [(time(7,30), time(13,30))]
    return []

def overlap_minutes(a_start,a_end,b_start,b_end):
    start, end = max(a_start,b_start), min(a_end,b_end)
    return max(0,(end-start).total_seconds()/60)

def working_minutes_between(start, end):
    if pd.isna(start) or pd.isna(end): return 0
    if end<start: start,end=end,start
    total=0; cur=start.date()
    while cur<=end.date():
        for w_from,w_to in day_windows(cur):
            ws, we = datetime.combine(cur,w_from), datetime.combine(cur,w_to)
            total+=overlap_minutes(start,end,ws,we)
        cur+=timedelta(days=1)
    return round(total,2)

# =========================
# Tarifas
# =========================
def load_rates_csv():
    if os.path.exists(RATES_CSV):
        df=pd.read_csv(RATES_CSV)
        return df
    return pd.DataFrame(columns=["DEPTO","precio_minuto","precio_pieza","precio_hora"])

def calc_pago_row(depto,produce,minutos_ef,minutos_std,rates):
    dep=depto.strip().upper()
    r=rates[rates["DEPTO"]==dep]
    if not r.empty:
        t_min=r["precio_minuto"].iloc[0]
        t_pza=r["precio_pieza"].iloc[0]
        t_hr=r["precio_hora"].iloc[0]
        if pd.notna(t_min): return (round(minutos_ef*t_min,2),"minuto",t_min)
        if pd.notna(t_pza): return (round(produce*t_pza,2),"pieza",t_pza)
        if pd.notna(t_hr): return (round((minutos_ef/60)*t_hr,2),"hora",t_hr)
    return (0,"sin_tarifa",0)

# =========================
# Catálogos
# =========================
def load_emp_catalog():
    return pd.read_csv(CAT_EMP) if os.path.exists(CAT_EMP) else pd.DataFrame(columns=["departamento","empleado"])
def emp_options_for(depto): 
    df=load_emp_catalog()
    return sorted(df[df["departamento"].str.upper()==depto]["empleado"].tolist())
def load_model_catalog():
    return pd.read_csv(CAT_MOD)["modelo"].tolist() if os.path.exists(CAT_MOD) else []

# =========================
# Login
# =========================
def load_users():
    return pd.DataFrame([
        {"user":"admin","role":"Admin","pin":"1234"},
        {"user":"supervisor","role":"Supervisor","pin":"1111"}
    ])

def login_box():
    st.header("Iniciar sesión")
    users=load_users()
    u=st.text_input("Usuario")
    p=st.text_input("PIN",type="password")
    if st.button("Entrar"):
        row=users[(users.user==u)&(users.pin==p)]
        if not row.empty:
            st.session_state.user=u; st.session_state.role=row.iloc[0].role; st.rerun()
        else: st.error("Usuario/PIN incorrectos")

if "user" not in st.session_state: st.session_state.user=None; st.session_state.role=None
if not st.session_state.user: login_box(); st.stop()

# =========================
# Tabs
# =========================
tabs=st.tabs(["📲 Captura","📈 Tablero","🛠️ Admin"])

# 📲 Captura
with tabs[0]:
    st.subheader("Captura móvil")
    rates=load_rates_csv()
    with st.form("form_cap",clear_on_submit=True):
        c1,c2=st.columns(2)
        with c1:
            depto=st.selectbox("Departamento*",options=DEPT_OPTIONS)
            emp_choice=st.selectbox("Empleado*",["— Selecciona —"]+emp_options_for(depto))
        with c2:
            modelo_choice=st.selectbox("Modelo*",["— Selecciona —"]+load_model_catalog())
            produce=st.number_input("Produce (piezas)*",min_value=1,step=1,value=1)
            minutos_std=st.number_input("Minutos Std (por pieza)*",min_value=0.0,step=0.5,value=0.0)
        if st.form_submit_button("➕ Agregar registro"):
            empleado=emp_choice if emp_choice!="— Selecciona —" else ""
            modelo=modelo_choice if modelo_choice!="— Selecciona —" else ""
            ahora=datetime.now()
            db=load_parquet(DB_FILE)
            row={"DEPTO":depto,"EMPLEADO":empleado,"MODELO":modelo,"Produce":produce,
                 "Inicio":ahora,"Fin":ahora,"Minutos_Proceso":0,"Minutos_Std":minutos_std,
                 "Semana":week_number(ahora),"Usuario":st.session_state.user,
                 "Pago":0,"Esquema_Pago":"","Tarifa_Base":0}
            db=pd.concat([db,pd.DataFrame([row])],ignore_index=True)
            save_parquet(db,DB_FILE)
            st.success("Registro guardado ✅")

# 📈 Tablero
with tabs[1]:
    st.subheader("Producción en vivo")
    db=load_parquet(DB_FILE)
    if db.empty: st.info("Sin registros")
    else: st.dataframe(db,use_container_width=True)

# 🛠️ Admin
with tabs[2]:
    st.subheader("Admin")
    st.info("Aquí puedes cargar catálogos y tarifas.")
