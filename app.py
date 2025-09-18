
import streamlit as st
import pandas as pd
import datetime as dt
import base64
from pathlib import Path

st.set_page_config(page_title="Devané • Destajos (Original)", layout="wide")

# --- Paths ---
BASE = Path(".")
DATA = BASE / "data"
PDF_DIR = BASE / "pdfs"
for p in [DATA, PDF_DIR]:
    p.mkdir(exist_ok=True)

# --- Files ---
CAPTURA_FILE  = DATA / "capturas.csv"         # capturas de operación
TARIFAS_FILE  = DATA / "tarifas.csv"          # normalizado desde Excel
CAT_MODELOS   = DATA / "cat_modelos.csv"
CAT_EMPLEADOS = DATA / "cat_empleados.csv"
CAT_LINEAS    = DATA / "cat_lineas.csv"

# --- Utils ---
def _ensure_cols(df, cols):
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return df[cols]

def _load_csv(path: Path, cols: list):
    if path.exists():
        try:
            df = pd.read_csv(path)
        except Exception:
            df = pd.DataFrame(columns=cols)
        return _ensure_cols(df, cols)
    return pd.DataFrame(columns=cols)

def _save_csv(df: pd.DataFrame, path: Path):
    df.to_csv(path, index=False)

def init_files():
    _save_csv(_load_csv(CAPTURA_FILE,  ["fecha","semana","linea","empleado","modelo","operacion","configuracion","cantidad","min_por_pieza","min_total","pago_estimado","creado_por","creado_en"]), CAPTURA_FILE)
    _save_csv(_load_csv(TARIFAS_FILE,  ["modelo","operacion","tarifa_min"]), TARIFAS_FILE)
    _save_csv(_load_csv(CAT_MODELOS,   ["modelo","descripcion","familia"]), CAT_MODELOS)
    _save_csv(_load_csv(CAT_EMPLEADOS, ["empleado","departamento","puesto","activo"]), CAT_EMPLEADOS)
    _save_csv(_load_csv(CAT_LINEAS,    ["linea","area","activa"]), CAT_LINEAS)

init_files()

def get_week(date: dt.date) -> int:
    return int(date.isocalendar()[1])

# --- PDF helpers ---
def list_pdfs():
    return sorted([p for p in PDF_DIR.glob("*.pdf")], key=lambda x: x.name)

def show_pdf(filepath: Path):
    b = filepath.read_bytes()
    b64 = base64.b64encode(b).decode("utf-8")
    pdf_display = f'<iframe src="data:application/pdf;base64,{b64}" width="100%" height="700" type="application/pdf"></iframe>'
    st.markdown(pdf_display, unsafe_allow_html=True)

# --- PAGES ---
def page_captura(usuario):
    st.header("📥 Captura de Tiempos / Destajos")
    cat_emps = _load_csv(CAT_EMPLEADOS, ["empleado","departamento","puesto","activo"])
    cat_lines = _load_csv(CAT_LINEAS, ["linea","area","activa"])
    cat_mods  = _load_csv(CAT_MODELOS, ["modelo","descripcion","familia"])

    with st.form("frm_cap"):
        c1,c2,c3 = st.columns(3)
        fecha = c1.date_input("Fecha", value=dt.date.today())
        semana = c2.number_input("Semana", step=1, value=get_week(fecha))
        linea = c3.selectbox("Línea", cat_lines["linea"].tolist() if not cat_lines.empty else [])
        c4,c5,c6 = st.columns(3)
        empleado = c4.selectbox("Empleado", cat_emps.loc[cat_emps["activo"]==True, "empleado"].tolist() if not cat_emps.empty else [])
        modelo = c5.selectbox("Modelo", cat_mods["modelo"].tolist() if not cat_mods.empty else [])
        operacion = c6.text_input("Operación", placeholder="Ej. Tapizado, Costura, Corte")
        configuracion = st.text_input("Configuración", placeholder="Ej. 3-2-1 / L / Par")
        c7,c8,c9 = st.columns(3)
        cantidad = c7.number_input("Cantidad", min_value=1, step=1, value=1)
        min_por_pieza = c8.number_input("Minutos por pieza", min_value=0.0, step=0.1, value=1.0)
        ok = st.form_submit_button("Guardar captura")
    if ok:
        min_total = float(min_por_pieza) * int(cantidad)
        # intentar tarifar
        tarifas = _load_csv(TARIFAS_FILE, ["modelo","operacion","tarifa_min"])
        tarifa = None
        if not tarifas.empty:
            row = tarifas[(tarifas["modelo"]==modelo) & (tarifas["operacion"]==operacion)]
            if not row.empty:
                tarifa = float(pd.to_numeric(row["tarifa_min"], errors="coerce").fillna(0).iloc[0])
        pago_est = min_total * tarifa if tarifa is not None else None

        cap = _load_csv(CAPTURA_FILE, ["fecha","semana","linea","empleado","modelo","operacion","configuracion","cantidad","min_por_pieza","min_total","pago_estimado","creado_por","creado_en"])
        row = pd.DataFrame([{
            "fecha": str(fecha),
            "semana": int(semana),
            "linea": linea,
            "empleado": empleado,
            "modelo": modelo,
            "operacion": operacion.strip(),
            "configuracion": configuracion.strip(),
            "cantidad": int(cantidad),
            "min_por_pieza": float(min_por_pieza),
            "min_total": float(min_total),
            "pago_estimado": float(pago_est) if pago_est is not None else None,
            "creado_por": usuario,
            "creado_en": dt.datetime.now().isoformat(timespec="seconds")
        }])
        cap = pd.concat([cap, row], ignore_index=True)
        _save_csv(cap, CAPTURA_FILE)
        st.success("✅ Captura guardada.")

    st.subheader("Últimas capturas")
    st.dataframe(_load_csv(CAPTURA_FILE, ["fecha","semana","linea","empleado","modelo","operacion","configuracion","cantidad","min_por_pieza","min_total","pago_estimado","creado_por","creado_en"]).tail(100), use_container_width=True)

