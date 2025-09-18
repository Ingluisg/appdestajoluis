
import streamlit as st
import pandas as pd
import datetime as dt
import base64
from pathlib import Path

st.set_page_config(page_title="Devané • Ecosistema Producción", layout="wide")

# --- Paths ---
BASE = Path(".")
DATA = BASE / "data"
PDF_DIR = BASE / "pdfs"
for p in [DATA, PDF_DIR]:
    p.mkdir(exist_ok=True)

# --- Files ---
PLANNING_FILE = DATA / "planeacion.csv"
ASSIGN_FILE   = DATA / "asignaciones.csv"
OPERATORS_FILE= DATA / "operadores.csv"
ALERTS_FILE   = DATA / "alertas.csv"
CAT_MODELOS   = DATA / "cat_modelos.csv"
CAT_EMPLEADOS = DATA / "cat_empleados.csv"
CAT_LINEAS    = DATA / "cat_lineas.csv"
TARIFAS_FILE  = DATA / "tarifas.csv"          # normalizado desde Excel
CAPTURA_FILE  = DATA / "capturas.csv"         # capturas generales (operación)

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
    _save_csv(_load_csv(PLANNING_FILE, ["semana","modelo","corrida_codigo","cantidad_planeada","inicio","fin","creado_por","creado_en"]), PLANNING_FILE)
    _save_csv(_load_csv(ASSIGN_FILE,   ["operador","modelo","corrida_codigo","cantidad_asignada","asignado_por","asignado_en"]), ASSIGN_FILE)
    _save_csv(_load_csv(OPERATORS_FILE,["operador","activo","departamento"]), OPERATORS_FILE)
    _save_csv(_load_csv(ALERTS_FILE,   ["nivel","mensaje","detalles","creado_en","actor"]), ALERTS_FILE)
    _save_csv(_load_csv(CAT_MODELOS,   ["modelo","descripcion","familia"]), CAT_MODELOS)
    _save_csv(_load_csv(CAT_EMPLEADOS, ["empleado","departamento","puesto","activo"]), CAT_EMPLEADOS)
    _save_csv(_load_csv(CAT_LINEAS,    ["linea","area","activa"]), CAT_LINEAS)
    _save_csv(_load_csv(TARIFAS_FILE,  ["modelo","operacion","tarifa_min","unidad","vigencia_inicio","vigencia_fin"]), TARIFAS_FILE)
    _save_csv(_load_csv(CAPTURA_FILE,  ["fecha","hora_inicio","hora_fin","semana","linea","empleado","modelo","configuracion","cantidad","corrida_codigo","creado_por","creado_en"]), CAPTURA_FILE)

init_files()

# --- Business helpers ---
def get_week(date: dt.date) -> int:
    return int(date.isocalendar()[1])

def total_asignado_por_corrida(codigo: str) -> int:
    df = _load_csv(ASSIGN_FILE, ["operador","modelo","corrida_codigo","cantidad_asignada","asignado_por","asignado_en"])
    df["cantidad_asignada"] = pd.to_numeric(df["cantidad_asignada"], errors="coerce").fillna(0).astype(int)
    return int(df.loc[df["corrida_codigo"] == codigo, "cantidad_asignada"].sum())

def cantidad_planeada(codigo: str) -> int:
    df = _load_csv(PLANNING_FILE, ["semana","modelo","corrida_codigo","cantidad_planeada","inicio","fin","creado_por","creado_en"])
    df["cantidad_planeada"] = pd.to_numeric(df["cantidad_planeada"], errors="coerce").fillna(0).astype(int)
    row = df.loc[df["corrida_codigo"] == codigo]
    return 0 if row.empty else int(row["cantidad_planeada"].iloc[0])

def registrar_alerta(nivel, mensaje, detalles, actor):
    al = _load_csv(ALERTS_FILE, ["nivel","mensaje","detalles","creado_en","actor"])
    new = pd.DataFrame([{
        "nivel": nivel,
        "mensaje": mensaje,
        "detalles": str(detalles),
        "creado_en": dt.datetime.now().isoformat(timespec="seconds"),
        "actor": actor
    }])
    al = pd.concat([al, new], ignore_index=True)
    _save_csv(al, ALERTS_FILE)

# --- Roles ---
def roles_ui():
    st.sidebar.subheader("Usuario")
    rol = st.sidebar.selectbox("Rol", ["Administrador","Planeación","Supervisor","Operador"], index=0)
    usuario = st.sidebar.text_input("Nombre", value="Luis García")
    depto = st.sidebar.selectbox("Departamento", ["Tapiz","Costura","Corte","Carpintería","General"], index=0)
    return rol, usuario, depto

# --- PDF helpers ---
def list_pdfs():
    return sorted([p for p in PDF_DIR.glob("*.pdf")], key=lambda x: x.name)

