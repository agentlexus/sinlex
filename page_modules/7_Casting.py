"""Литьевые проекты: список и переход к загрузке STEP."""
import html

import requests
import streamlit as st

from utils import NGROK_URL, format_project_date_label, get_headers
from project_dates import project_activity_iso
from page_shell import inject_unified_main_scroll, page_title, refresh_casting_list
from ui_delete_button import delete_button_key, delete_button_label, inject_delete_icon_button_styles

_NEW_CASTING_BTN_KEY = "casting_new_btn"
_CASTING_COLS = [3, 1.5, 1.5, 1, 0.45]
_CASTING_HEADERS = ("Название", "Материал", "Стоимость", "Дата", "")


def _inject_new_casting_button_style(*, after: bool = False) -> None:
    """Кнопка «Новое литье» в стиле «Новый проект» (локальный стиль)."""
    ORANGE = "#ff8800"
    ORANGE_HOVER = "#595957"
    st.markdown(
        f"""
<style>
[data-testid="stMainBlockContainer"] .st-key-{_NEW_CASTING_BTN_KEY} button[kind="secondary"],
[data-testid="stMainBlockContainer"] .st-key-{_NEW_CASTING_BTN_KEY} button[kind="primary"],
[data-testid="stMainBlockContainer"] .st-key-{_NEW_CASTING_BTN_KEY} button {{
    background-color: {ORANGE} !important;
    background: {ORANGE} !important;
    border-color: {ORANGE} !important;
    color: #ffffff !important;
    box-shadow: none !important;
}}
[data-testid="stMainBlockContainer"] .st-key-{_NEW_CASTING_BTN_KEY} button:hover {{
    background-color: {ORANGE_HOVER} !important;
    background: {ORANGE_HOVER} !important;
    border-color: {ORANGE_HOVER} !important;
    color: #ffffff !important;
}}
</style>
""",
        unsafe_allow_html=True,
    )


def _inject_casting_table_layout() -> None:
    st.markdown(
        """
<style>
#sinlex-casting-page { display: none !important; }
[data-testid="stAppViewContainer"]:has(#sinlex-casting-page) section[data-testid="stMain"] > div.block-container,
[data-testid="stAppViewContainer"]:has(#sinlex-casting-page) [data-testid="stMainBlockContainer"] {
    max-width: 100% !important;
    width: 100% !important;
    overflow-x: visible !important;
}
[data-testid="stAppViewContainer"]:has(#sinlex-casting-page) [data-testid="stHorizontalBlock"] {
    width: 100% !important;
    max-width: 100% !important;
    overflow-x: visible !important;
    flex-wrap: nowrap !important;
    gap: 0.5rem !important;
}
[data-testid="stAppViewContainer"]:has(#sinlex-casting-page) [data-testid="column"] {
    min-width: 0 !important;
    overflow: visible !important;
}
.casting-table-header-cell {
    font-size: 17px;
    font-weight: 600;
    color: #595957;
    line-height: 1.3;
    white-space: nowrap;
    width: 100%;
    margin: 0;
}
.casting-table-header-cell.left {
    text-align: left;
    padding-left: 0.15rem;
}
.casting-table-header-cell.center {
    text-align: center;
}
[data-testid="stAppViewContainer"]:has(#sinlex-casting-page) [data-testid="stHorizontalBlock"]:has(.casting-table-header-cell) {
    width: 100% !important;
    max-width: 100% !important;
    align-items: center !important;
    margin: 0.75rem 0 0.35rem 0;
    padding: 0.85rem 0.95rem;
    background: #ececeb;
    border: 1px solid #d8d8d6;
    border-radius: 8px;
    box-sizing: border-box;
}
[data-testid="stAppViewContainer"]:has(#sinlex-casting-page) [data-testid="stHorizontalBlock"]:has(.casting-table-header-cell) [data-testid="column"] {
    display: flex !important;
    flex-direction: column !important;
    justify-content: center !important;
    min-width: 0 !important;
}
[data-testid="stAppViewContainer"]:has(#sinlex-casting-page) [data-testid="stHorizontalBlock"]:has(.casting-table-header-cell) [data-testid="column"]:first-child {
    align-items: flex-start !important;
}
[data-testid="stAppViewContainer"]:has(#sinlex-casting-page) [data-testid="stHorizontalBlock"]:has(.casting-table-header-cell) [data-testid="column"]:not(:first-child) {
    align-items: center !important;
}
[data-testid="stAppViewContainer"]:has(#sinlex-casting-page) [data-testid="stHorizontalBlock"]:has(.casting-table-header-cell) [data-testid="stMarkdownContainer"],
[data-testid="stAppViewContainer"]:has(#sinlex-casting-page) [data-testid="stHorizontalBlock"]:has(.casting-table-header-cell) [data-testid="stMarkdownContainer"] p {
    width: 100% !important;
    margin: 0 !important;
}
[data-testid="stAppViewContainer"]:has(#sinlex-casting-page) [data-testid="stHorizontalBlock"]:has([class*="st-key-casting_"]) {
    align-items: center !important;
}
[data-testid="stAppViewContainer"]:has(#sinlex-casting-page) [data-testid="stHorizontalBlock"]:has([class*="st-key-casting_"]) [data-testid="column"] {
    display: flex !important;
    flex-direction: column !important;
    justify-content: center !important;
    align-self: stretch !important;
    min-height: 0 !important;
}
[data-testid="stAppViewContainer"]:has(#sinlex-casting-page) [data-testid="stHorizontalBlock"]:has([class*="st-key-casting_"]) [data-testid="column"] [data-testid="stVerticalBlock"] {
    justify-content: center !important;
    width: 100% !important;
}
[data-testid="stAppViewContainer"]:has(#sinlex-casting-page) [data-testid="stHorizontalBlock"]:has([class*="st-key-casting_"]) [data-testid="column"]:first-child {
    align-items: flex-start !important;
    text-align: left !important;
}
[data-testid="stAppViewContainer"]:has(#sinlex-casting-page) [data-testid="stHorizontalBlock"]:has([class*="st-key-casting_"]) [data-testid="column"]:not(:first-child) {
    align-items: center !important;
    text-align: center !important;
}
[data-testid="stAppViewContainer"]:has(#sinlex-casting-page) [data-testid="stHorizontalBlock"]:has([class*="st-key-casting_"]) [data-testid="column"]:not(:first-child) [data-testid="stMarkdownContainer"],
[data-testid="stAppViewContainer"]:has(#sinlex-casting-page) [data-testid="stHorizontalBlock"]:has([class*="st-key-casting_"]) [data-testid="column"]:not(:first-child) [data-testid="stMarkdownContainer"] p {
    width: 100% !important;
    text-align: center !important;
    margin: 0 !important;
}
[data-testid="stAppViewContainer"]:has(#sinlex-casting-page) [data-testid="stHorizontalBlock"]:has([class*="st-key-casting_"]) [data-testid="column"]:not(:first-child) [data-testid="stElementContainer"] {
    width: 100% !important;
    display: flex !important;
    justify-content: center !important;
}
[data-testid="stAppViewContainer"]:has(#sinlex-casting-page) [data-testid="stHorizontalBlock"]:has([class*="st-key-casting_"]) [data-testid="column"]:not(:first-child) .stButton {
    width: auto !important;
    display: flex !important;
    justify-content: center !important;
}
</style>
<div id="sinlex-casting-page"></div>
""",
        unsafe_allow_html=True,
    )