def page_catalogos():
    st.header("🗂️ Catálogos")
    tab1, tab2, tab3 = st.tabs(["Modelos","Empleados","Líneas"])

    with tab1:
        df = _load_csv(CAT_MODELOS, ["modelo","descripcion","familia"])
        st.dataframe(df, use_container_width=True)
        with st.form("frm_mod"):
            c1,c2,c3 = st.columns(3)
            m = c1.text_input("Modelo")
            d = c2.text_input("Descripción")
            f = c3.text_input("Familia")
            if st.form_submit_button("Agregar modelo"):
                if m:
                    if m in df["modelo"].astype(str).tolist():
                        st.warning("Ese modelo ya existe.")
                    else:
                        df = pd.concat([df, pd.DataFrame([{"modelo": m, "descripcion": d, "familia": f}])], ignore_index=True)
                        _save_csv(df, CAT_MODELOS)
                        st.success("Modelo agregado.")

    with tab2:
        df = _load_csv(CAT_EMPLEADOS, ["empleado","departamento","puesto","activo"])
        st.dataframe(df, use_container_width=True)
        with st.form("frm_emp"):
            c1,c2,c3,c4 = st.columns(4)
            e = c1.text_input("Empleado")
            dep = c2.text_input("Departamento")
            pst = c3.text_input("Puesto")
            act = c4.checkbox("Activo", value=True)
            if st.form_submit_button("Agregar empleado"):
                if e:
                    df = pd.concat([df, pd.DataFrame([{"empleado": e, "departamento": dep, "puesto": pst, "activo": act}])], ignore_index=True)
                    _save_csv(df, CAT_EMPLEADOS)
                    st.success("Empleado agregado.")

    with tab3:
        df = _load_csv(CAT_LINEAS, ["linea","area","activa"])
        st.dataframe(df, use_container_width=True)
        with st.form("frm_lin"):
            c1,c2,c3 = st.columns(3)
            l = c1.text_input("Línea")
            ar = c2.text_input("Área")
            ac = c3.checkbox("Activa", value=True)
            if st.form_submit_button("Agregar línea"):
                if l:
                    df = pd.concat([df, pd.DataFrame([{"linea": l, "area": ar, "activa": ac}])], ignore_index=True)
                    _save_csv(df, CAT_LINEAS)
                    st.success("Línea agregada.")