def show_pdf(filepath: Path):
    b = filepath.read_bytes()
    b64 = base64.b64encode(b).decode("utf-8")
    pdf_display = f'<iframe src="data:application/pdf;base64,{b64}" width="100%" height="700" type="application/pdf"></iframe>'
    st.markdown(pdf_display, unsafe_allow_html=True)

# --- PAGES ---
def page_captura(usuario, depto):
    st.header("📥 Captura de Producción / Tiempos")
    cat_emps = _load_csv(CAT_EMPLEADOS, ["empleado","departamento","puesto","activo"])
    cat_lines = _load_csv(CAT_LINEAS, ["linea","area","activa"])
    cat_mods  = _load_csv(CAT_MODELOS, ["modelo","descripcion","familia"])

    with st.form("frm_cap"):
        c1,c2,c3 = st.columns(3)
        fecha = c1.date_input("Fecha", value=dt.date.today())
        h_ini = c2.time_input("Hora inicio", value=dt.time(8,0))
        h_fin = c3.time_input("Hora fin", value=dt.time(17,0))
        semana = st.number_input("Semana", step=1, value=get_week(fecha))
        linea = st.selectbox("Línea", cat_lines["linea"].tolist() if not cat_lines.empty else [])
        empleado = st.selectbox("Empleado", cat_emps.loc[cat_emps["activo"]==True, "empleado"].tolist() if not cat_emps.empty else [])
        modelo = st.selectbox("Modelo", cat_mods["modelo"].tolist() if not cat_mods.empty else [])
        config = st.text_input("Configuración", placeholder="Ej. 3-2-1")
        cantidad = st.number_input("Cantidad", min_value=1, step=1, value=1)
        corrida = st.text_input("Código de corrida (opcional, para ligar con planeación)")
        ok = st.form_submit_button("Guardar captura")
    if ok:
        cap = _load_csv(CAPTURA_FILE, ["fecha","hora_inicio","hora_fin","semana","linea","empleado","modelo","configuracion","cantidad","corrida_codigo","creado_por","creado_en"])
        row = pd.DataFrame([{
            "fecha": str(fecha),
            "hora_inicio": str(h_ini),
            "hora_fin": str(h_fin),
            "semana": int(semana),
            "linea": linea,
            "empleado": empleado,
            "modelo": modelo,
            "configuracion": config,
            "cantidad": int(cantidad),
            "corrida_codigo": corrida.strip(),
            "creado_por": usuario,
            "creado_en": dt.datetime.now().isoformat(timespec="seconds")
        }])
        cap = pd.concat([cap, row], ignore_index=True)
        _save_csv(cap, CAPTURA_FILE)
        st.success("✅ Captura guardada.")

    st.subheader("Últimas capturas")
    st.dataframe(_load_csv(CAPTURA_FILE, ["fecha","hora_inicio","hora_fin","semana","linea","empleado","modelo","configuracion","cantidad","corrida_codigo","creado_por","creado_en"]).tail(100))

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
    st.header("💵 Tarifas desde Excel (normalización)")
    st.info("Carga un Excel con columnas: **modelo, operacion, tarifa_min, unidad, vigencia_inicio, vigencia_fin**. Se normaliza a CSV.")
    up = st.file_uploader("Subir Excel de tarifas", type=["xlsx","xls"])
    if up is not None:
        try:
            xls = pd.read_excel(up)
            cols = ["modelo","operacion","tarifa_min","unidad","vigencia_inicio","vigencia_fin"]
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
    st.dataframe(_load_csv(TARIFAS_FILE, ["modelo","operacion","tarifa_min","unidad","vigencia_inicio","vigencia_fin"]))

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

def page_planeacion(usuario):
    st.header("🗓️ Planeación semanal")
    with st.form("frm_plan"):
        c1,c2,c3 = st.columns(3)
        f_ini = c1.date_input("Inicio", value=dt.date.today())
        f_fin = c2.date_input("Fin", value=dt.date.today())
        semana = c3.number_input("Semana", value=get_week(dt.date.today()), step=1)
        modelo = st.text_input("Modelo")
        corrida = st.text_input("Código único de corrida").strip()
        cantidad = st.number_input("Cantidad planeada", min_value=1, step=1, value=10)
        ok = st.form_submit_button("Guardar planeación")
    if ok:
        plan = _load_csv(PLANNING_FILE, ["semana","modelo","corrida_codigo","cantidad_planeada","inicio","fin","creado_por","creado_en"])
        if corrida in plan["corrida_codigo"].astype(str).tolist():
            st.error("❌ Código de corrida duplicado.")
        elif not modelo or not corrida:
            st.warning("Completa Modelo y Código de corrida.")
        else:
            row = pd.DataFrame([{
                "semana": int(semana),
                "modelo": modelo.strip(),
                "corrida_codigo": corrida,
                "cantidad_planeada": int(cantidad),
                "inicio": str(f_ini),
                "fin": str(f_fin),
                "creado_por": usuario,
                "creado_en": dt.datetime.now().isoformat(timespec="seconds")
            }])
            plan = pd.concat([plan, row], ignore_index=True)
            _save_csv(plan, PLANNING_FILE)
            st.success("✅ Planeación guardada.")

    st.subheader("Planeaciones")
    st.dataframe(_load_csv(PLANNING_FILE, ["semana","modelo","corrida_codigo","cantidad_planeada","inicio","fin","creado_por","creado_en"]))

