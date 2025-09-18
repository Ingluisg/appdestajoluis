# app.py — Destajo con Planeación PRIV (fix: ensure ESPERA/PLAN_CODE columns)
import os, json
from datetime import datetime, date, timedelta

import numpy as np
import pandas as pd
import streamlit as st

APP_TITLE = "Destajo · Planeación PRIV + Roles + Alertas"
st.set_page_config(page_title=APP_TITLE, page_icon="📅", layout="centered")

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
DB_FILE = os.path.join(DATA_DIR, "registros.parquet")

# ------------------ Utilidades ------------------
def now_iso():
    return datetime.now().isoformat(timespec="seconds")

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

def ensure_col(df, name, default_value):
    if df is None or df.empty:
        return df
    if name not in df.columns:
        df[name] = default_value
    return df

# ------------------ Login ------------------
def login_box():
    st.header("Iniciar sesión (demo)")
    u = st.text_input("Usuario")
    p = st.text_input("PIN", type="password")
    if st.button("Entrar", use_container_width=True):
        st.session_state.user = u
        st.session_state.role = "Admin"
        st.rerun()

if "user" not in st.session_state:
    st.session_state.user = None
    st.session_state.role = None

if not st.session_state.user:
    login_box(); st.stop()

role = st.session_state.role
st.sidebar.success(f"Sesión: {st.session_state.user} ({role})")
if st.sidebar.button("Cerrar sesión"):
    for k in ["user","role"]:
        st.session_state.pop(k, None)
    st.rerun()

# Demo tablero with safe ESPERA metric
st.title("Demo Tablero (fix KeyError ESPERA)")

base = load_parquet(DB_FILE)
base = ensure_col(base, "ESPERA", False)
base = ensure_col(base, "PLAN_CODE", None)

if not base.empty:
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Piezas", f"{pd.to_numeric(base.get('Produce'), errors='coerce').sum(skipna=True):,.0f}")
    k2.metric("Minutos proceso", f"{pd.to_numeric(base.get('Minutos_Proceso'), errors='coerce').sum(skipna=True):,.0f}")
    k3.metric("Registros", f"{len(base):,}")
    k4.metric("En espera", f"{int(base['ESPERA'].fillna(False).sum())}")
else:
    st.info("Sin registros aún.")
