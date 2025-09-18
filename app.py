# app.py — Destajo + Catálogos por Depto + Cierre Automático + Visor/Buscador de PDFs (con miniaturas)
# © 2025

import os, json, base64, re, hashlib
from datetime import datetime, date
from typing import Optional, Dict, Any, List

import numpy as np
import pandas as pd
import streamlit as st

# =========================
# Config básica
# =========================
APP_TITLE = "Destajo · Roles + Auditoría + Plantillas"
st.set_page_config(page_title=APP_TITLE, page_icon="🧮", layout="centered")

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

DB_FILE     = os.path.join(DATA_DIR, "registros.parquet")
AUDIT_FILE  = os.path.join(DATA_DIR, "audit.parquet")
USERS_FILE  = "users.csv"

# Catálogos
CAT_EMP     = os.path.join(DATA_DIR, "cat_empleados.csv")  # columnas: departamento,empleado
CAT_MOD     = os.path.join(DATA_DIR, "cat_modelos.csv")    # columna: modelo

# Documentos (PDFs)
DOCS_DIR    = os.path.join(DATA_DIR, "docs")
DOCS_INDEX  = os.path.join(DATA_DIR, "docs_index.csv")     # id,departamento,titulo,tags,filename,relpath,uploaded_by,ts
THUMBS_DIR  = os.path.join(DOCS_DIR, "thumbs")
os.makedirs(THUMBS_DIR, exist_ok=True)

DEPT_OPTIONS = ["COSTURA","TAPIZ","CARPINTERIA","COJINERIA","CORTE","ARMADO","HILADO","COLCHONETA","OTRO"]

# =========================
# Utils
# =========================
def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")

def week_number(dt: Optional[datetime]):
    if pd.isna(dt) or dt is None:
        return np.nan
    return pd.Timestamp(dt).isocalendar().week

def load_parquet(path: str) -> pd.DataFrame:
    if os.path.exists(path):
        try:
            return pd.read_parquet(path)
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()

def save_parquet(df: pd.DataFrame, path: str):
    if df is None or df.empty:
        return
    df.to_parquet(path, index=False)

def sanitize_filename(name: str) -> str:
    base = re.sub(r"[^\w\-. ]+", "_", str(name))
    return re.sub(r"\s+", "_", base).strip("_")

def hash_relpath(relpath: str) -> str:
    return hashlib.sha1(relpath.encode("utf-8")).hexdigest()[:16]

# =========================
# Usuarios
# =========================
def load_users() -> pd.DataFrame:
    if os.path.exists(USERS_FILE):
        try:
            df = pd.read_csv(USERS_FILE, dtype=str)
            df.columns = [c.strip().lower() for c in df.columns]
            return df
        except Exception:
            pass
    # fallback
    return pd.DataFrame([
        {"user":"admin","role":"Admin","pin":"1234"},
        {"user":"supervisor","role":"Supervisor","pin":"1111"},
        {"user":"nominas","role":"Nominas","pin":"2222"},
        {"user":"rrhh","role":"RRHH","pin":"3333"},
        {"user":"productividad","role":"Productividad","pin":"4444"},
    ])

# =========================
# Catálogos (empleados por depto / modelos global)
# =========================
def load_emp_catalog() -> pd.DataFrame:
    if os.path.exists(CAT_EMP):
        try:
            df = pd.read_csv(CAT_EMP, dtype=str)
            for c in ["departamento","empleado"]:
                if c not in df.columns:
                    return pd.DataFrame(columns=["departamento","empleado"])
            df = df.dropna(subset=["empleado"])
            df["departamento"] = df["departamento"].str.strip().str.upper()
            df["empleado"] = df["empleado"].str.strip()
            return df.drop_duplicates(subset=["departamento","empleado"]).sort_values(["departamento","empleado"])
        except Exception:
            pass
    return pd.DataFrame(columns=["departamento","empleado"])

