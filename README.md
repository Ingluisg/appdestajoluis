
# Devané • Destajos v1.0 (Original, sin planeación)

Incluye:
- **Captura** de tiempos/destajos (min/px y cantidad) con cálculo de **minutos totales** y **pago estimado** (según tarifas por minuto).
- **Catálogos** (Modelos, Empleados, Líneas).
- **Tarifas** desde Excel (columnas: `modelo, operacion, tarifa_min`).
- **PDFs**: subir y visualizar embebidos.
- **Tablero** con métricas por semana/línea y por empleado, y detalle reciente.
- **Datos**: exportación y reseteo de CSVs.

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
