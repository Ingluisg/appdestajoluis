# =========================
# ✏️ Editar / Auditar
# =========================
with tabs[3]:
    st.subheader("Edición (solo Admin mueve tiempos) + Bitácora")

    db = load_parquet(DB_FILE)
    rates = load_rates_csv()

    if db.empty:
        st.info("No hay datos para editar.")
    else:
        idx_num = st.number_input(
            "ID de registro (0 .. n-1)",
            min_value=0,
            max_value=len(db) - 1,
            step=1,
            value=0,
        )
        row = db.iloc[int(idx_num)].to_dict()

        if st.session_state.role != "Admin":
            st.warning("Solo **Admin** puede modificar horas Inicio/Fin.")

        with st.form("edit_form"):
            c1, c2 = st.columns(2)

            with c1:
                depto = st.selectbox(
                    "Departamento",
                    options=sorted(
                        list(set(DEPT_FALLBACK) | set(rates["DEPTO"].dropna().astype(str).tolist()))
                    ) or DEPT_FALLBACK,
                    index=0,
                )
                empleado = st.text_input("Empleado", value=str(row.get("EMPLEADO", "")))
                modelo = st.text_input("Modelo", value=str(row.get("MODELO", "")))
                produce = st.number_input(
                    "Produce", value=int(num(row.get("Produce"), 0)), min_value=0
                )
                min_std = st.number_input(
                    "Minutos_Std",
                    value=float(num(row.get("Minutos_Std"), 0.0)),
                    min_value=0.0,
                    step=0.5,
                )

            with c2:
                ini_raw = pd.to_datetime(row.get("Inicio"), errors="coerce")
                fin_raw = pd.to_datetime(row.get("Fin"), errors="coerce")

                if st.session_state.role == "Admin":
                    ini_date = st.date_input(
                        "Inicio (fecha)",
                        ini_raw.date() if pd.notna(ini_raw) else date.today(),
                    )
                    ini_time = st.time_input(
                        "Inicio (hora)",
                        ini_raw.time()
                        if pd.notna(ini_raw)
                        else datetime.now().time().replace(second=0, microsecond=0),
                    )
                    fin_date = st.date_input(
                        "Fin (fecha)",
                        fin_raw.date() if pd.notna(fin_raw) else date.today(),
                    )
                    fin_time = st.time_input(
                        "Fin (hora)",
                        fin_raw.time()
                        if pd.notna(fin_raw)
                        else datetime.now().time().replace(second=0, microsecond=0),
                    )
                    inicio = datetime.combine(ini_date, ini_time)
                    fin = datetime.combine(fin_date, fin_time)
                else:
                    st.write("Inicio:", ini_raw)
                    st.write("Fin:", fin_raw)
                    inicio, fin = ini_raw, fin_raw

            submitted = st.form_submit_button("💾 Guardar cambios")

        # OJO: el 'if submitted' va fuera del 'with st.form(...)'
        if submitted:
            before = db.iloc[int(idx_num)].to_dict()

            db.at[int(idx_num), "DEPTO"] = norm_depto(depto)
            db.at[int(idx_num), "EMPLEADO"] = empleado
            db.at[int(idx_num), "MODELO"] = modelo
            db.at[int(idx_num), "Produce"] = num(produce)
            db.at[int(idx_num), "Minutos_Std"] = num(min_std)

            if st.session_state.role == "Admin":
                db.at[int(idx_num), "Inicio"] = inicio
                db.at[int(idx_num), "Fin"] = fin

                minutos_ef = working_minutes_between(inicio, fin)
                db.at[int(idx_num), "Minutos_Proceso"] = minutos_ef

                pago, esquema, tarifa = calc_pago_row(
                    norm_depto(depto), num(produce), minutos_ef, num(min_std), rates
                )
                db.at[int(idx_num), "Pago"] = pago
                db.at[int(idx_num), "Esquema_Pago"] = esquema
                db.at[int(idx_num), "Tarifa_Base"] = tarifa

            save_parquet(db, DB_FILE)
            after = db.iloc[int(idx_num)].to_dict()
            log_audit(
                st.session_state.user,
                "update",
                int(idx_num),
                {"before": before, "after": after},
            )
            st.success("Actualizado ✅")

    st.markdown("---")
    st.subheader("Bitácora")
    audit = load_parquet(AUDIT_FILE)
    if audit.empty:
        st.caption("Sin eventos aún.")
    else:
        st.dataframe(
            audit.sort_values(by="ts", ascending=False).head(400),
            use_container_width=True,
            hide_index=True,
        )

# =========================
# 🛠️ Admin
# =========================