def save_emp_catalog(df: pd.DataFrame):
    os.makedirs(os.path.dirname(CAT_EMP), exist_ok=True)
    out = (df.dropna(subset=["empleado"])
             .assign(departamento=lambda d: d["departamento"].str.strip().str.upper(),
                     empleado=lambda d: d["empleado"].str.strip()))
    out = out[(out["departamento"]!="") & (out["empleado"]!="")]
    out.drop_duplicates(subset=["departamento","empleado"]).sort_values(["departamento","empleado"]).to_csv(CAT_EMP, index=False)

def emp_options_for(depto: str, db_hist: pd.DataFrame) -> List[str]:
    dep = str(depto).strip().upper()
    cat = load_emp_catalog()
    cat_list = cat.loc[cat["departamento"]==dep, "empleado"].dropna().astype(str).tolist()
    hist_list = []
    if not db_hist.empty and {"EMPLEADO","DEPTO"}.issubset(db_hist.columns):
        hist_list = db_hist.loc[db_hist["DEPTO"].astype(str).str.upper()==dep, "EMPLEADO"].dropna().astype(str).unique().tolist()
    return sorted(list(dict.fromkeys(cat_list + hist_list)))

def add_emp_to_catalog(depto: str, empleado: str):
    dep = str(depto).strip().upper()
    emp = str(empleado).strip()
    if not dep or not emp:
        return
    cat = load_emp_catalog()
    cat = pd.concat([cat, pd.DataFrame([{"departamento": dep, "empleado": emp}])], ignore_index=True)
    save_emp_catalog(cat)

def load_model_catalog() -> List[str]:
    if os.path.exists(CAT_MOD):
        try:
            df = pd.read_csv(CAT_MOD, dtype=str)
            if "modelo" in df.columns:
                items = [x.strip() for x in df["modelo"].dropna().astype(str).tolist() if x.strip()]
                return sorted(list(dict.fromkeys(items)))
        except Exception:
            pass
    return []

def save_model_catalog(items: List[str]):
    clean = sorted(list(dict.fromkeys([str(x).strip() for x in items if str(x).strip()])))
    pd.DataFrame({"modelo": clean}).to_csv(CAT_MOD, index=False)

# =========================
# Docs (PDF) + Miniaturas
# =========================
def load_docs_index() -> pd.DataFrame:
    if os.path.exists(DOCS_INDEX):
        try:
            df = pd.read_csv(DOCS_INDEX, dtype=str)
            need = ["id","departamento","titulo","tags","filename","relpath","uploaded_by","ts"]
            for c in need:
                if c not in df.columns:
                    return pd.DataFrame(columns=need)
            return df
        except Exception:
            pass
    return pd.DataFrame(columns=["id","departamento","titulo","tags","filename","relpath","uploaded_by","ts"])

def save_docs_index(df: pd.DataFrame):
    os.makedirs(DOCS_DIR, exist_ok=True)
    df.to_csv(DOCS_INDEX, index=False)

def thumb_path_for(relpath: str) -> str:
    # Usa un hash del relpath para nombre estable
    h = hash_relpath(relpath)
    base = os.path.splitext(os.path.basename(relpath))[0]
    return os.path.join(THUMBS_DIR, f"{base}_{h}.png")

def ensure_pdf_thumbnail(relpath: str, max_w: int = 360, dpi: int = 110) -> Optional[str]:
    """
    Genera (si falta) una miniatura PNG de la primera página del PDF.
    Devuelve ruta al PNG o None si falla.
    """
    png_path = thumb_path_for(relpath)
    abs_pdf = relpath if os.path.isabs(relpath) else os.path.join(".", relpath)
    try:
        if os.path.exists(png_path):
            return png_path
        # Render con PyMuPDF
        import fitz  # PyMuPDF
        doc = fitz.open(abs_pdf)
        if doc.page_count == 0:
            return None
        page = doc.load_page(0)
        # calcular escala por ancho objetivo
        pix = page.get_pixmap(dpi=dpi)
        if pix.width > max_w:
            scale = max_w / pix.width
            mat = fitz.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=mat, dpi=dpi)
        pix.save(png_path)
        doc.close()
        return png_path if os.path.exists(png_path) else None
    except Exception:
        # fall back: None
        return None

