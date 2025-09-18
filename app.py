
import streamlit as st
import pandas as pd
import datetime as dt
from pathlib import Path

st.set_page_config(page_title="Devané • App de Planeación y Asignación", layout="wide")

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

PLANNING_FILE = DATA_DIR / "planeacion.csv"
ASSIGN_FILE = DATA_DIR / "asignaciones.csv"
OPERATORS_FILE = DATA_DIR / "operadores.csv"
ALERTS_FILE = DATA_DIR / "alertas.csv"

def _load_csv(path: Path, cols: list):
    if path.exists():
        df = pd.read_csv(path)
        # Ensure required columns exist
        for c in cols:
            if c not in df.columns:
                df[c] = None
        return df[cols]
    else:
        return pd.DataFrame(columns=cols)

def _save_csv(df: pd.DataFrame, path: Path):
    df.to_csv(path, index=False)

def init_files():
    _save_csv(_load_csv(PLANNING_FILE, ["semana","modelo","corrida_codigo","cantidad_planeada","inicio","fin","creado_por","creado_en"]), PLANNING_FILE)
    _save_csv(_load_csv(ASSIGN_FILE, ["operador","modelo","corrida_codigo","cantidad_asignada","asignado_por","asignado_en"]), ASSIGN_FILE)
    _save_csv(_load_csv(OPERATORS_FILE, ["operador","activo"]), OPERATORS_FILE)
    _save_csv(_load_csv(ALERTS_FILE, ["nivel","mensaje","detalles","creado_en","actor"]), ALERTS_FILE)

init_files()

# --- Helpers de negocio ---
def get_week(d: dt.date) -> int:
    return int(d.isocalendar()[1])

def total_asignado_por_corrida(corrida_codigo: str) -> int:
    asig = _load_csv(ASSIGN_FILE, ["operador","modelo","corrida_codigo","cantidad_asignada","asignado_por","asignado_en"])
    asig["cantidad_asignada"] = pd.to_numeric(asig["cantidad_asignada"], errors="coerce").fillna(0).astype(int)
    return int(asig.loc[asig["corrida_codigo"] == corrida_codigo, "cantidad_asignada"].sum())

def cantidad_planeada(corrida_codigo: str) -> int:
    plan = _load_csv(PLANNING_FILE, ["semana","modelo","corrida_codigo","cantidad_planeada","inicio","fin","creado_por","creado_en"])
    plan["cantidad_planeada"] = pd.to_numeric(plan["cantidad_planeada"], errors="coerce").fillna(0).astype(int)
    row = plan.loc[plan["corrida_codigo"] == corrida_codigo]
    if row.empty:
        return 0
    return int(row["cantidad_planeada"].iloc[0])

def registrar_alerta(nivel: str, mensaje: str, detalles: dict, actor: str):
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

def roles_ui():
    st.sidebar.subheader("Usuario")
    rol = st.sidebar.selectbox("Rol", ["Planeación","Administrador","Supervisor","Operador"], index=0)
    usuario = st.sidebar.text_input("Nombre de usuario", value="Luis García")
    return rol, usuario

def page_planeacion(usuario: str):
    st.header("Planeación semanal (visible: Planeación y Administrador)")
    st.info("Registra planeación por **modelo** y **código único de corrida**. El sistema impide duplicados y valida asignaciones contra el tope planeado.")
    with st.form("frm_plan"):
        col1, col2, col3 = st.columns(3)
        dia = col1.date_input("Fecha de inicio", value=dt.date.today())
        fin = col2.date_input("Fecha de fin", value=dt.date.today())
        semana = col3.number_input("Semana", value=int(dt.date.today().isocalendar()[1]), step=1)
        modelo = st.text_input("Modelo", placeholder="Ej. SOFA-ALFA")
        corrida = st.text_input("Código único de corrida", placeholder="Ej. ALFA-2025-W38-R1").strip()
        cantidad = st.number_input("Cantidad planeada", min_value=1, step=1, value=10)
        submitted = st.form_submit_button("Guardar planeación")
    if submitted:
        plan = _load_csv(PLANNING_FILE, ["semana","modelo","corrida_codigo","cantidad_planeada","inicio","fin","creado_por","creado_en"])
        if corrida in plan["corrida_codigo"].astype(str).tolist():
            st.error("❌ Ya existe una corrida con ese **código único**. Cambia el código.")
        elif not modelo or not corrida:
            st.warning("Completa **Modelo** y **Código de corrida**.")
        else:
            nuevo = pd.DataFrame([{
                "semana": int(semana),
                "modelo": modelo.strip(),
                "corrida_codigo": corrida,
                "cantidad_planeada": int(cantidad),
                "inicio": str(dia),
                "fin": str(fin),
                "creado_por": usuario,
                "creado_en": dt.datetime.now().isoformat(timespec="seconds")
            }])
            plan = pd.concat([plan, nuevo], ignore_index=True)
            _save_csv(plan, PLANNING_FILE)
            st.success("✅ Planeación guardada.")
    st.subheader("Planeaciones actuales")
    st.dataframe(_load_csv(PLANNING_FILE, ["semana","modelo","corrida_codigo","cantidad_planeada","inicio","fin","creado_por","creado_en"]))

