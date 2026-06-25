"""Иконка удаления проекта вместо эмодзи корзины (списки 3D и литьё)."""
from __future__ import annotations

import base64
import functools
import os

import streamlit as st

_DELETE_ICON_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "static",
    "icons",
    "delete.svg",
)
_DELETE_KEY_PREFIX = "sinlex_del"
_DELETE_BTN_LABEL = "\u00a0"
_DELETE_ICON_SIZE_PX = round(33 / 1.3)


@functools.lru_cache(maxsize=1)
def _delete_icon_data_uri() -> str:
    with open(_DELETE_ICON_PATH, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def delete_button_label() -> str:
    return _DELETE_BTN_LABEL


def delete_button_key(scope: str, index: int) -> str:
    return f"{_DELETE_KEY_PREFIX}_{scope}_{index}"


def inject_delete_icon_button_styles() -> None:
    icon = _delete_icon_data_uri()
    st.markdown(
        f"""
<style>
[class*="st-key-{_DELETE_KEY_PREFIX}_"] button {{
    min-width: 2.7rem !important;
    padding: 0.32rem 0.5rem !important;
}}
[class*="st-key-{_DELETE_KEY_PREFIX}_"] button p {{
    width: {_DELETE_ICON_SIZE_PX}px !important;
    height: {_DELETE_ICON_SIZE_PX}px !important;
    min-height: {_DELETE_ICON_SIZE_PX}px !important;
    font-size: 0 !important;
    line-height: 0 !important;
    color: transparent !important;
    background: url("{icon}") center center / contain no-repeat !important;
    margin: 0 auto !important;
}}
</style>
""",
        unsafe_allow_html=True,
    )
