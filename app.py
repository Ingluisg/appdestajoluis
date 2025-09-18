# app.py
import os
import io
import math
from datetime import datetime, date, time, timedelta
from typing import Dict, List, Optional

import pandas as pd
import numpy as np
import streamlit as st

APP_TITLE = "Destajo Móvil · Tiempos"
st.set_page_config(page_title=APP_TITLE, page_icon="⏱️", layout="centered", initial_sidebar_state="expanded")

# ----------------------------
# Helpers
# ----------------------------
def parse_datetime(d, t):
    """Build a Python datetime from separate date/time or passthrough if already datetime-like."""
    if pd.isna(d) and pd.isna(t):
        return None
    if isinstance(d, (pd.Timestamp, datetime)):
        if isinstance(t, (pd.Timestamp, datetime, time)):
            # combine date from d and time from t
            if isinstance(t, (pd.Timestamp, datetime)):
                tt = t.time()
            else:
                tt = t
            return datetime(d.year, d.month, d.day, tt.hour, tt.minute, tt.second)
        # if d already has time, just return
        return d.to_pydatetime() if isinstance(d, pd.Timestamp) else d
    # if strings, try to parse
    try:
        if isinstance(d, str) and isinstance(t, str):
            return datetime.fromisoformat(f"{d} {t}")
        if isinstance(d, str) and isinstance(t, time):
            return datetime.combine(pd.to_datetime(d).date(), t)
        if isinstance(d, date) and isinstance(t, time):
            return datetime.combine(d, t)
    except Exception:
        return None
    return None

def week_number(dt: datetime) -> int:
    if not dt:
        return np.nan
    # ISO week number (Mon=1)
    return int(dt.isocalendar()[1])

def minutes_between(start: Optional[datetime], end: Optional[datetime]) -> float:
    if not start or not end:
        return np.nan
    return (end - start).total_seconds() / 60.0

def sanitize_col(col: str) -> str:
    return col.strip().lower().replace("á","a").replace("é","e").replace("í","i").replace("ó","o").replace("ú","u")

# ----------------------------
# Session & Storage
# ----------------------------
if "records" not in st.session_state:
    st.session_state.records = pd.DataFrame()

if "roles" not in st.session_state:
    st.session_state.roles = {"Nominas": True, "RRHH": True, "Productividad": True, "Supervisor": True}

DATA_PATH = "data_registros.parquet"

def load_saved():
    if os.path.exists(DATA_PATH):
        try:
            return pd.read_parquet(DATA_PATH)
        except Exception:
            try:
                return pd.read_csv(DATA_PATH.replace(".parquet", ".csv"))
            except Exception:
                return pd.DataFrame()
    return pd.DataFrame()

def save_data(df: pd.DataFrame):
    if df is None or df.empty:
        return
    df.to_parquet(DATA_PATH, index=False)

# ----------------------------
# Sidebar: Upload Excel and Params
# ----------------------------
st.sidebar.header("📄 Fuente: Excel de Tiempos")
file = st.sidebar.file_uploader("Sube tu Excel (.xlsx) con la **primera hoja: Tiempos**", type=["xlsx"], accept_multiple_files=False)

rate_min = st.sidebar.number_input("Tarifa por minuto (si aplica)", min_value=0.0, value=1.67, step=0.01, help="Se usará para el cálculo de pago si no viene en el Excel.")
jornada_min = st.sidebar.number_input("Minutos de jornada (opcional)", min_value=0, value=540, step=30, help="Ejemplo: 10 horas - 60 min comida = 540")

st.sidebar.markdown("---")
st.sidebar.caption("Consejo: si tu Excel ya trae columnas con tiempos estándar o pago por pieza, el sistema las detecta y las respeta.")

# ----------------------------
# Load Excel
# ----------------------------
uploaded_df = None
if file is not None:
    try:
        # Read first sheet or "Tiempos"
        xl = pd.ExcelFile(file)
        sheet_name = "Tiempos" if "Tiempos" in xl.sheet_names else xl.sheet_names[0]
        uploaded_df = xl.parse(sheet_name)
        # Keep a copy raw
        raw_cols = uploaded_df.columns.tolist()
    except Exception as e:
        st.sidebar.error(f"Error leyendo Excel: {e}")