def page_asignaciones(usuario: str, rol: str):
    st.header("Asignación a operadores")
    plan = _load_csv(PLANNING_FILE, ["semana","modelo","corrida_codigo","cantidad_planeada","inicio","fin","creado_por","creado_en"])
    if plan.empty:
        st.warning("No hay planeaciones registradas todavía.")
        return
    operadores = _load_csv(OPERATORS_FILE, ["operador","activo"])
    with st.expander("📋 Operadores"):
        st.dataframe(operadores)
        with st.form("frm_op"):
            op_name = st.text_input("Agregar operador")
            if st.form_submit_button("Guardar operador"):
                if op_name:
                    if op_name in operadores["operador"].astype(str).tolist():
                        st.info("Ese operador ya existe.")
                    else:
                        row = pd.DataFrame([{"operador": op_name, "activo": True}])
                        operadores = pd.concat([operadores, row], ignore_index=True)
                        _save_csv(operadores, OPERATORS_FILE)
                        st.success("Operador agregado.")

    st.subheader("Nueva asignación")
    col1, col2 = st.columns(2)
    corrida_sel = col1.selectbox("Corrida (código único)", plan["corrida_codigo"].tolist())
    modelo_sel = plan.loc[plan["corrida_codigo"]==corrida_sel, "modelo"].iloc[0]
    col2.write(f"**Modelo:** {modelo_sel}")

    op_list = _load_csv(OPERATORS_FILE, ["operador","activo"])
    op = col1.selectbox("Operador", op_list["operador"].tolist() if not op_list.empty else [])
    cant = col2.number_input("Cantidad a asignar", min_value=1, step=1, value=1)

    if st.button("Asignar"):
        if not op:
            st.warning("Agrega al menos un operador.")
        else:
            planeado = cantidad_planeada(corrida_sel)
            ya_asignado = total_asignado_por_corrida(corrida_sel)
            restante = planeado - ya_asignado
            if cant > restante:
                st.error(f"❌ No se puede asignar {cant}. Restante permitido: {restante}.")
                registrar_alerta("ALTA","Intento de sobre-asignación",
                                 {"corrida": corrida_sel, "solicitado": int(cant), "restante": int(restante)},
                                 actor=rol)
            else:
                asg = _load_csv(ASSIGN_FILE, ["operador","modelo","corrida_codigo","cantidad_asignada","asignado_por","asignado_en"])
                nuevo = pd.DataFrame([{
                    "operador": op,
                    "modelo": modelo_sel,
                    "corrida_codigo": corrida_sel,
                    "cantidad_asignada": int(cant),
                    "asignado_por": usuario,
                    "asignado_en": dt.datetime.now().isoformat(timespec="seconds")
                }])
                asg = pd.concat([asg, nuevo], ignore_index=True)
                _save_csv(asg, ASSIGN_FILE)
                st.success("✅ Asignación registrada.")

    # Resumen por corrida
    st.subheader("Resumen por corrida")
    asg = _load_csv(ASSIGN_FILE, ["operador","modelo","corrida_codigo","cantidad_asignada","asignado_por","asignado_en"])
    if not asg.empty:
        asg["cantidad_asignada"] = pd.to_numeric(asg["cantidad_asignada"], errors="coerce").fillna(0).astype(int)
    res = asg.groupby("corrida_codigo", as_index=False)["cantidad_asignada"].sum() if not asg.empty else pd.DataFrame(columns=["corrida_codigo","cantidad_asignada"])
    merged = plan.merge(res, on="corrida_codigo", how="left").rename(columns={"cantidad_asignada":"asignado"})
    merged["asignado"] = merged["asignado"].fillna(0).astype(int)
    merged["restante"] = merged["cantidad_planeada"].astype(int) - merged["asignado"].astype(int)
    st.dataframe(merged[["semana","modelo","corrida_codigo","cantidad_planeada","asignado","restante"]])

    # Alertas automáticas
    # 1) Si falta por asignar -> alerta a Supervisor
    faltantes = merged.loc[merged["restante"] > 0]
    if not faltantes.empty:
        registrar_alerta("MEDIA","Faltan asignaciones en corridas", {"corridas": faltantes["corrida_codigo"].tolist()}, actor="Sistema")
        st.warning("⚠️ Hay corridas con **pendiente por asignar**. Ya se notificó al Supervisor.")

    # 2) Operadores sin trabajo (idle): operadores activos sin asignación en la última semana
    if not op_list.empty and not asg.empty:
        ult_semana = plan["semana"].max()
        # Un operador con 0 asignaciones en corridas de la última semana
        corridas_sem = plan.loc[plan["semana"]==ult_semana, "corrida_codigo"].tolist()
        asg_sem = asg[asg["corrida_codigo"].isin(corridas_sem)]
        activos = op_list.loc[op_list["activo"]==True, "operador"].tolist()
        con_asig = asg_sem["operador"].unique().tolist()
        idle = [o for o in activos if o not in con_asig]
        if idle:
            registrar_alerta("BAJA","Operadores en tiempo de espera", {"operadores": idle, "semana": int(ult_semana)}, actor="Sistema")
            st.info(f"ℹ️ Operadores sin asignación en semana {int(ult_semana)}: {', '.join(idle)}")

