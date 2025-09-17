
import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import datetime

st.set_page_config(page_title="Destajo App — Núcleo (Móvil)", layout="wide")

EXCEL_PATH = "TIEMPOS_DESTAJO_CORE.xlsx"
BITACORA_PATH = "bitacora_cambios.csv"
VALID_SHEETS = ["Tiempos", "Tabla", "Calendario"]  # Solo estas 3 hojas

# Credenciales máster (en producción define st.secrets["MASTER_PASS"] en secrets)
MASTER_USER = "master"
MASTER_PASS = st.secrets.get("MASTER_PASS", "master1234")

# ----------------- Utilidades -----------------
@st.cache_data
def load_book(path):
    xls = pd.ExcelFile(path)
    data = {s: xls.parse(s) for s in xls.sheet_names if s in VALID_SHEETS}
    return data

def to_excel_bytes(dfs):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for name in VALID_SHEETS:
            if name in dfs:
                dfs[name].to_excel(writer, sheet_name=name, index=False)
    return output.getvalue()

def validate_same_columns(a: pd.DataFrame, b: pd.DataFrame) -> bool:
    return list(a.columns) == list(b.columns)

def append_bitacora(accion: str, hoja: str, detalle: str = ""):
    ts = datetime.now().isoformat(timespec="seconds")
    row = {"timestamp": ts, "usuario": MASTER_USER, "accion": accion, "hoja": hoja, "detalle": detalle}
    try:
        if os.path.exists(BITACORA_PATH):
            df = pd.read_csv(BITACORA_PATH)
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        else:
            df = pd.DataFrame([row])
        df.to_csv(BITACORA_PATH, index=False)
    except Exception as e:
        st.warning(f"No se pudo registrar en bitácora: {e}")

def detect_fecha_column(df: pd.DataFrame):
    # Intenta detectar una columna de fecha (datetime dtype o nombre contiene 'fecha')
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            return c
    for c in df.columns:
        if "fecha" in str(c).lower():
            # intentar parsear
            try:
                pd.to_datetime(df[c])
                return c
            except Exception:
                continue
    return None

def detect_modelo_column(df: pd.DataFrame):
    for c in df.columns:
        if "modelo" in str(c).lower():
            return c
    return None

# ----------------- UI -----------------
st.title("App de Destajo — Núcleo")
st.caption("Optimizada para móviles. Solo **Tiempos**, **Tabla** y **Calendario**. Sin añadir columnas nuevas.")

# Barra lateral: acceso y global
with st.sidebar:
    st.header("Acceso")
    modo = st.radio("Modo", ["Usuario", "Máster"], horizontal=True)
    is_master = st.session_state.get("is_master", False)
    if modo == "Máster":
        user = st.text_input("Usuario", value=MASTER_USER if is_master else "")
        pwd = st.text_input("Contraseña", type="password")
        if st.button("Entrar", use_container_width=True):
            if user == MASTER_USER and pwd == MASTER_PASS:
                st.session_state["is_master"] = True
                st.success("Acceso máster concedido.")
            else:
                st.session_state["is_master"] = False
                st.error("Credenciales inválidas.")
    else:
        st.session_state["is_master"] = False
    is_master = st.session_state.get("is_master", False)

    st.divider()
    st.subheader("Bitácora")
    if os.path.exists(BITACORA_PATH):
        try:
            bit = pd.read_csv(BITACORA_PATH)
            st.write(f"Entradas: {len(bit)}")
            st.download_button("Descargar bitácora (CSV)", bit.to_csv(index=False).encode("utf-8"),
                               file_name="bitacora_cambios.csv", mime="text/csv", use_container_width=True)
        except Exception as e:
            st.info(f"No se pudo leer la bitácora: {e}")
    else:
        st.caption("Aún no hay bitácora.")

data = load_book(EXCEL_PATH)
tabs = st.tabs(VALID_SHEETS)