# ----------------------------
# Column Mapping Wizard
# ----------------------------
st.title("⏱️ Destajo Móvil · Tiempos")

st.markdown("""
Este módulo replica el cálculo de tiempos **exclusivamente con base en tu Excel**.
- Si tu hoja ya trae **tiempos estándar** y/o **pago por pieza**, se respetan.
- Si no, el sistema calcula el **tiempo real** entre inicio y fin, y el **pago** con la tarifa por minuto.
""")

expected = {
    "operador": ["operador", "trabajador", "empleado"],
    "modelo": ["modelo", "producto", "referencia"],
    "config": ["config", "configuracion", "variante"],
    "cantidad": ["cantidad", "piezas", "qty", "unidades"],
    "linea": ["linea", "línea"],
    "depto": ["depto", "departamento", "area"],
    "fecha_inicio": ["fecha inicio", "fecha_inicio", "finicio", "fecha de inicio"],
    "hora_inicio": ["hora inicio", "hora_inicio", "hinicio", "hora de inicio"],
    "fecha_fin": ["fecha fin", "fecha_fin", "ffin", "fecha de fin"],
    "hora_fin": ["hora fin", "hora_fin", "hfin", "hora de fin"],
    "tiempo_std_min": ["tiempo std min", "tiempo estandar min", "tiempo_std", "minutos estandar"],
    "pago_pieza": ["pago pieza", "pago por pieza", "tarifa pieza"],
    "tarifa_min": ["tarifa min", "tarifa por minuto", "rate_minuto"],
}

