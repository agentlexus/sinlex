"""Параметры заготовки, расчёт стоимости и распределение затрат."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import streamlit as st

from upload_step import (
    WP_OPTIONS,
    WP_ROD,
    format_model_dims,
    format_part_family,
    infer_part_family_from_geometry,
    is_rod_wp,
    normalize_wp_type,
)
from utils import chip_prices, material_prices, save_project_data

_CRITERIA_CODE_LABELS: Dict[str, str] = {
    "ra_finish_16": "Ra ≤ 1.6 (чистовая)",
    "ra_grinding": "Ra < 1.6 (шлифование)",
    "hole_tolerance": "Отверстия с допуском",
    "threaded_hole": "Резьба",
    "keyway": "Шпоночный паз",
    "finish_pass_global": "Финишный проход",
}


def _format_hours_h(value: float) -> str:
    if value < 1:
        return f"{round(value * 60)} мин"
    return f"{value:.2f} ч"


def _criteria_has_ui(criteria: dict | None) -> bool:
    return bool(criteria and criteria.get("active_codes"))


def render_drawing_criteria_header(criteria: dict | None) -> None:
    """Chips и summary под заголовком стоимости (CR-4)."""
    if not _criteria_has_ui(criteria):
        return
    summary = (criteria or {}).get("summary_ru", "").strip()
    if summary:
        st.caption(summary)
    chips = [
        _CRITERIA_CODE_LABELS.get(code, code)
        for code in (criteria or {}).get("active_codes") or []
        if code != "finish_pass_global"
    ]
    if chips:
        st.markdown(" ".join(f"`{label}`" for label in chips))


def _modifier_summary_lines(
    modifiers: dict | None,
    breakdown: dict | None,
) -> List[str]:
    mods = modifiers or {}
    lines: List[str] = []
    cut = float(mods.get("cutting_mult") or 1.0)
    setup_m = float(mods.get("setup_mult") or 1.0)
    cam_m = float(mods.get("cam_mult") or 1.0)
    if cut > 1.0:
        lines.append(f"Резание: ×{cut:g}")
    if setup_m > 1.0:
        add_h = float(mods.get("setup_add_h") or 0.0)
        if add_h > 0:
            lines.append(f"Наладка: ×{setup_m:g} (+{add_h:g} ч к полной наладке)")
        else:
            lines.append(f"Наладка: ×{setup_m:g}")
    if cam_m > 1.0:
        lines.append(f"Написание УП: ×{cam_m:g}")
    measure = float(mods.get("measure_per_part_h") or 0.0)
    if measure > 0:
        lines.append(f"Контроль: +{measure:g} ч/шт")
    thread_h = float(mods.get("thread_cam_add_h") or 0.0)
    if thread_h > 0:
        lines.append(f"Доп. УП (резьба): +{thread_h:g} ч")
    keyway_h = float(mods.get("keyway_cam_add_h") or 0.0)
    if keyway_h > 0:
        lines.append(f"Доп. УП (шпон. паз): +{keyway_h:g} ч")
    grind = float(
        (breakdown or {}).get("grind_price_mult")
        or mods.get("grind_price_mult")
        or 1.0
    )
    if grind > 1.0:
        lines.append(f"Шлифование (коэфф. цены): ×{grind:g}")
    ops_add = mods.get("operations_add") or (breakdown or {}).get("operations_add") or []
    if ops_add:
        lines.append("Процессы: " + ", ".join(str(o) for o in ops_add))
    return lines


def build_criteria_table_rows(
    criteria: dict | None,
    breakdown: dict | None = None,
) -> List[Dict[str, str]]:
    """Строки таблицы active_codes → описание и влияние."""
    if not criteria:
        return []
    mods = (criteria or {}).get("modifiers") or {}
    bd = breakdown or {}
    rows: List[Dict[str, str]] = []
    for code in (criteria.get("active_codes") or []):
        if code == "finish_pass_global":
            continue
        label = _CRITERIA_CODE_LABELS.get(code, code)
        effects: List[str] = []
        if code in ("ra_finish_16", "finish_pass_global"):
            if float(mods.get("cutting_mult") or 1) > 1:
                effects.append(f"резание ×{mods['cutting_mult']:g}")
        if code in ("ra_finish_16", "hole_tolerance", "keyway"):
            if float(mods.get("setup_mult") or 1) > 1:
                effects.append(f"наладка ×{mods['setup_mult']:g}")
        if code == "hole_tolerance" and float(mods.get("measure_per_part_h") or 0) > 0:
            effects.append(f"+{mods['measure_per_part_h']:g} ч контроль/шт")
        if code == "ra_grinding":
            g = float(mods.get("grind_price_mult") or 1)
            if g > 1:
                effects.append(f"цена ×{g:g}")
        if code == "threaded_hole" and float(mods.get("thread_cam_add_h") or 0) > 0:
            effects.append(f"+{mods['thread_cam_add_h']:g} ч УП")
        if code == "keyway" and float(mods.get("keyway_cam_add_h") or 0) > 0:
            effects.append(f"+{mods['keyway_cam_add_h']:g} ч УП")
        if not effects:
            effects.append("см. общие множители ниже")
        rows.append(
            {
                "Код": code,
                "Критерий": label,
                "Влияние": "; ".join(effects),
            }
        )
    return rows


def render_quote_time_delta(
    quote_base: dict | None,
    quote_adjusted: dict | None,
) -> None:
    """Δ времени база STEP vs с критериями чертежа."""
    if not quote_base or not quote_adjusted:
        return
    base_mhpu = float(quote_base.get("mhpu") or 0)
    adj_mhpu = float(quote_adjusted.get("mhpu") or 0)
    delta = adj_mhpu - base_mhpu
    if abs(delta) < 0.01:
        return
    sign = "+" if delta > 0 else ""
    st.caption(
        f"Δ к расчёту только по STEP: **{sign}{_format_hours_h(delta)}**/шт на станке "
        f"(было {_format_hours_h(base_mhpu)}, стало {_format_hours_h(adj_mhpu)})"
    )


def render_drawing_criteria_tab(
    criteria: dict | None,
    criteria_breakdown: dict | None,
) -> None:
    """Вкладка «Критерии чертежа»."""
    if not _criteria_has_ui(criteria):
        st.caption("Критерии из чертежа не применялись (расчёт только по STEP).")
        return
    rows = build_criteria_table_rows(criteria, criteria_breakdown)
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    mods = (criteria or {}).get("modifiers") or {}
    summary_lines = _modifier_summary_lines(mods, criteria_breakdown)
    if summary_lines:
        st.markdown("**Сводка множителей**")
        for line in summary_lines:
            st.write(f"· {line}")


def render_parameters_panel(
    *,
    project_name: str,
    model_volume: float,
    dimensions: dict,
    geometry: dict,
    operations: list,
) -> dict:
    """
    Правая колонка: материал, партия, заготовка, сохранение.
    Возвращает словарь с актуальными значениями для расчёта.
    """
    wp = normalize_wp_type(st.session_state.get("wp", WP_ROD))
    st.session_state["wp"] = wp
    d1 = int(st.session_state.get("diam", 85))
    l1 = int(st.session_state.get("len", 320))
    w1 = int(st.session_state.get("wid", 100))
    h1 = int(st.session_state.get("hei", 50))
    cph = int(st.session_state.get("cost_h", 3500))
    sm = st.session_state.get("mat", "Сталь 45")

    st.markdown("### 📋 Параметры")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Процесс**")
        st.write(", ".join(operations))
    with col2:
        st.markdown("**Количество**")
        saved_bs = st.session_state.get("saved_batch_size", 1)
        batch_options = [1, 10, 50, 100, 200, 500]
        try:
            bs_index = batch_options.index(int(saved_bs)) if int(saved_bs) in batch_options else 0
        except Exception:
            bs_index = 0
        batch_size = st.selectbox(
            "",
            batch_options,
            index=bs_index,
            label_visibility="collapsed",
        )

    col3, col4 = st.columns(2)
    with col3:
        st.markdown("**Материал**")
        sm = st.selectbox(
            "",
            list(material_prices.keys()),
            index=list(material_prices.keys()).index(sm) if sm in material_prices else 0,
            key="mat_select_right",
            label_visibility="collapsed",
        )
        st.session_state["mat"] = sm
    with col4:
        st.markdown("**Станко-час, ₽**")
        cph = st.number_input(
            "",
            value=cph,
            min_value=0,
            step=100,
            label_visibility="collapsed",
            key="cost_hour_input_right",
        )
        st.session_state["cost_h"] = int(cph)

    col5, col6 = st.columns(2)
    with col5:
        st.markdown("**Тип заготовки**")
        wp = st.selectbox(
            "",
            WP_OPTIONS,
            index=WP_OPTIONS.index(wp) if wp in WP_OPTIONS else 0,
            label_visibility="collapsed",
            key="wp_select_right",
        )
        st.session_state["wp"] = wp
    with col6:
        if is_rod_wp(wp):
            st.markdown("**Диаметр, мм**")
            d1 = st.number_input(
                "",
                value=max(d1, 1),
                min_value=1,
                step=1,
                label_visibility="collapsed",
                key="diam_input_right",
            )
            st.session_state["diam"] = int(d1)
        else:
            st.markdown("**Ширина, мм**")
            w1 = st.number_input(
                "",
                value=max(w1, 1),
                min_value=1,
                step=1,
                label_visibility="collapsed",
                key="width_input_right",
            )
            st.session_state["wid"] = int(w1)

    col7, col8 = st.columns(2)
    with col7:
        st.markdown("**Длина, мм**")
        l1 = st.number_input(
            "",
            value=max(l1, 1),
            min_value=1,
            step=1,
            label_visibility="collapsed",
            key="len_input_right",
        )
        st.session_state["len"] = int(l1)
    with col8:
        if not is_rod_wp(wp):
            st.markdown("**Высота, мм**")
            h1 = st.number_input(
                "",
                value=max(h1, 1),
                min_value=1,
                step=1,
                label_visibility="collapsed",
                key="hei_input_right",
            )
            st.session_state["hei"] = int(h1)
        else:
            st.markdown("**Габариты модели**")
            st.write(
                format_model_dims(
                    dimensions,
                    st.session_state.get("model_size"),
                    operations,
                    wp,
                )
            )

    st.markdown("---")
    if st.button("💾 Сохранить параметры заготовки", use_container_width=True):
        save_project_data(
            project_name,
            sm,
            model_volume,
            dimensions,
            geometry,
            wp,
            d1 if is_rod_wp(wp) else 0,
            l1,
            w1 if not is_rod_wp(wp) else 0,
            h1 if not is_rod_wp(wp) else 0,
            cph,
            batch_size,
        )
        st.session_state["saved_batch_size"] = batch_size
        st.session_state["user_blank_dims_locked"] = True
        st.success("Параметры сохранены")

    return {
        "wp": wp,
        "d1": d1,
        "l1": l1,
        "w1": w1,
        "h1": h1,
        "cph": cph,
        "sm": sm,
        "batch_size": batch_size,
        "mp": material_prices[sm],
    }


def render_geometry_captions(geometry: dict, dimensions: dict, operations: list, wp: str) -> None:
    if not geometry:
        return
    col_geo1, col_geo2, col_geo3, col_geo4 = st.columns(4)
    with col_geo1:
        st.caption(
            f"Габариты: {format_model_dims(dimensions, st.session_state.get('model_size'), operations, wp)}"
        )
    with col_geo2:
        st.caption(f"Семейство: {format_part_family(geometry)}")
    with col_geo3:
        st.caption(f"Тонкие стенки: {'да' if geometry.get('thin_walls') else 'нет'}")
    with col_geo4:
        st.caption(f"Сложность: {geometry.get('complexity', '—')}")
    if geometry.get("setup_count_total"):
        st.caption(
            f"Установы (OCC): всего {geometry['setup_count_total']}"
            + (
                f", токарных {geometry['setup_count_turning']}"
                if geometry.get("setup_count_turning")
                else ""
            )
            + (
                f", фрезерных {geometry['setup_count_milling']}"
                if geometry.get("setup_count_milling")
                else ""
            )
        )


def compute_costing_snapshot(
    *,
    geometry: dict,
    dimensions: dict,
    operations: list,
    model_volume: float,
    params: dict,
    drawing_criteria: dict | None = None,
    cam_rate_per_hour: float | None = None,
) -> dict:
    """Расчёт стоимости без отрисовки UI (для размещения заказа и сохранения)."""
    wp = params["wp"]
    d1 = params["d1"]
    l1 = params["l1"]
    w1 = params["w1"]
    h1 = params["h1"]
    cph = params["cph"]
    sm = params["sm"]
    batch_size = params["batch_size"]
    mp = params["mp"]

    wp_cost = wp
    d1_cost = int(d1)
    l1_cost = int(l1)
    w1_cost = int(w1)
    h1_cost = int(h1)

    from machining_cost import (
        DEFAULT_CAM_RATE,
        blank_volume_mm3,
        compute_machining_quote,
        removal_rate_cm3_h,
        removal_volume_cm3,
    )

    cam_rate = cam_rate_per_hour
    if cam_rate is None:
        cam_rate = st.session_state.get("cam_rate", DEFAULT_CAM_RATE)

    if is_rod_wp(wp_cost):
        bv = blank_volume_mm3(wp_cost, diameter=d1_cost, length=l1_cost)
    else:
        bv = blank_volume_mm3(wp_cost, width=w1_cost, length=l1_cost, height=h1_cost)
    rvc = removal_volume_cm3(bv, model_volume)
    if "Титан" in sm:
        den = 4.43
    elif "Алюминий" in sm:
        den = 2.71
    else:
        den = 7.85
    rmkg = (rvc * den) / 1000
    tcm = rmkg * batch_size
    cpk = chip_prices.get(sm, 15)
    cr = tcm * cpk

    rr = removal_rate_cm3_h(
        geometry,
        material=sm,
        detail_index=float(
            (geometry or {}).get("detail_index") or st.session_state.get("detail_index") or 0
        ),
    )

    part_family_code = (geometry or {}).get("part_family") or ""
    if not part_family_code and geometry:
        part_family_code = infer_part_family_from_geometry(geometry, dimensions)

    mq = compute_machining_quote(
        removal_volume_cm3=rvc,
        removal_rate=rr,
        batch_size=batch_size,
        model_volume_mm3=model_volume,
        density_g_cm3=den,
        operations=operations,
        geometry=geometry,
        workpiece_type=wp_cost,
        part_family=part_family_code,
        cam_rate_per_hour=cam_rate,
        drawing_criteria=drawing_criteria,
    )
    cutting_per_part_h = mq["cutting_per_part_h"]
    setup_batch_h = mq["setup_batch_h"]
    setup_per_part_h = mq["setup_per_part_h"]
    setup_full_h = mq["setup_full_h"]
    setup_amort = mq["setup_amort"]
    cam_batch_h = mq["cam_batch_h"]
    cam_per_part_h = mq["cam_per_part_h"]
    cam_full_h = mq["cam_full_h"]
    cam_amort = mq["cam_amort"]
    cam_cost = mq["cam_cost_batch"]
    show_cam = mq["cam_applies"]
    mhpu = mq["mhpu"]
    mht = mq["mht"]
    grind_price_mult = float(mq.get("grind_price_mult") or 1.0)
    mct = rmkg * mp * batch_size
    mcst = mht * cph
    if grind_price_mult > 1.0:
        mcst = mcst * grind_price_mult
    tc = mcst + mct + cam_cost - cr
    cpu = tc / batch_size

    return {
        "cpu": cpu,
        "tc": tc,
        "mhpu": mhpu,
        "mht": mht,
        "cutting_per_part_h": cutting_per_part_h,
        "setup_per_part_h": setup_per_part_h,
        "cam_per_part_h": cam_per_part_h,
        "sm": sm,
        "wp": wp,
        "cph": cph,
        "batch_size": batch_size,
        "d1": d1,
        "l1": l1,
        "w1": w1,
        "h1": h1,
        "show_cam": show_cam,
        "setup_batch_h": setup_batch_h,
        "setup_full_h": setup_full_h,
        "setup_amort": setup_amort,
        "cam_batch_h": cam_batch_h,
        "cam_full_h": cam_full_h,
        "cam_amort": cam_amort,
        "cam_cost": cam_cost,
        "drawing_criteria": mq.get("drawing_criteria"),
        "quote_base": mq.get("quote_base"),
        "quote_adjusted": mq.get("quote_adjusted"),
        "criteria_breakdown": mq.get("criteria_breakdown"),
        "grind_price_mult": grind_price_mult,
        "d1_cost": d1_cost,
        "l1_cost": l1_cost,
        "w1_cost": w1_cost,
        "h1_cost": h1_cost,
        "wp_cost": wp_cost,
        "bv": bv,
        "den": den,
        "rmkg": rmkg,
        "tcm": tcm,
        "cr": cr,
        "mct": mct,
        "mcst": mcst,
    }


def render_costing_section(
    *,
    geometry: dict,
    dimensions: dict,
    operations: list,
    model_volume: float,
    params: dict,
    drawing_criteria: dict | None = None,
) -> dict:
    """
    Расчёт и отображение стоимости. Возвращает dict с cpu, tc, mhpu, mht и пр. для техкарты/сохранения.
    """
    snap = compute_costing_snapshot(
        geometry=geometry,
        dimensions=dimensions,
        operations=operations,
        model_volume=model_volume,
        params=params,
        drawing_criteria=drawing_criteria,
    )
    cpu = snap["cpu"]
    tc = snap["tc"]
    mhpu = snap["mhpu"]
    mht = snap["mht"]
    cutting_per_part_h = snap["cutting_per_part_h"]
    setup_per_part_h = snap["setup_per_part_h"]
    cam_per_part_h = snap["cam_per_part_h"]
    sm = snap["sm"]
    batch_size = snap["batch_size"]
    show_cam = snap["show_cam"]
    setup_batch_h = snap["setup_batch_h"]
    setup_full_h = snap["setup_full_h"]
    setup_amort = snap["setup_amort"]
    cam_batch_h = snap["cam_batch_h"]
    cam_full_h = snap["cam_full_h"]
    cam_amort = snap["cam_amort"]
    cam_cost = snap["cam_cost"]
    criteria_breakdown = snap["criteria_breakdown"] or {}
    quote_base = snap["quote_base"]
    quote_adjusted = snap["quote_adjusted"]
    d1_cost = snap["d1_cost"]
    l1_cost = snap["l1_cost"]
    w1_cost = snap["w1_cost"]
    h1_cost = snap["h1_cost"]
    wp_cost = snap["wp_cost"]
    cph = snap["cph"]
    bv = snap["bv"]
    den = snap["den"]
    rmkg = snap["rmkg"]
    tcm = snap["tcm"]
    cr = snap["cr"]
    mct = snap["mct"]
    mcst = snap["mcst"]
    grind_price_mult = snap["grind_price_mult"]

    st.markdown("### 🧾 Стоимость за изделие")
    render_drawing_criteria_header(drawing_criteria)
    render_quote_time_delta(quote_base, quote_adjusted)
    cc1, cc2 = st.columns(2)
    price_label = (
        "**Цена изделия (вкл. УП):**"
        if show_cam
        else f"**Цена за 1 шт. (партия {batch_size} шт.)**"
    )
    with cc1:
        st.metric(price_label, f"{int(cpu):,} ₽".replace(",", " "))
    with cc2:
        st.metric("**Общая стоимость**", f"{int(tc):,} ₽".replace(",", " "))

    st.markdown("---")
    st.markdown("### 📊 Распределение затрат")
    show_criteria_tab = _criteria_has_ui(drawing_criteria)
    tab_labels = ["🧱 Сырьё", "⚙️ Обработка", "🛠️ Наладка"]
    if show_cam:
        tab_labels.append("💻 Написание УП")
    if show_criteria_tab:
        tab_labels.append("📐 Критерии чертежа")
    tabs = st.tabs(tab_labels)
    tab_i = 0
    t1 = tabs[tab_i]
    tab_i += 1
    t2 = tabs[tab_i]
    tab_i += 1
    t3 = tabs[tab_i]
    tab_i += 1
    t4 = None
    t_criteria = None
    if show_cam:
        t4 = tabs[tab_i]
        tab_i += 1
    if show_criteria_tab:
        t_criteria = tabs[tab_i]

    with t1:
        st.write(
            f"Размеры заготовки: Ø{d1_cost}×{l1_cost} мм"
            if is_rod_wp(wp_cost)
            else f"{w1_cost}×{l1_cost}×{h1_cost} мм"
        )
        blank_kg = bv * den / 1_000_000
        raw_kg_batch = blank_kg * batch_size
        chips_kg_batch = tcm
        st.write(f"Масса сырья (партия {batch_size} шт.): **{raw_kg_batch:.2f} кг**")
        st.write(f"Стоимость материала (партия {batch_size} шт.): **{int(mct):,} ₽**".replace(",", " "))
        st.write(f"Стружка (партия {batch_size} шт.): **{chips_kg_batch:.2f} кг**")
        st.write(f"♻ Возврат (партия {batch_size} шт.): **{int(cr):,} ₽**".replace(",", " "))
    with t2:
        st.write(
            f"Обработка/деталь: **{round(cutting_per_part_h * 60)} мин**"
            if cutting_per_part_h < 1
            else f"Обработка/деталь: **{round(cutting_per_part_h, 2)} ч**"
        )
        st.write(
            f"Общее время (вкл. наладку): **{round(mhpu * 60)} мин**"
            if mhpu < 1
            else f"Общее время (вкл. наладку): **{round(mhpu, 2)} ч**"
        )
        st.write(
            f"Изготовление (партия {batch_size} шт.): **{round(mht * 60)} мин**"
            if mht < 1
            else f"Изготовление (партия {batch_size} шт.): **{round(mht, 1)} ч**"
        )
        st.caption(
            f"≈ **{round(mhpu * 60)} мин**/шт"
            if mhpu < 1
            else f"≈ **{round(mhpu, 2)} ч**/шт (обработка + наладка на деталь)"
        )
        st.write(f"Ставка: **{cph:,} ₽**".replace(",", " "))
        st.write(f"Изготовление: **{int(mcst / batch_size):,} ₽/шт**".replace(",", " "))
        if show_criteria_tab and quote_base and quote_adjusted:
            base_cut = float(quote_base.get("cutting_per_part_h") or 0)
            adj_cut = float(quote_adjusted.get("cutting_per_part_h") or 0)
            if abs(adj_cut - base_cut) >= 0.01:
                st.caption(
                    f"Резание с критериями: {_format_hours_h(adj_cut)}/шт "
                    f"(STEP: {_format_hours_h(base_cut)})"
                )
    with t3:
        st.write(
            f"На партию ({batch_size} шт.): **{setup_batch_h:.1f} ч** "
            f"(от **{setup_full_h:.1f} ч** при 1 шт., аморт. **{setup_amort:.0%}**)"
        )
        st.write(
            f"На деталь: **{round(setup_per_part_h * 60)} мин**"
            if setup_per_part_h < 1
            else f"На деталь: **{setup_per_part_h:.2f} ч**"
        )
    if t_criteria is not None:
        with t_criteria:
            render_drawing_criteria_tab(drawing_criteria, criteria_breakdown)
    if show_cam and t4 is not None:
        with t4:
            st.markdown("**Ставка программиста, ₽/ч**")
            st.number_input(
                "Ставка программиста, ₽/ч",
                min_value=0,
                step=50,
                key="cam_rate",
                label_visibility="collapsed",
            )
            st.write(
                f"Написание УП (партия {batch_size} шт.): **{int(cam_cost):,} ₽**".replace(",", " ")
            )
            st.write(
                f"На партию: **{cam_batch_h:.1f} ч** "
                f"(от **{cam_full_h:.1f} ч** при 1 шт., аморт. **{cam_amort:.0%}**)"
            )
            st.write(
                f"На деталь: **{round(cam_per_part_h * 60)} мин**"
                if cam_per_part_h < 1
                else f"На деталь: **{cam_per_part_h:.2f} ч**"
            )

    return {
        "cpu": cpu,
        "tc": tc,
        "mhpu": mhpu,
        "mht": mht,
        "cutting_per_part_h": cutting_per_part_h,
        "setup_per_part_h": setup_per_part_h,
        "cam_per_part_h": cam_per_part_h,
        "sm": sm,
        "wp": snap["wp"],
        "cph": cph,
        "batch_size": batch_size,
        "d1": snap["d1"],
        "l1": snap["l1"],
        "w1": snap["w1"],
        "h1": snap["h1"],
        "drawing_criteria": snap.get("drawing_criteria"),
        "quote_base": quote_base,
        "quote_adjusted": quote_adjusted,
        "criteria_breakdown": criteria_breakdown,
        "grind_price_mult": grind_price_mult,
    }
