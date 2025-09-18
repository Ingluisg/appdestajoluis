
# Destajo · Planeación PRIV + Roles + Alertas

## Cambios clave solicitados
- **Planeación solo visible para `Planeacion` y `Admin`** (la pestaña desaparece para otros roles).
- **Código único de plan** por **modelo + corrida + semana** (`plan_code`) con unicidad validada.
- **Match** entre planeado y capturado: muestra **asignado, faltante, avance %**.
- **Reglas duras** en Captura:
  - ❌ Bloquea si se intenta exceder lo **programado** (no permite guardar).
  - 🔔 **Alerta a Admin** cuando alguien intenta exceder el límite (quedan registradas en *Alertas*).
  - ⏳ Si se captura sin plan, se marca como **ESPERA** y genera **alerta a Supervisor**.
- **Tablero** muestra **alertas filtradas por rol** (Supervisor ve las suyas; Admin ve todas).

## Ejecutar
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Estructura de datos
- `data/planning.parquet` — planeaciones (plan_code, semana, modelo, corrida, depto, subunidad, programado, status).
- `data/registros.parquet` — capturas.
- `data/audit.parquet` — bitácora (acciones de usuario).
- `data/alerts.parquet` — alertas (level, audience, title, message, payload).
