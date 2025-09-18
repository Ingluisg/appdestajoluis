
# Destajo · Producción y Destajo (Móvil) — con Roles

## Qué incluye
- **Login con roles** (Admin, Supervisor, Nominas, RRHH, Productividad) vía `users.csv` (usuario + PIN).
- **Captura móvil** para supervisores: Día/Hora inicio/fin, Minutos_Std por pieza, Produce, etc.
- **Tablero** con KPIs y filtros (depto, semana, empleado).
- **Cálculo exacto desde Excel**Tiempos** (Eficiencia, Destajo Unitario, Pago Total) usando la tabla de **DEPARTAMENTOS** para $/hr.
- **Admin**: gestión simple de `users.csv` y exportación/borrado de la base local.

## Archivos clave
- `app.py` — app Streamlit.
- `users.csv` — credenciales (demo incluidas).
- `data/registros.parquet` — base de datos local (se crea sola).

## Ejecutar local
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Despliegue (Streamlit Cloud)
1. Sube estos archivos a tu repo GitHub.
2. En Streamlit Cloud, selecciona `app.py`.
3. (Opcional) Sube tu Excel en la pestaña **Excel (cálculo exacto)**.

## Seguridad
Este login es **básico**. Para producción real, integra SSO/LDAP/JWT y cifrado de secretos.