def _render_casting_header_row() -> None:
    cols = st.columns(_CASTING_COLS)
    for idx, (col, label) in enumerate(zip(cols, _CASTING_HEADERS)):
        align = "left" if idx == 0 else "center"
        with col:
            st.markdown(
                f'<div class="casting-table-header-cell {align}">{html.escape(label)}</div>',
                unsafe_allow_html=True,
            )


def render() -> None:
    """Страница списка литьевых проектов."""
    page_title("Литье")
    inject_unified_main_scroll()
    _inject_casting_table_layout()
    inject_delete_icon_button_styles()
    _inject_new_casting_button_style()
    btn_col, _sp = st.columns([1, 3])
    with btn_col:
        if st.button(
            "Новое литье",
            use_container_width=True,
            type="secondary",
            key=_NEW_CASTING_BTN_KEY,
        ):
            st.session_state.project_domain = "casting"
            st.session_state.cached_step = None
            st.session_state.cached_step_name = None
            st.session_state.selected_project = None
            st.session_state.page = "upload"
            st.rerun()

    _inject_new_casting_button_style(after=True)
    refresh_casting_list()
    projects = st.session_state.get("casting_projects") or []
    if not projects:
        st.info("Пока нет литьевых проектов.")
        return

    _render_casting_header_row()
    for i, p in enumerate(projects):
        c1, c2, c3, c4, c5 = st.columns(_CASTING_COLS)
        with c1:
            if st.button(p["name"], key=f"casting_{i}", type="tertiary"):
                st.session_state.project_domain = "casting"
                st.session_state.selected_project = p
                st.session_state.page = "upload"
                st.rerun()
        with c2:
            st.write(p.get("material", "—"))
        with c3:
            st.write(
                f"{int(p.get('total_cost', 0)):,} ₽".replace(",", " ")
                if p.get("total_cost")
                else "—"
            )
        with c4:
            st.write(format_project_date_label(project_activity_iso(p)))
        with c5:
            if st.button(
                delete_button_label(),
                key=delete_button_key("cast", i),
                type="secondary",
                help="Удалить проект",
            ):
                dn = p["name"]
                st.session_state.casting_projects = [
                    pp for pp in (st.session_state.get("casting_projects") or []) if pp["name"] != dn
                ]
                try:
                    requests.delete(
                        f"{NGROK_URL}/casting/{dn}",
                        headers=get_headers(),
                        timeout=5,
                    )
                except Exception:
                    pass
                st.rerun()