def auto_guess_mapping(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    mapping = {k: None for k in expected.keys()}
    cols = [sanitize_col(c) for c in df.columns]
    for k, aliases in expected.items():
        for i, c in enumerate(cols):
            if c in aliases:
                mapping[k] = df.columns[i]
                break
    return mapping

mapping = {}
if uploaded_df is not None and not uploaded_df.empty:
    mapping = auto_guess_mapping(uploaded_df)
    with st.expander("🧭 Mapeo de columnas (ajústalo si es necesario):", expanded=False):
        for key in expected.keys():
            mapping[key] = st.selectbox(
                f"{key} →",
                options=["— (no aplica) —"] + uploaded_df.columns.tolist(),
                index=(uploaded_df.columns.tolist().index(mapping[key]) + 1) if mapping.get(key) in uploaded_df.columns else 0,
                key=f"map_{key}"
            )
            if mapping[key] == "— (no aplica) —":
                mapping[key] = None

# ----------------------------
# Build normalized dataset
# ----------------------------
def build_dataset(df: pd.DataFrame, mapping: Dict[str, Optional[str]]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = pd.DataFrame()
    def col(k): 
        m = mapping.get(k)
        return df[m] if m in df.columns else pd.Series([np.nan]*len(df))

    for k in ["operador","modelo","config","linea","depto"]:
        if mapping.get(k):
            out[k] = col(k)
        else:
            out[k] = np.nan

    # cantidad
    out["cantidad"] = pd.to_numeric(col("cantidad"), errors="coerce") if mapping.get("cantidad") else 1

    # datetimes
    dt_inicio = None
    dt_fin = None
    if mapping.get("fecha_inicio") or mapping.get("hora_inicio"):
        fi = pd.to_datetime(col("fecha_inicio"), errors="coerce") if mapping.get("fecha_inicio") else pd.NaT
        hi = pd.to_datetime(col("hora_inicio"), errors="coerce").dt.time if mapping.get("hora_inicio") else None
        dt_inicio = [parse_datetime(fi.iloc[i] if not pd.isna(fi).all() else None,
                                    hi.iloc[i] if hi is not None else None) for i in range(len(df))]
    if mapping.get("fecha_fin") or mapping.get("hora_fin"):
        ff = pd.to_datetime(col("fecha_fin"), errors="coerce") if mapping.get("fecha_fin") else pd.NaT
        hf = pd.to_datetime(col("hora_fin"), errors="coerce").dt.time if mapping.get("hora_fin") else None
        dt_fin = [parse_datetime(ff.iloc[i] if not pd.isna(ff).all() else None,
                                 hf.iloc[i] if hf is not None else None) for i in range(len(df))]

    out["inicio"] = pd.to_datetime(pd.Series(dt_inicio), errors="coerce") if dt_inicio is not None else pd.NaT
    out["fin"] = pd.to_datetime(pd.Series(dt_fin), errors="coerce") if dt_fin is not None else pd.NaT

    # week
    out["semana"] = out["inicio"].apply(lambda x: week_number(x) if pd.notna(x) else np.nan)

    # tiempos
    if mapping.get("tiempo_std_min"):
        out["tiempo_std_min"] = pd.to_numeric(col("tiempo_std_min"), errors="coerce")
    else:
        out["tiempo_std_min"] = np.nan

    out["minutos_reales"] = out.apply(lambda r: minutes_between(r["inicio"], r["fin"]), axis=1)

    # tarifa
    if mapping.get("tarifa_min"):
        out["tarifa_min"] = pd.to_numeric(col("tarifa_min"), errors="coerce").fillna({})
    else:
        out["tarifa_min"] = float(st.session_state.get("tarifa_min_sidebar", 0) or 0)
    # si tarifa_min no viene, usa rate_min del sidebar
    if out["tarifa_min"].isna().all() or (out["tarifa_min"] == 0).all():
        out["tarifa_min"] = rate_min

    # pago
    # prioridad: si viene pago_pieza en Excel, respétalo; sino, calcula
    if mapping.get("pago_pieza"):
        out["pago_pieza"] = pd.to_numeric(col("pago_pieza"), errors="coerce")
        out["pago_total"] = out["pago_pieza"] * out["cantidad"]
    else:
        # si existe tiempo_std_min -> pago por estándar * cantidad; sino por minutos reales
        cond_std = pd.notna(out["tiempo_std_min"])
        out["pago_total"] = np.where(cond_std,
                                     out["tiempo_std_min"] * out["tarifa_min"] * out["cantidad"],
                                     out["minutos_reales"] * out["tarifa_min"])

    # limpieza
    numeric_cols = ["cantidad","tiempo_std_min","minutos_reales","tarifa_min","pago_pieza","pago_total"]
    for c in numeric_cols:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")

    return out

norm_df = pd.DataFrame()
if uploaded_df is not None and not uploaded_df.empty:
    norm_df = build_dataset(uploaded_df, mapping)
    # merge with saved local
    saved = load_saved()
    if not saved.empty:
        # keep concatenated view (saved manual + uploaded excel calc side-by-side)
        pass

# ----------------------------
# Role & Auth (lightweight)
# ----------------------------
st.sidebar.header("👥 Roles (vista rápida)")
role = st.sidebar.selectbox("Rol de acceso", options=["Supervisor","Nominas","RRHH","Productividad"], index=0, help="Esto es un selector de vista, no seguridad real.")

# ----------------------------
# Tabs
# ----------------------------
tabs = st.tabs(["📲 Captura móvil", "📈 Producción en vivo", "📚 Histórico / Excel"])

with tabs[0]:
    st.subheader("Captura de registro de tiempo")
    with st.form("form_captura", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            operador = st.text_input("Operador*", placeholder="Nombre y/o ID")
            depto = st.selectbox("Departamento*", options=["Tapicería","Costura","Carpintería","Hilado","Colchón","Corte","Otro"])
            linea = st.selectbox("Línea*", options=["L1","L2","L3","L4"])
            modelo = st.text_input("Modelo*", placeholder="Ej. Sillón Alfa")
            config = st.text_input("Configuración", placeholder="Ej. Tela gris, brazo derecho")
            cantidad = st.number_input("Cantidad*", min_value=1, value=1, step=1)
        with col2:
            fecha_inicio = st.date_input("Fecha inicio*", value=date.today())
            hora_inicio = st.time_input("Hora inicio*", value=datetime.now().time().replace(second=0, microsecond=0))
            fecha_fin = st.date_input("Fecha fin*", value=date.today())
            hora_fin = st.time_input("Hora fin*", value=(datetime.now() + timedelta(minutes=30)).time().replace(second=0, microsecond=0))
            tarifa_local = st.number_input("Tarifa por minuto (opcional)", min_value=0.0, value=rate_min, step=0.01)

        submitted = st.form_submit_button("➕ Agregar registro")
        if submitted:
            # Build row
            dt_i = datetime.combine(fecha_inicio, hora_inicio) if fecha_inicio and hora_inicio else None
            dt_f = datetime.combine(fecha_fin, hora_fin) if fecha_fin and hora_fin else None
            row = {
                "operador": operador or np.nan,
                "depto": depto,
                "linea": linea,
                "modelo": modelo,
                "config": config,
                "cantidad": cantidad,
                "inicio": dt_i,
                "fin": dt_f,
                "semana": week_number(dt_i) if dt_i else np.nan,
                "minutos_reales": minutes_between(dt_i, dt_f),
                "tarifa_min": tarifa_local if tarifa_local else rate_min,
            }
            row["pago_total"] = (row["minutos_reales"] or 0) * (row["tarifa_min"] or 0)
            new_df = pd.DataFrame([row])
            current = load_saved()
            merged = pd.concat([current, new_df], ignore_index=True)
            save_data(merged)
            st.success("Registro agregado ✅")

    st.caption("Tip: esta pantalla está optimizada para celulares. Puedes añadir a la pantalla de inicio como PWA desde el navegador.")

with tabs[1]:
    st.subheader("Producción en vivo")
    df_live = load_saved()
    if uploaded_df is not None and not norm_df.empty:
        # visualizar calculado desde Excel junto a capturas manuales
        df_live = pd.concat([df_live, norm_df], ignore_index=True, sort=False)
    if df_live.empty:
        st.info("Aún no hay registros.")
    else:
        # KPIs rápidos
        total_min = pd.to_numeric(df_live["minutos_reales"], errors="coerce").sum(skipna=True)
        total_pzas = pd.to_numeric(df_live["cantidad"], errors="coerce").sum(skipna=True)
        total_pago = pd.to_numeric(df_live["pago_total"], errors="coerce").sum(skipna=True)

        k1, k2, k3 = st.columns(3)
        k1.metric("Minutos (reales)", f"{total_min:,.0f}")
        k2.metric("Piezas", f"{total_pzas:,.0f}")
        k3.metric("Pago estimado", f"${total_pago:,.2f}")

        # filtros
        with st.expander("Filtros"):
            c1, c2, c3 = st.columns(3)
            with c1:
                depto_f = st.multiselect("Departamento", sorted(df_live["depto"].dropna().unique().tolist()))
            with c2:
                linea_f = st.multiselect("Línea", sorted(df_live["linea"].dropna().unique().tolist()))
            with c3:
                semana_f = st.multiselect("Semana", sorted([int(x) for x in df_live["semana"].dropna().unique().tolist()]))

        fdf = df_live.copy()
        if depto_f: fdf = fdf[fdf["depto"].isin(depto_f)]
        if linea_f: fdf = fdf[fdf["linea"].isin(linea_f)]
        if semana_f: fdf = fdf[fdf["semana"].isin(semana_f)]

        # tabla
        st.dataframe(
            fdf.sort_values(by=["inicio"], ascending=False),
            use_container_width=True,
            hide_index=True
        )

with tabs[2]:
    st.subheader("Histórico y exportación")
    base = load_saved()
    if uploaded_df is not None and not norm_df.empty:
        base = pd.concat([base, norm_df], ignore_index=True, sort=False)
    if base.empty:
        st.info("No hay datos para mostrar.")
    else:
        st.dataframe(base, use_container_width=True, hide_index=True)
        # export
        csv = base.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Descargar CSV", data=csv, file_name="destajo_tiempos.csv", mime="text/csv")

st.sidebar.markdown("---")
st.sidebar.caption("© 2025 Destajo Móvil – construido con Streamlit")