for i, name in enumerate(VALID_SHEETS):
    with tabs[i]:
        st.subheader(name)
        df = data.get(name)
        if df is None:
            st.error(f"No se encontró la hoja '{name}' en el archivo.")
            continue

        # ---- Filtros específicos para 'Tiempos' ----
        if name == "Tiempos":
            fecha_col = detect_fecha_column(df)
            modelo_col = detect_modelo_column(df)

            with st.expander("Filtros (solo vista y exportación)"):
                filtered = df.copy()
                if fecha_col is not None:
                    # Intentar convertir a datetime (no modifica archivo, solo vista)
                    try:
                        filtered[fecha_col] = pd.to_datetime(filtered[fecha_col], errors="coerce")
                        min_d = pd.to_datetime(filtered[fecha_col].min())
                        max_d = pd.to_datetime(filtered[fecha_col].max())
                        if pd.notna(min_d) and pd.notna(max_d):
                            r = st.date_input("Rango de fechas",
                                              value=(min_d.date(), max_d.date()))
                            if isinstance(r, tuple) and len(r) == 2:
                                start, end = pd.to_datetime(r[0]), pd.to_datetime(r[1])
                                mask = (filtered[fecha_col] >= start) & (filtered[fecha_col] <= end + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))
                                filtered = filtered[mask]
                    except Exception as e:
                        st.caption(f"No se pudo aplicar filtro por fecha: {e}")

                if modelo_col is not None:
                    q = st.text_input("Buscar modelo (contiene)", "")
                    if q:
                        filtered = filtered[filtered[modelo_col].astype(str).str.contains(q, case=False, na=False)]

                # Vista filtrada + export
                st.markdown("**Vista filtrada (no altera el Excel):**")
                st.dataframe(filtered, use_container_width=True, height=380)
                # Export filtrado
                st.download_button(
                    "Descargar 'Tiempos' filtrado (CSV)",
                    filtered.to_csv(index=False).encode("utf-8"),
                    file_name="Tiempos_filtrado.csv",
                    mime="text/csv",
                    use_container_width=True
                )

        # ---- Vista general por hoja ----
        st.markdown("**Vista completa de la hoja:**")
        st.dataframe(df, use_container_width=True, height=300)

        # ---- Herramientas máster por hoja ----
        if is_master:
            st.markdown("—")
            st.markdown("**Herramientas Máster**")

            # Editor enriquecido
            try:
                edited = st.experimental_data_editor(df, num_rows="dynamic", use_container_width=True, key=f"edit_{name}")
                if st.button(f"Guardar cambios en {name}", key=f"save_{name}", use_container_width=True):
                    if not validate_same_columns(df, edited):
                        st.error("No se permite añadir/eliminar/reordenar columnas. Reestablece las columnas originales.")
                    else:
                        data[name] = edited
                        excel_bytes = to_excel_bytes(data)
                        with open(EXCEL_PATH, "wb") as f:
                            f.write(excel_bytes)
                        append_bitacora("editar_guardar", name, f"filas={len(edited)}")
                        st.success(f"Cambios guardados en '{name}'.")
            except Exception:
                st.info("Editor de cuadrícula no disponible en esta versión.")

            # Importador CSV
            st.markdown("**Importar CSV (reemplaza la hoja completa, mismas columnas y orden):**")
            up = st.file_uploader(f"Subir CSV para '{name}'", type=["csv"], key=f"uploader_{name}")
            if up is not None:
                try:
                    new_df = pd.read_csv(up)
                    if not validate_same_columns(df, new_df):
                        st.error("El CSV debe tener **exactamente** las mismas columnas y en el mismo orden.")
                    else:
                        if st.button(f"Confirmar importación a {name}", key=f"confirm_{name}", use_container_width=True):
                            data[name] = new_df
                            excel_bytes = to_excel_bytes(data)
                            with open(EXCEL_PATH, "wb") as f:
                                f.write(excel_bytes)
                            append_bitacora("importar_csv", name, f"filas={len(new_df)}")
                            st.success(f"CSV importado correctamente en '{name}'.")
                except Exception as e:
                    st.error(f"Error al leer CSV: {e}")

            # Descargas por hoja
            st.download_button(
                f"Descargar {name} (CSV)",
                df.to_csv(index=False).encode("utf-8"),
                file_name=f"{name}.csv",
                mime="text/csv",
                key=f"dl_{name}"
            )

# Sección de reportes globales
st.markdown("---")
col1, col2 = st.columns(2)
with col1:
    st.markdown("### Reportes Rápidos")
    for name in VALID_SHEETS:
        df = data.get(name)
        if df is not None:
            st.write(f"**{name}** — Registros: {len(df)}")
with col2:
    st.markdown("### Exportar Libro Completo")
    buf = to_excel_bytes(data)
    st.download_button(
        "Descargar Excel (3 hojas)",
        buf,
        file_name="TIEMPOS_DESTAJO_CORE_actualizado.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )

st.caption("🔐 Producción: usa `MASTER_PASS` en Secrets. 📝 La bitácora se guarda en `bitacora_cambios.csv`.")