def page_tarifas():
    st.header("💵 Tarifas (por minuto) desde Excel")
    st.info("Carga un Excel con columnas: **modelo, operacion, tarifa_min**. Se normaliza en `tarifas.csv`.")
    up = st.file_uploader("Subir Excel de tarifas", type=["xlsx","xls"])
    if up is not None:
        try:
            xls = pd.read_excel(up)
            cols = ["modelo","operacion","tarifa_min"]
            miss = [c for c in cols if c not in xls.columns]
            if miss:
                st.error(f"Faltan columnas: {', '.join(miss)}")
            else:
                xls = xls[cols]
                xls["tarifa_min"] = pd.to_numeric(xls["tarifa_min"], errors="coerce")
                _save_csv(xls, TARIFAS_FILE)
                st.success("✅ Tarifas guardadas en CSV.")
        except Exception as e:
            st.error(f"Error leyendo Excel: {e}")
    st.subheader("Tarifas actuales")
    st.dataframe(_load_csv(TARIFAS_FILE, ["modelo","operacion","tarifa_min"]), use_container_width=True)

def page_pdf():
    st.header("📄 Carga y visualización de PDFs")
    up = st.file_uploader("Subir PDF", type=["pdf"])
    if up is not None:
        dest = PDF_DIR / up.name
        with open(dest, "wb") as f:
            f.write(up.read())
        st.success(f"PDF guardado: {dest.name}")

    pdfs = list_pdfs()
    if not pdfs:
        st.info("No hay PDFs cargados aún.")
        return
    sel = st.selectbox("Selecciona PDF", [p.name for p in pdfs])
    if sel:
        show_pdf(PDF_DIR / sel)

def page_tablero():
    st.header("📊 Tablero de Tiempos y Destajos")
    cap = _load_csv(CAPTURA_FILE, ["fecha","semana","linea","empleado","modelo","operacion","configuracion","cantidad","min_por_pieza","min_total","pago_estimado","creado_por","creado_en"])
    if cap.empty:
        st.info("Aún no hay capturas.")
        return

    # Totales
    cap["min_total"] = pd.to_numeric(cap["min_total"], errors="coerce").fillna(0.0)
    cap["pago_estimado"] = pd.to_numeric(cap["pago_estimado"], errors="coerce")
    c1,c2,c3 = st.columns(3)
    c1.metric("Registros", len(cap))
    c2.metric("Minutos totales", int(cap["min_total"].sum()))
    total_p = cap["pago_estimado"].dropna().sum()
    c3.metric("Pago estimado", f"${total_p:,.2f}")

    st.subheader("Por semana y línea")
    by_week_line = cap.groupby(["semana","linea"], as_index=False).agg(min_total=("min_total","sum"), pago=("pago_estimado","sum"))
    st.dataframe(by_week_line, use_container_width=True)

    st.subheader("Por empleado")
    by_emp = cap.groupby(["empleado"], as_index=False).agg(min_total=("min_total","sum"), pago=("pago_estimado","sum"))
    st.dataframe(by_emp, use_container_width=True)

    st.subheader("Detalle reciente")
    st.dataframe(cap.sort_values("creado_en", ascending=False).head(200), use_container_width=True)

def page_datos():
    st.header("💾 Datos y exportación")
    files = [
        ("capturas.csv", CAPTURA_FILE),
        ("tarifas.csv", TARIFAS_FILE),
        ("cat_modelos.csv", CAT_MODELOS),
        ("cat_empleados.csv", CAT_EMPLEADOS),
        ("cat_lineas.csv", CAT_LINEAS),
    ]
    st.subheader("Descargar CSVs")
    cols = st.columns(5)
    for i, (fname, fpath) in enumerate(files):
        with cols[i % 5]:
            if fpath.exists():
                st.download_button(f"Descargar {fname}", data=open(fpath,"rb").read(), file_name=fname)

    if st.button("Resetear datos (vaciar CSVs)"):
        init_files()
        st.success("Datos inicializados.")

# --- App ---
st.sidebar.title("Devané • Destajos")
rol = st.sidebar.selectbox("Rol", ["Administrador","Supervisor","Operador"], index=0)
usuario = st.sidebar.text_input("Usuario", value="Luis García")

if rol == "Administrador":
    menu = ["Captura","Catálogos","Tarifas","PDFs","Tablero","Datos"]
elif rol == "Supervisor":
    menu = ["Captura","PDFs","Tablero","Datos"]
else:
    menu = ["Captura","PDFs"]

page = st.sidebar.radio("Menú", menu, index=0)

if page == "Captura":
    page_captura(usuario)
elif page == "Catálogos":
    page_catalogos()
elif page == "Tarifas":
    page_tarifas()
elif page == "PDFs":
    page_pdf()
elif page == "Tablero":
    page_tablero()
elif page == "Datos":
    page_datos()

st.caption("Devané • Destajos v1.0 (Original) • Streamlit")