def page_asignaciones(usuario, rol):
    st.header("👷 Asignaciones")
    plan = _load_csv(PLANNING_FILE, ["semana","modelo","corrida_codigo","cantidad_planeada","inicio","fin","creado_por","creado_en"])
    if plan.empty:
        st.warning("No hay planeaciones.")
        return
    ops = _load_csv(OPERATORS_FILE, ["operador","activo","departamento"])
    with st.expander("📋 Operadores"):
        st.dataframe(ops)
        with st.form("frm_op"):
            c1,c2 = st.columns(2)
            name = c1.text_input("Nombre de operador")
            dep = c2.text_input("Departamento")
            if st.form_submit_button("Agregar operador"):
                if name:
                    if not (name in ops["operador"].astype(str).tolist()):
                        ops = pd.concat([ops, pd.DataFrame([{"operador": name, "activo": True, "departamento": dep}] )], ignore_index=True)
                        _save_csv(ops, OPERATORS_FILE)
                        st.success("Operador agregado.")
                    else:
                        st.info("El operador ya existe.")

    st.subheader("Nueva asignación")
    c1,c2 = st.columns(2)
    corrida = c1.selectbox("Corrida", plan["corrida_codigo"].tolist())
    modelo = plan.loc[plan["corrida_codigo"]==corrida, "modelo"].iloc[0]
    c2.write(f"**Modelo:** {modelo}")
    op_list = ops["operador"].tolist() if not ops.empty else []
    op = c1.selectbox("Operador", op_list)
    cant = c2.number_input("Cantidad a asignar", min_value=1, step=1, value=1)

    if st.button("Asignar"):
        if not op:
            st.warning("Selecciona un operador.")
        else:
            planeado = cantidad_planeada(corrida)
            ya_asig = total_asignado_por_corrida(corrida)
            restante = planeado - ya_asig
            if cant > restante:
                st.error(f"No se puede asignar {cant}. Restante: {restante}.")
                registrar_alerta("ALTA","Intento de sobre-asignación", {"corrida": corrida, "solicitado": int(cant), "restante": int(restante)}, actor=rol)
            else:
                asg = _load_csv(ASSIGN_FILE, ["operador","modelo","corrida_codigo","cantidad_asignada","asignado_por","asignado_en"])
                row = pd.DataFrame([{
                    "operador": op,
                    "modelo": modelo,
                    "corrida_codigo": corrida,
                    "cantidad_asignada": int(cant),
                    "asignado_por": usuario,
                    "asignado_en": dt.datetime.now().isoformat(timespec="seconds")
                }])
                asg = pd.concat([asg, row], ignore_index=True)
                _save_csv(asg, ASSIGN_FILE)
                st.success("✅ Asignación registrada.")

    # Resumen
    asg = _load_csv(ASSIGN_FILE, ["operador","modelo","corrida_codigo","cantidad_asignada","asignado_por","asignado_en"])
    if not asg.empty:
        asg["cantidad_asignada"] = pd.to_numeric(asg["cantidad_asignada"], errors="coerce").fillna(0).astype(int)
    res = asg.groupby("corrida_codigo", as_index=False)["cantidad_asignada"].sum() if not asg.empty else pd.DataFrame(columns=["corrida_codigo","cantidad_asignada"])
    merged = plan.merge(res, on="corrida_codigo", how="left").rename(columns={"cantidad_asignada":"asignado"})
    merged["asignado"] = merged["asignado"].fillna(0).astype(int)
    merged["restante"] = merged["cantidad_planeada"].astype(int) - merged["asignado"].astype(int)
    st.subheader("Resumen por corrida")
    st.dataframe(merged[["semana","modelo","corrida_codigo","cantidad_planeada","asignado","restante"]])

    # Alertas auto
    faltantes = merged.loc[merged["restante"] > 0]
    if not faltantes.empty:
        registrar_alerta("MEDIA","Faltan asignaciones en corridas", {"corridas": faltantes["corrida_codigo"].tolist()}, actor="Sistema")
        st.warning("⚠️ Corridas con pendiente por asignar. Supervisor notificado.")

    if not ops.empty and not asg.empty:
        ult_sem = plan["semana"].max()
        corr_sem = plan.loc[plan["semana"]==ult_sem, "corrida_codigo"].tolist()
        asg_sem = asg[asg["corrida_codigo"].isin(corr_sem)]
        activos = ops.loc[ops["activo"]==True, "operador"].tolist()
        con_asig = asg_sem["operador"].unique().tolist()
        idle = [o for o in activos if o not in con_asig]
        if idle:
            registrar_alerta("BAJA","Operadores en tiempo de espera", {"operadores": idle, "semana": int(ult_sem)}, actor="Sistema")
            st.info(f"ℹ️ Operadores sin asignación (sem {int(ult_sem)}): {', '.join(idle)}")

