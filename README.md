
# Devané • Ecosistema de Producción v1.1 (Streamlit)

Incluye:
- **Captura** de producción/tiempos por línea, empleado, modelo y corrida.
- **Catálogos** (Modelos, Empleados, Líneas).
- **Tarifas** normalizadas desde Excel (se guarda en CSV).
- **PDFs**: carga y visualización embebida.
- **Planeación** semanal con **código único de corrida** (sin duplicados).
- **Asignaciones** a operadores con tope por planeación y alertas automáticas.
- **Tableros**: avance por corrida y productividad por línea (con capturas).
- **Alertas** con niveles (ALTA, MEDIA, BAJA) con visibilidad por rol.
- **Datos**: exportación de todos los CSVs y reseteo.

## Requisitos
```
pip install -r requirements.txt
```

## Ejecutar
```
streamlit run app.py
```

## Estructura
- `app.py`
- `data/` CSVs
- `pdfs/` PDFs cargados
- `requirements.txt`