# visor PDF amigable en móvil
def show_pdf_file(path: str, height: int = 680):
    try:
        with open(path, "rb") as f:
            data = f.read()
        b64 = base64.b64encode(data).decode("utf-8")

        # 1) PDF.js via streamlit-pdf-viewer (mejor en móvil)
        try:
            from streamlit_pdf_viewer import pdf_viewer
            pdf_viewer(b64, width=0, height=height, scrolling=True)
        except Exception:
            # 2) Fallback: iframe data: (mejor en desktop)
            st.components.v1.html(
                f"""<iframe src="data:application/pdf;base64,{b64}" width="100%" height="{height}" style="border:none;"></iframe>""",
                height=height+10,
            )

        # 3) Enlaces alternativos
        colA, colB = st.columns(2)
        with colA:
            st.markdown(
                f"""<a href="data:application/pdf;base64,{b64}" target="_blank" rel="noopener"
                style="display:inline-block;padding:0.6rem 1rem;border:1px solid #777;border-radius:6px;text-decoration:none">
                🔎 Abrir en pestaña nueva</a>""",
                unsafe_allow_html=True,
            )
        with colB:
            st.download_button("⬇️ Descargar PDF", data=data, file_name=os.path.basename(path), mime="application/pdf", use_container_width=True)
    except Exception as e:
        st.error(f"No se pudo mostrar/servir el PDF: {e}")

# =========================
# Permisos
# =========================
ROLE_PERMS = {
    "Admin": {"editable": True, "columns_view": "all", "can_delete": True},
    "Supervisor": {"editable": True, "columns_view": "all", "can_delete": False},
    "Productividad": {"editable": False, "columns_view": "all", "can_delete": False},
    "Nominas": {"editable": False, "columns_view": "all", "can_delete": False},
    "RRHH": {"editable": False, "columns_view": "all", "can_delete": False},
}

# =========================
# Auditoría
# =========================
def log_audit(user: str, action: str, record_id: Optional[int], details: Dict[str, Any]):
    payload = json.dumps(details, ensure_ascii=False,
                         default=lambda o: o.isoformat() if hasattr(o, "isoformat") else str(o))
    aud = load_parquet(AUDIT_FILE)
    row = {"ts": now_iso(), "user": user, "action": action,
           "record_id": int(record_id) if record_id is not None else None, "details": payload}
    aud = pd.concat([aud, pd.DataFrame([row])], ignore_index=True)
    save_parquet(aud, AUDIT_FILE)

# =========================
# Login
# =========================
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
    st.session_state.user, st.session_state.role = None, None

if not st.session_state.user:
    login_box(); st.stop()

perms = ROLE_PERMS.get(st.session_state.role, ROLE_PERMS["Supervisor"])

st.sidebar.success(f"Sesión: {st.session_state.user} ({st.session_state.role})")
if st.sidebar.button("Cerrar sesión"):
    for k in ["user","role"]:
        st.session_state.pop(k, None)
    st.rerun()

# =========================
# Tabs
# =========================
tabs = st.tabs([
    "📲 Captura",
    "📈 Tablero",
    "📚 Plantillas & Diagramas",
    "✏️ Editar / Auditar",
    "🛠️ Admin",
])

