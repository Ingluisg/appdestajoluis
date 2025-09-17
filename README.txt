
# App Destajo — Núcleo (Móvil) con Bitácora y Filtros

Incluye **solo** las hojas: **Tiempos**, **Tabla** y **Calendario**.

## Novedades
- **Bitácora de cambios**: registra fecha, usuario, hoja y acción (guardar, importación).
- **Filtros en Tiempos**: puedes filtrar por rango de fechas y por modelo (texto).

## Archivos
- `TIEMPOS_DESTAJO_CORE.xlsx`
- `app.py`
- `requirements.txt`
- `bitacora.csv` (se genera automáticamente al usar funciones máster)

## Ejecución
1) `pip install -r requirements.txt`
2) `streamlit run app.py`
3) Abre `http://localhost:8501`

## Acceso máster
- Usuario: `master`
- Contraseña demo: `master1234`
> Cambia la pass en producción (`st.secrets["MASTER_PASS"]`).


## Novedades (esta versión)
- **Bitácora de cambios** en `bitacora_cambios.csv` (edición/importe por hoja) sin modificar tu Excel.
- **Filtros en 'Tiempos'** por rango de fechas (auto-detección de columna) y búsqueda por modelo. Exportación de vista filtrada a CSV.
