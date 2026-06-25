"""Пополнение баланса «Поток» (страница сохранена для обратной совместимости)."""
import streamlit as st


def render() -> None:
    from page_shell import inject_unified_main_scroll, page_title

    page_title("Баланс «Поток»")
    inject_unified_main_scroll()
    st.info("Тарифы отключены. Пополнение баланса «Поток» — через кнопку «Баланс» в верхней панели.")
    if st.button("Открыть пополнение", type="primary", key="payment_open_topup"):
        st.session_state.show_flow_topup_form = True
        st.rerun()
    if st.button("Перейти в «Поток»", key="payment_go_flow"):
        st.session_state.page = "flow"
        st.rerun()