def page_tableros():
    st.header("Tablero")
    plan = _load_csv(PLANNING_FILE, ["semana","modelo","corrida_codigo","cantidad_planeada","inicio","fin","creado_por","creado_en"])
    asg = _load_csv(ASSIGN_FILE, ["operador","modelo","corrida_codigo","cantidad_asignada","asignado_por","asignado_en"])
    if plan.empty:
        st.info("Carga planeaciones para ver el tablero.")
        return
    res = asg.groupby(["corrida_codigo"], as_index=False)["cantidad_asignada"].sum() if not asg.empty else pd.DataFrame(columns=["corrida_codigo","cantidad_asignada"])
    merged = plan.merge(res, on="corrida_codigo", how="left").rename(columns={"cantidad_asignada":"asignado"})
    merged["asignado"] = merged["asignado"].fillna(0).astype(int)
    merged["avance_%"] = (merged["asignado"] / merged["cantidad_planeada"].replace(0,1) * 100).round(1)
    st.dataframe(merged[["semana","modelo","corrida_codigo","cantidad_planeada","asignado","avance_%"]])

def page_alertas(rol: str):
    st.header("Centro de alertas")
    al = _load_csv(ALERTS_FILE, ["nivel","mensaje","detalles","creado_en","actor"])
    if al.empty:
        st.success("Sin alertas por ahora.")
        return
    if rol != "Administrador":
        # Ocultar de otros roles las alertas ALTA con detalles
        mask = al["nivel"] != "ALTA"
        st.dataframe(al.loc[mask])
    else:
        st.dataframe(al)

def page_datos():
    st.header("Datos y exportación")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.download_button("Descargar planeación.csv", data=open(PLANNING_FILE,"rb").read(), file_name="planeacion.csv")
    with col2:
        st.download_button("Descargar asignaciones.csv", data=open(ASSIGN_FILE,"rb").read(), file_name="asignaciones.csv")
    with col3:
        st.download_button("Descargar operadores.csv", data=open(OPERATORS_FILE,"rb").read(), file_name="operadores.csv")
    with col4:
        st.download_button("Descargar alertas.csv", data=open(ALERTS_FILE,"rb").read(), file_name="alertas.csv")

    if st.button("Resetear datos (vaciar CSVs)"):
        init_files()
        st.success("Datos inicializados.")

# --- App ---
rol, usuario = roles_ui()

menu = ["Planeación","Asignaciones","Tablero","Alertas","Datos"]
# Visibilidad por rol
if rol == "Planeación":
    default = 0
elif rol == "Administrador":
    default = 2
elif rol == "Supervisor":
    default = 2
else:
    default = 2

page = st.sidebar.radio("Menú", menu, index=default)

if page == "Planeación":
    if rol in ["Planeación","Administrador"]:
        page_planeacion(usuario)
    else:
        st.error("Acceso restringido: solo Planeación y Administrador.")
elif page == "Asignaciones":
    page_asignaciones(usuario, rol)
elif page == "Tablero":
    page_tableros()
elif page == "Alertas":
    page_alertas(rol)
elif page == "Datos":
    page_datos()

st.caption("Devané • v1.0 • Streamlit")