# =========================
# 📲 Captura
# =========================
with tabs[0]:
    st.subheader("Captura móvil")
    if not perms["editable"]:
        st.info("Sin permisos para capturar.")
    else:
        db_prev = load_parquet(DB_FILE)

        with st.form("form_captura", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                depto = st.selectbox("Departamento*", options=DEPT_OPTIONS, index=0)
                empleados_opts = emp_options_for(depto, db_prev)
                emp_choice = st.selectbox("Empleado*", ["— Selecciona —"] + empleados_opts + ["Otro…"])
                empleado_manual = st.text_input("Empleado (nuevo)*", placeholder="Nombre/ID") if emp_choice=="Otro…" else ""
            with c2:
                modelos_hist = sorted(db_prev["MODELO"].dropna().astype(str).unique().tolist()) if "MODELO" in db_prev.columns else []
                modelos_cat = load_model_catalog()
                modelos_opts = sorted(list(dict.fromkeys(modelos_cat + modelos_hist)))
                modelo_choice = st.selectbox("Modelo*", ["— Selecciona —"] + modelos_opts + ["Otro…"])
                modelo_manual = st.text_input("Modelo (nuevo)*", placeholder="Ej. MARIE 2 GAIA") if modelo_choice=="Otro…" else ""
                produce = st.number_input("Produce (piezas)*", min_value=1, step=1, value=1)
                minutos_std = st.number_input("Minutos Std (por pieza)*", min_value=0.0, step=0.5, value=0.0)

            if st.form_submit_button("➕ Agregar registro", use_container_width=True):
                empleado = empleado_manual if emp_choice=="Otro…" else (emp_choice if emp_choice!="— Selecciona —" else "")
                modelo   = modelo_manual   if modelo_choice=="Otro…" else (modelo_choice if modelo_choice!="— Selecciona —" else "")
                if not empleado or not modelo:
                    st.error("Empleado y Modelo son obligatorios.")
                else:
                    # aprender en catálogos
                    if emp_choice=="Otro…":
                        add_emp_to_catalog(depto, empleado)
                    if modelo_choice=="Otro…":
                        save_model_catalog(list(set(load_model_catalog()+[modelo])))

                    ahora = datetime.now()
                    db = load_parquet(DB_FILE)

                    # Cerrar trabajo abierto del mismo empleado (Inicio==Fin)
                    if not db.empty and {"EMPLEADO","Inicio","Fin"}.issubset(db.columns):
                        try:
                            db["Inicio"] = pd.to_datetime(db["Inicio"], errors="coerce")
                            db["Fin"] = pd.to_datetime(db["Fin"], errors="coerce")
                        except Exception:
                            pass
                        abiertos = db[(db["EMPLEADO"].astype(str)==str(empleado)) &
                                      db["Inicio"].notna() & db["Fin"].notna() &
                                      (db["Inicio"]==db["Fin"])]
                        if not abiertos.empty:
                            idx_last = abiertos.index[-1]
                            ini_prev = pd.to_datetime(db.at[idx_last,"Inicio"])
                            db.at[idx_last,"Fin"] = ahora
                            db.at[idx_last,"Minutos_Proceso"] = (ahora - ini_prev).total_seconds()/60.0
                            db.at[idx_last,"Estimado"] = False
                            save_parquet(db, DB_FILE)
                            log_audit(st.session_state.user, "auto-close", int(idx_last), {"empleado": empleado, "cerrado": ahora})

                    # Nuevo registro "abierto"
                    row = {
                        "DEPTO": str(depto).strip().upper(),
                        "EMPLEADO": empleado,
                        "MODELO": modelo,
                        "Produce": produce,
                        "Inicio": ahora,
                        "Fin": ahora,            # abierto
                        "Minutos_Proceso": 0.0,  # se calculará al cerrar
                        "Minutos_Std": minutos_std,
                        "Semana": week_number(ahora),
                        "Usuario": st.session_state.user,
                        "Estimado": True,
                    }
                    db = load_parquet(DB_FILE)
                    db = pd.concat([db, pd.DataFrame([row])], ignore_index=True)
                    save_parquet(db, DB_FILE)
                    log_audit(st.session_state.user, "create", int(len(db)-1), {"via":"ui", "row": row})
                    st.success("Registro guardado ✅ (si había uno abierto, se cerró)")

# =========================
# 📈 Tablero
# =========================
with tabs[1]:
    st.subheader("Producción en vivo")
    base = load_parquet(DB_FILE)
    if base.empty:
        st.info("Sin registros.")
    else:
        c1, c2, c3 = st.columns(3)
        f_depto = c1.multiselect("Departamento", sorted(base["DEPTO"].dropna().astype(str).unique().tolist()) if "DEPTO" in base.columns else [])
        f_semana = c2.multiselect("Semana", sorted(pd.to_numeric(base["Semana"], errors="coerce").dropna().unique().tolist()) if "Semana" in base.columns else [])
        f_emp = c3.text_input("Empleado (contiene)")

        fdf = base.copy()
        if not fdf.empty:
            if f_depto: fdf = fdf[fdf["DEPTO"].astype(str).isin(f_depto)]
            if f_semana: fdf = fdf[pd.to_numeric(fdf["Semana"], errors="coerce").isin(f_semana)]
            if f_emp: fdf = fdf[fdf["EMPLEADO"].astype(str).str.contains(f_emp, case=False, na=False)]

        st.dataframe(fdf.sort_values(by="Inicio", ascending=False), use_container_width=True, hide_index=True)

# =========================
# 📚 Plantillas & Diagramas (PDF) — con miniaturas
# =========================
with tabs[2]:
    st.subheader("Plantillas & Diagramas (PDF)")
    st.caption("Sube y consulta PDFs por departamento: corte de tela, costura, carpintería, armado, resorte, cojinera, delcrón, tapiz…")

    # Upload (solo Admin)
    if st.session_state.role == "Admin":
        with st.expander("⬆️ Subir nuevo PDF", expanded=False):
            up_depto = st.selectbox("Departamento", DEPT_OPTIONS, key="up_depto")
            up_title = st.text_input("Título o descripción")
            up_tags  = st.text_input("Etiquetas (separadas por comas)", placeholder="corte, guía, plantilla A")
            up_file  = st.file_uploader("Archivo PDF", type=["pdf"])
            if st.button("Guardar PDF", type="primary"):
                if not up_file:
                    st.error("Adjunta un PDF.")
                else:
                    dep_dir = os.path.join(DOCS_DIR, sanitize_filename(up_depto))
                    os.makedirs(dep_dir, exist_ok=True)
                    safe_name = sanitize_filename(up_file.name)
                    save_path = os.path.join(dep_dir, safe_name)
                    with open(save_path, "wb") as f:
                        f.write(up_file.read())
                    relpath = os.path.relpath(save_path, ".").replace("\\","/")

                    # indexar
                    idx = load_docs_index()
                    new_id = str(int(idx["id"].max())+1) if not idx.empty else "1"
                    row = {"id": new_id,
                           "departamento": str(up_depto).strip().upper(),
                           "titulo": (up_title.strip() if up_title else safe_name),
                           "tags": up_tags.strip(),
                           "filename": safe_name,
                           "relpath": relpath,
                           "uploaded_by": st.session_state.user,
                           "ts": now_iso()}
                    idx = pd.concat([idx, pd.DataFrame([row])], ignore_index=True)
                    save_docs_index(idx)

                    # generar miniatura ahora para que aparezca en el grid
                    ensure_pdf_thumbnail(relpath)

                    st.success("PDF guardado e indexado ✅")

    # Buscador
    idx = load_docs_index()
    if idx.empty:
        st.info("Aún no hay documentos. (Admin puede subirlos arriba)")
    else:
        c1, c2 = st.columns([1,2])
        dept_filter = c1.multiselect("Departamento", DEPT_OPTIONS)
        q = c2.text_input("Buscar (título / tags / archivo)", placeholder="ej. corte, plantilla, tapiz...")

        df = idx.copy()
        if dept_filter:
            df = df[df["departamento"].isin([d.upper() for d in dept_filter])]
        if q.strip():
            qq = q.strip().lower()
            df = df[df.apply(lambda r: any(qq in str(r[col]).lower() for col in ["titulo","tags","filename"]), axis=1)]

        df = df.sort_values(by="ts", ascending=False).reset_index(drop=True)
        st.write(f"{len(df)} documento(s) encontrado(s).")

        # ---- Grid de tarjetas con miniatura ----
        cols_per_row = 2 if st.session_state.get("_is_mobile", False) else 3
        # heurística simple para mobile: ancho de la app < 520px
        try:
            # no hay API oficial; dejamos bandera manual si quieres menearlo
            pass
        except:
            pass

        # dibujar grid
        for i in range(0, len(df), cols_per_row):
            cols = st.columns(cols_per_row)
            for j, (_, r) in enumerate(df.iloc[i:i+cols_per_row].iterrows()):
                with cols[j]:
                    path = r["relpath"]
                    abs_path = path if os.path.isabs(path) else os.path.join(".", path)
                    thumb = ensure_pdf_thumbnail(path)
                    if thumb and os.path.exists(thumb):
                        st.image(thumb, use_container_width=True)
                    st.markdown(f"**{r['titulo']}**")
                    st.caption(f"{r['departamento']} · {r['filename']}")
                    # Acciones rápidas
                    cta1, cta2 = st.columns(2)
                    with cta1:
                        if st.button("👁️ Ver", key=f"ver_{r['id']}"):
                            st.session_state[f"open_{r['id']}"] = True
                    with cta2:
                        try:
                            with open(abs_path, "rb") as f:
                                data = f.read()
                            st.download_button("⬇️ Descargar", data=data, file_name=os.path.basename(abs_path),
                                               mime="application/pdf", key=f"dl_{r['id']}", use_container_width=True)
                        except Exception as e:
                            st.error(f"Descarga falló: {e}")
                    # viewer embebido opcional bajo cada tarjeta si se presionó "Ver"
                    if st.session_state.get(f"open_{r['id']}"):
                        show_pdf_file(abs_path, height=600)
                        st.divider()
                    st.caption(f"Etiquetas: {r['tags'] or '—'} · Por: {r['uploaded_by']} · {r['ts']}")

# =========================
# ✏️ Editar / Auditar
# =========================
with tabs[3]:
    st.subheader("Edición (solo Admin mueve tiempos) + Bitácora")
    db = load_parquet(DB_FILE)
    if db.empty:
        st.info("No hay datos para editar.")
    else:
        idx_num = st.number_input("ID de registro (0 .. n-1)", min_value=0, max_value=len(db)-1, step=1, value=0)
        row = db.iloc[int(idx_num)].to_dict()
        st.write("Registro actual:", row)

        if perms["editable"]:
            with st.form("edit_form"):
                c1, c2 = st.columns(2)
                with c1:
                    depto = st.selectbox("Departamento", options=DEPT_OPTIONS,
                                         index=max(0, DEPT_OPTIONS.index(str(row.get("DEPTO","OTRO")).upper()))
                                         if str(row.get("DEPTO","")).upper() in DEPT_OPTIONS else 0)
                    empleado = st.text_input("Empleado", value=str(row.get("EMPLEADO","")))
                    modelo = st.text_input("Modelo", value=str(row.get("MODELO","")))
                    produce = st.number_input("Produce", value=int(row.get("Produce") or 0), min_value=0)
                    min_std = st.number_input("Minutos_Std", value=float(row.get("Minutos_Std") or 0.0), min_value=0.0, step=0.5)
                with c2:
                    ini_raw = pd.to_datetime(row.get("Inicio"), errors="coerce")
                    fin_raw = pd.to_datetime(row.get("Fin"), errors="coerce")
                    if st.session_state.role=="Admin":
                        ini_date = st.date_input("Inicio (fecha)", ini_raw.date() if pd.notna(ini_raw) else date.today())
                        ini_time = st.time_input("Inicio (hora)", ini_raw.time() if pd.notna(ini_raw) else datetime.now().time().replace(second=0, microsecond=0))
                        fin_date = st.date_input("Fin (fecha)", fin_raw.date() if pd.notna(fin_raw) else date.today())
                        fin_time = st.time_input("Fin (hora)", fin_raw.time() if pd.notna(fin_raw) else datetime.now().time().replace(second=0, microsecond=0))
                        inicio = datetime.combine(ini_date, ini_time)
                        fin = datetime.combine(fin_date, fin_time)
                    else:
                        st.write("Inicio:", ini_raw)
                        st.write("Fin:", fin_raw)
                        inicio, fin = ini_raw, fin_raw

                submitted = st.form_submit_button("💾 Guardar cambios")
                if submitted:
                    before = db.iloc[int(idx_num)].to_dict()
                    db.at[int(idx_num),"DEPTO"] = str(depto).strip().upper()
                    db.at[int(idx_num),"EMPLEADO"] = empleado
                    db.at[int(idx_num),"MODELO"] = modelo
                    db.at[int(idx_num),"Produce"] = produce
                    db.at[int(idx_num),"Minutos_Std"] = min_std
                    if st.session_state.role=="Admin":
                        db.at[int(idx_num),"Inicio"] = inicio
                        db.at[int(idx_num),"Fin"] = fin
                        db.at[int(idx_num),"Minutos_Proceso"] = (pd.to_datetime(fin) - pd.to_datetime(inicio)).total_seconds()/60.0
                    save_parquet(db, DB_FILE)
                    after = db.iloc[int(idx_num)].to_dict()
                    log_audit(st.session_state.user, "update", int(idx_num), {"before": before, "after": after})
                    st.success("Actualizado ✅")

        st.markdown("---")
        st.subheader("Bitácora")
        audit = load_parquet(AUDIT_FILE)
        if audit.empty:
            st.caption("Sin eventos aún.")
        else:
            st.dataframe(audit.sort_values(by="ts", ascending=False).head(300),
                         use_container_width=True, hide_index=True)

# =========================
# 🛠️ Admin
# =========================
with tabs[4]:
    if st.session_state.role!="Admin":
        st.info("Solo Admin puede administrar.")
    else:
        st.subheader("Catálogo de Empleados por Departamento")
        emp_cat = load_emp_catalog()
        cA, cB = st.columns([1,2])
        with cA:
            dep_new = st.selectbox("Departamento", DEPT_OPTIONS, index=0, key="dep_new")
            emp_new = st.text_input("➕ Empleado nuevo")
            if st.button("Guardar empleado"):
                if emp_new.strip():
                    add_emp_to_catalog(dep_new, emp_new.strip())
                    st.success("Empleado agregado al catálogo"); st.rerun()
        with cB:
            st.dataframe(emp_cat, use_container_width=True, hide_index=True)
        st.download_button("⬇️ Descargar cat_empleados.csv",
                           data=emp_cat.to_csv(index=False).encode("utf-8"),
                           file_name="cat_empleados.csv", mime="text/csv")
        up_emp = st.file_uploader("Subir cat_empleados.csv", type=["csv"])
        if up_emp is not None:
            try:
                dfu = pd.read_csv(up_emp, dtype=str)
                if {"departamento","empleado"}.issubset(dfu.columns):
                    save_emp_catalog(dfu)
                    st.success("Catálogo de empleados actualizado"); st.rerun()
                else:
                    st.error("El CSV debe tener columnas: departamento, empleado")
            except Exception as e:
                st.error(f"CSV inválido: {e}")

        st.markdown("---")
        st.subheader("Catálogo de Modelos (global)")
        mod_cat_list = load_model_catalog()
        st.dataframe(pd.DataFrame({"modelo": mod_cat_list}), use_container_width=True, hide_index=True)
        nuevo_mod = st.text_input("➕ Modelo nuevo")
        if st.button("Guardar modelo"):
            save_model_catalog(list(set(mod_cat_list + ([nuevo_mod] if nuevo_mod.strip() else []))))
            st.success("Modelo agregado"); st.rerun()
        st.download_button("⬇️ Descargar cat_modelos.csv",
                           data=pd.DataFrame({"modelo": load_model_catalog()}).to_csv(index=False).encode("utf-8"),
                           file_name="cat_modelos.csv", mime="text/csv")
        up_mod = st.file_uploader("Subir cat_modelos.csv", type=["csv"], key="up_mod")
        if up_mod is not None:
            try:
                dfm = pd.read_csv(up_mod, dtype=str)
                if "modelo" in dfm.columns:
                    save_model_catalog(dfm["modelo"].dropna().astype(str).tolist())
                    st.success("Catálogo de modelos actualizado"); st.rerun()
                else:
                    st.error("El CSV debe tener columna: modelo")
            except Exception as e:
                st.error(f"CSV inválido: {e}")

st.caption("© 2025 · Destajo móvil con roles, auditoría y repositorio de plantillas por departamento (con miniaturas).")
