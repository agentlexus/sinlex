"""Agent Sinlex — заглушка раздела (бэкенд отключён)."""
import streamlit as st

PAGE_TITLE = "Agent Sinlex"


def render() -> None:
    from page_shell import page_title

    page_title(PAGE_TITLE)
    st.info(
        "Раздел в разработке. "
        "Интеллектуальный помощник технолога по чертежам будет доступен в следующих версиях."
    )
    st.caption(
        "Сейчас доступны загрузка проектов, экспертный анализ и калькуляция в других разделах."
    )


def clear_page_session_state() -> None:
    """Сброс ключей session_state этого раздела (и устаревших agent_lexus_*)."""
    for key in list(st.session_state.keys()):
        if key.startswith("agent_sinlex") or key.startswith("agent_lexus"):
            del st.session_state[key]