def page_tableros():
    st.header("📊 Tablero General")
    plan = _load_csv(PLANNING_FILE, ["semana","modelo","corrida_codigo","cantidad_planeada","inicio","fin","creado_por","creado_en"])
    asg  = _load_csv(ASSIGN_FILE, ["operador","modelo","corrida_codigo","cantidad_asignada","asignado_por","asignado_en"])
    cap  = _load_csv(CAPTURA_FILE, ["fecha","hora_inicio","hora_fin","semana","linea","empleado","modelo","configuracion","cantidad","corrida_codigo","creado_por","creado_en"])

    # Avance por corrida
    res = asg.groupby("corrida_codigo", as_index=False)["cantidad_asignada"].sum() if not asg.empty else pd.DataFrame(columns=["corrida_codigo","cantidad_asignada"])
    merged = plan.merge(res, on="corrida_codigo", how="left").rename(columns={"cantidad_asignada":"asignado"})
    merged["asignado"] = merged["asignado"].fillna(0).astype(int)
    merged["avance_%"] = (merged["asignado"] / merged["cantidad_planeada"].replace(0,1) * 100).round(1)

    c1,c2 = st.columns(2)
    with c1:
        st.subheader("Avance por corrida")
        st.dataframe(merged[["semana","modelo","corrida_codigo","cantidad_planeada","asignado","avance_%"]])
    with c2:
        st.subheader("Productividad por línea (capturas)")
        if cap.empty:
            st.info("Sin capturas.")
        else:
            cap["cantidad"] = pd.to_numeric(cap["cantidad"], errors="coerce").fillna(0).astype(int)
            by_line = cap.groupby(["semana","linea"], as_index=False)["cantidad"].sum()
            st.dataframe(by_line)

def page_alertas(rol):
    st.header("🚨 Centro de Alertas")
    al = _load_csv(ALERTS_FILE, ["nivel","mensaje","detalles","creado_en","actor"])
    if al.empty:
        st.success("Sin alertas por ahora.")
        return
    if rol != "Administrador":
        st.dataframe(al.loc[al["nivel"]!="ALTA"])
    else:
        st.dataframe(al)

def page_datos():
    st.header("💾 Datos y exportación")
    col = st.columns(5)
    files = [
        ("planeacion.csv", PLANNING_FILE),
        ("asignaciones.csv", ASSIGN_FILE),
        ("operadores.csv", OPERATORS_FILE),
        ("alertas.csv", ALERTS_FILE),
        ("cat_modelos.csv", CAT_MODELOS),
        ("cat_empleados.csv", CAT_EMPLEADOS),
        ("cat_lineas.csv", CAT_LINEAS),
        ("tarifas.csv", TARIFAS_FILE),
        ("capturas.csv", CAPTURA_FILE),
    ]
    for fname, fpath in files:
        if fpath.exists():
            st.download_button(f"Descargar {fname}", data=open(fpath,"rb").read(), file_name=fname)
    if st.button("Resetear datos (vaciar CSVs)"):
        init_files()
        st.success("Datos inicializados.")

# --- App ---
rol, usuario, depto = roles_ui()

# Menú condicionado por rol
if rol == "Administrador":
    menu = ["Captura","Catálogos","Tarifas","PDFs","Planeación","Asignaciones","Tableros","Alertas","Datos"]
elif rol == "Planeación":
    menu = ["Planeación","Asignaciones","Tableros","Alertas","Datos"]
elif rol == "Supervisor":
    menu = ["Asignaciones","Tableros","Alertas","Datos"]
else: # Operador
    menu = ["Captura","PDFs","Datos"]

page = st.sidebar.radio("Menú", menu, index=0)

if page == "Captura":
    page_captura(usuario, depto)
elif page == "Catálogos":
    page_catalogos()
elif page == "Tarifas":
    page_tarifas()
elif page == "PDFs":
    page_pdf()
elif page == "Planeación":
    page_planeacion(usuario)
elif page == "Asignaciones":
    page_asignaciones(usuario, rol)
elif page == "Tableros":
    page_tableros()
elif page == "Alertas":
    page_alertas(rol)
elif page == "Datos":
    page_datos()

st.caption("Devané • Ecosistema v1.1 • Streamlit")
