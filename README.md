# Devané • App de Planeación y Asignación

App simple en **Streamlit** para:
- Registrar *planeación semanal* por modelo con **código único de corrida** (evita duplicados).
- Asignar cantidades a **operadores** respetando el tope planeado.
- **Alertas**:
  - Intento de sobre-asignación (ALTA) → Administrador.
  - Corridas con faltante por asignar (MEDIA) → Supervisor.
  - Operadores **en tiempo de espera** (BAJA) por semana.
- Tablero con avance por corrida.
- Exportación de CSVs.

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
- `data/` con CSVs (se crean al ejecutar).
- `requirements.txt`
