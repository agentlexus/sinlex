"""Мои заказы — список и карточка заказа."""
from __future__ import annotations

import html
import json
import os
import urllib.parse
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

import streamlit as st

from orders_store import ORDER_STAGES, add_requisites_files, delete_user_order, list_user_orders, load_order, save_order, stage_label
from page_shell import inject_unified_main_scroll, page_title
from ui_delete_button import delete_button_key, delete_button_label, inject_delete_icon_button_styles

_MANAGER_EMAIL = "info@sinlex.ru"
_CHAT_REPLY_EMAIL = "agent_lexus@mail.ru"

# Дизайн-система Sinlex
_C = {
    "orange": "#ff8800",
    "teal": "#14b8a6",
    "teal_dark": "#0d9488",
    "teal_light": "#ccfbf1",
    "teal_muted": "#5eead4",
    "ink": "#1a1d26",
    "muted": "#6b7280",
    "line": "#e5e7eb",
    "surface": "#ffffff",
    "wash": "#f6f7f9",
    "header": "#595957",
}


def _orders_css() -> str:
    o = _C["orange"]
    return f"""
<style>
#sinlex-orders-page {{ display: none !important; }}

/* —— Общее —— */
[data-testid="stAppViewContainer"]:has(#sinlex-orders-page) [data-testid="stMainBlockContainer"] {{
    max-width: 1080px !important;
}}

/* Пустое состояние */
.so-empty {{
    text-align: center;
    padding: 3.5rem 2rem;
    background: linear-gradient(180deg, {_C["wash"]} 0%, #fff 100%);
    border: 1px dashed {_C["line"]};
    border-radius: 16px;
    margin-top: 1rem;
}}
.so-empty h3 {{
    margin: 0 0 0.5rem;
    font-size: 1.15rem;
    font-weight: 600;
    color: {_C["ink"]};
}}
.so-empty p {{
    margin: 0;
    font-size: 0.92rem;
    color: {_C["muted"]};
    max-width: 28rem;
    margin-inline: auto;
    line-height: 1.5;
}}

/* Шапка списка */
.so-list-head {{
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 1rem;
    margin: 0.5rem 0 1.25rem;
    flex-wrap: wrap;
}}
.so-list-head .count {{
    font-size: 0.82rem;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: {_C["muted"]};
}}
.so-list-head .count b {{
    color: {o};
    font-size: 1.1rem;
    letter-spacing: 0;
    text-transform: none;
}}

/* Карточка в списке */
.so-feed {{
    display: flex;
    flex-direction: column;
    gap: 0.65rem;
}}
div[class*="st-key-so_card_"] {{
    background: #fff !important;
    border: 1px solid {_C["line"]} !important;
    border-radius: 14px !important;
    padding: 0 !important;
    margin: 0 !important;
    box-shadow: 0 1px 2px rgba(26, 29, 38, 0.04) !important;
    transition: border-color 0.2s, box-shadow 0.2s !important;
    overflow: hidden !important;
}}
div[class*="st-key-so_card_"]:hover {{
    border-color: #d4d4d8 !important;
    box-shadow: 0 8px 24px rgba(26, 29, 38, 0.06) !important;
}}
div[class*="st-key-so_card_"] [data-testid="stVerticalBlock"] {{
    gap: 0 !important;
}}
.so-row {{
    display: grid;
    grid-template-columns: 1fr auto auto;
    gap: 1rem 1.5rem;
    align-items: center;
    padding: 1.1rem 1.25rem 0.35rem;
}}
@media (max-width: 720px) {{
    .so-row {{ grid-template-columns: 1fr; }}
}}
.so-row-title {{
    font-size: 1.05rem;
    font-weight: 600;
    color: {_C["ink"]};
    line-height: 1.3;
    margin: 0;
    word-break: break-word;
}}
.so-row-meta {{
    font-size: 0.8rem;
    color: {_C["muted"]};
    margin-top: 0.25rem;
}}
.so-stage {{
    display: inline-block;
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    padding: 0.28rem 0.65rem;
    border-radius: 6px;
    background: {_C["wash"]};
    color: {_C["header"]};
    white-space: nowrap;
}}
.so-stage.is-active {{
    background: rgba(20, 184, 166, 0.14);
    color: #0f766e;
}}
.so-price {{
    font-size: 1.15rem;
    font-weight: 700;
    color: {_C["ink"]};
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
}}
.so-price span {{
    font-size: 0.75rem;
    font-weight: 500;
    color: {_C["muted"]};
}}
div[class*="st-key-so_card_"] .stButton {{
    padding: 0 1.25rem 1rem !important;
}}
div[class*="st-key-so_card_"] .stButton > button {{
    width: 100% !important;
    background: transparent !important;
    border: none !important;
    color: {o} !important;
    font-size: 0.82rem !important;
    font-weight: 600 !important;
    padding: 0.35rem 0 !important;
    justify-content: flex-start !important;
    box-shadow: none !important;
}}
div[class*="st-key-so_card_"] .stButton > button:hover {{
    color: {_C["header"]} !important;
    background: transparent !important;
}}

/* Удаление в карточке списка */
div[class*="st-key-so_card_"] [class*="st-key-sinlex_del_order_"] {{
    display: flex !important;
    justify-content: flex-end !important;
    padding-right: 1rem !important;
    padding-bottom: 0.75rem !important;
}}
.so-card-actions {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 1.25rem 0.85rem;
    gap: 0.75rem;
}}
.so-danger-zone {{
    margin-top: 2.25rem;
    padding: 1rem 1.15rem;
    border: 1px solid #fecaca;
    border-radius: 12px;
    background: #fffbfb;
}}
.so-danger-zone h5 {{
    margin: 0 0 0.35rem;
    font-size: 0.9rem;
    font-weight: 600;
    color: #991b1b;
}}
.so-danger-zone p {{
    margin: 0 0 0.75rem;
    font-size: 0.82rem;
    color: #b91c1c;
    line-height: 1.45;
}}
div[class*="st-key-so_delete_"] {{
    margin-top: 0.95rem !important;
}}
div[class*="st-key-so_delete_"] .stButton > button {{
    background: transparent !important;
    border: 1px solid #fca5a5 !important;
    color: #b91c1c !important;
    font-weight: 600 !important;
}}
div[class*="st-key-so_delete_"] .stButton > button:hover {{
    background: #fef2f2 !important;
    border-color: #f87171 !important;
}}

/* Кнопка «назад» */
div[class*="st-key-so_back_"] .stButton > button {{
    background: transparent !important;
    border: 1px solid {_C["line"]} !important;
    color: {_C["header"]} !important;
    font-size: 0.85rem !important;
    font-weight: 500 !important;
    border-radius: 8px !important;
    padding: 0.35rem 0.85rem !important;
    box-shadow: none !important;
}}
div[class*="st-key-so_back_"] .stButton > button:hover {{
    border-color: #d4d4d8 !important;
    background: {_C["wash"]} !important;
}}

/* —— Деталь заказа —— */
.so-detail-shell {{
    margin-top: 0.25rem;
}}
.so-detail-top {{
    position: relative;
    overflow: hidden;
    margin: 0.2rem 0 1.25rem;
    padding: 1.35rem 1.45rem;
    border: 1px solid #e6e8ec;
    border-radius: 20px;
    background:
        radial-gradient(circle at 88% 12%, rgba(20,184,166,0.14), transparent 28%),
        linear-gradient(145deg, #ffffff 0%, #f8fafc 58%, #f1f5f9 100%);
    box-shadow: 0 18px 45px rgba(15, 23, 42, 0.07);
}}
.so-detail-top::before {{
    content: "";
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 5px;
    background: linear-gradient(180deg, {_C["orange"]}, {_C["teal"]});
}}
.so-detail-top-grid {{
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(250px, 0.45fr);
    gap: 1.1rem;
    align-items: end;
    position: relative;
    z-index: 1;
}}
@media (max-width: 820px) {{
    .so-detail-top-grid {{ grid-template-columns: 1fr; align-items: start; }}
}}
.so-detail-eyebrow {{
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    font-size: 0.68rem;
    font-weight: 800;
    letter-spacing: 0.13em;
    text-transform: uppercase;
    color: #94a3b8;
    margin-bottom: 0.55rem;
}}
.so-detail-eyebrow::before {{
    content: "";
    width: 0.45rem;
    height: 0.45rem;
    border-radius: 999px;
    background: {_C["teal"]};
    box-shadow: 0 0 0 4px rgba(20, 184, 166, 0.12);
}}
.so-detail-title {{
    margin: 0;
    font-size: clamp(1.55rem, 3vw, 2.15rem);
    font-weight: 800;
    color: {_C["ink"]};
    line-height: 1.1;
    letter-spacing: -0.045em;
}}
.so-detail-sub {{
    margin: 0.65rem 0 0;
    font-size: 0.9rem;
    color: {_C["muted"]};
    line-height: 1.55;
    max-width: 42rem;
}}
.so-detail-kpis {{
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.55rem;
}}
.so-detail-kpi {{
    min-height: 4.9rem;
    padding: 0.85rem 0.9rem;
    border: 1px solid #e5e7eb;
    border-radius: 14px;
    background: rgba(255,255,255,0.78);
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}}
.so-detail-kpi .k {{
    margin: 0 0 0.35rem;
    color: #94a3b8;
    font-size: 0.66rem;
    font-weight: 800;
    letter-spacing: 0.1em;
    text-transform: uppercase;
}}
.so-detail-kpi .v {{
    margin: 0;
    color: {_C["ink"]};
    font-size: 1.05rem;
    font-weight: 800;
    letter-spacing: -0.025em;
    line-height: 1.15;
}}
.so-detail-kpi .v.teal {{ color: {_C["teal_dark"]}; }}

/* Выбор скина статуса производства */
div[class*="st-key-so_flow_skin_"] {{
    margin: 0.3rem 0 0.75rem !important;
    max-width: 24rem;
}}
div[class*="st-key-so_flow_skin_"] label {{
    color: #64748b !important;
    font-size: 0.74rem !important;
    font-weight: 760 !important;
}}

/* База статус-трекера */
.so-flow-status {{
    margin: 0 0 1.35rem;
    padding: 1.15rem 1.25rem 1.05rem;
    position: relative;
    overflow: hidden;
}}
.so-flow-head {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; flex-wrap: wrap; margin-bottom: 0.65rem; position: relative; z-index: 1; }}
.so-flow-title {{ line-height: 1.25; }}
.so-flow-badge {{ display: inline-flex; align-items: center; }}
.so-flow-meta {{ margin: 0 0 1rem; line-height: 1.45; position: relative; z-index: 1; }}
.so-flow-meta b {{ font-variant-numeric: tabular-nums; }}
.so-flow-rail {{ position: relative; margin: 0; padding: 1.08rem 0 0; z-index: 1; }}
.so-flow-bar {{ overflow: hidden; position: relative; }}
.so-flow-bar-fill {{ height: 100%; position: relative; min-width: 0.55rem; }}
.so-flow-nodes {{ display: flex; justify-content: space-between; position: absolute; left: 0; right: 0; top: 0.75rem; pointer-events: none; }}
.so-flow-node {{ display: flex; align-items: center; justify-content: center; font-variant-numeric: tabular-nums; }}
.so-flow-labels {{ display: flex; justify-content: space-between; gap: 0.45rem; margin-top: 0.78rem; position: relative; z-index: 1; }}
.so-flow-label {{ flex: 1; text-align: center; line-height: 1.25; min-width: 0; }}

/* Flip status card */
.so-flow-flip {{
    display: block;
    width: 100%;
    margin: 0 0 1.35rem;
    padding: 0;
    border: 0;
    background: transparent;
    perspective: 1400px;
    cursor: pointer;
    text-align: inherit;
    position: relative;
    z-index: 30;
    isolation: isolate;
}}
.so-flow-flip-summary {{
    display: block;
    list-style: none;
    outline: none;
}}
.so-flow-flip-summary::-webkit-details-marker {{ display: none; }}
.so-flow-flip-summary::marker {{ content: ""; }}
.so-flow-flip-inner {{
    display: block;
    position: relative;
    transform-style: preserve-3d;
    transition: transform 0.65s cubic-bezier(.2,.72,.22,1);
}}
.so-flow-flip[open] {{ z-index: 2000; }}
.so-flow-flip[open] .so-flow-flip-inner {{ transform: rotateY(180deg); }}
.so-flow-flip-face {{
    display: block;
    width: 100%;
    backface-visibility: hidden;
    transform-style: preserve-3d;
}}
.so-flow-flip-back {{
    position: absolute;
    inset: 0;
    transform: rotateY(180deg);
    z-index: 5;
}}
.so-flow-flip .so-flow-status {{ margin: 0; min-height: 13.8rem; }}
.so-flow-status-hint {{
    position: absolute;
    right: 1rem;
    bottom: 0.72rem;
    z-index: 2;
    color: currentColor;
    opacity: 0.48;
    font-size: 0.66rem;
    font-weight: 700;
}}
.so-flow-back-body {{ position: relative; z-index: 2; display: grid; gap: 0.78rem; }}
.so-flow-back-eyebrow {{ margin: 0; opacity: 0.68; font-size: 0.7rem; font-weight: 850; letter-spacing: 0.1em; text-transform: uppercase; }}
.so-flow-back-title {{ margin: 0; font-size: 1.12rem; line-height: 1.2; font-weight: 850; }}
.so-flow-back-text {{ margin: 0; font-size: 0.84rem; line-height: 1.55; max-width: 58rem; }}
.so-flow-back-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.65rem; }}
.so-flow-back-metric {{ padding: 0.72rem 0.78rem; border-radius: 12px; background: rgba(255,255,255,0.14); border: 1px solid rgba(148,163,184,0.20); }}
.so-flow-back-metric .k {{ margin: 0 0 0.22rem; opacity: 0.70; font-size: 0.66rem; font-weight: 780; text-transform: uppercase; letter-spacing: 0.06em; }}
.so-flow-back-metric .v {{ margin: 0; font-size: 0.92rem; font-weight: 850; }}
.so-flow-back-action {{ margin: 0; opacity: 0.66; font-size: 0.72rem; font-weight: 700; }}
@media (max-width: 720px) {{
    .so-flow-flip .so-flow-status {{ min-height: 17rem; }}
    .so-flow-back-grid {{ grid-template-columns: 1fr; }}
}}

.so-detail-shell, .so-flow-flip, .so-layout {{ position: relative; }}
.so-layout {{ z-index: 1; }}
.so-flow-flip {{ z-index: 30; }}
.so-flow-flip[open] {{ z-index: 2000; }}
/* Skin: SAP/Fiori */
.so-flow-skin-sap {{
    border-radius: 0.75rem;
    border: 1px solid #d9e1e8;
    background: #ffffff;
    box-shadow: 0 0.5rem 1.5rem rgba(34, 53, 72, 0.08);
}}
.so-flow-skin-sap::before {{ content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 0.25rem; background: #0a6ed1; }}
.so-flow-skin-sap .so-flow-title {{ color: #223548; font-size: 1rem; font-weight: 700; }}
.so-flow-skin-sap .so-flow-title::after {{ content: "Маршрут заказа"; display: block; margin-top: 0.18rem; color: #6a7d90; font-size: 0.75rem; font-weight: 400; }}
.so-flow-skin-sap .so-flow-badge {{ min-height: 1.75rem; padding: 0 0.65rem; border-radius: 0.375rem; border: 1px solid #b8d7f5; background: #ebf5fe; color: #0a6ed1; font-size: 0.78rem; font-weight: 700; }}
.so-flow-skin-sap .so-flow-meta {{ color: #556b82; font-size: 0.82rem; }}
.so-flow-skin-sap .so-flow-meta b {{ color: #223548; font-weight: 700; }}
.so-flow-skin-sap .so-flow-bar {{ height: 0.375rem; border-radius: 999px; background: #e5eaef; }}
.so-flow-skin-sap .so-flow-bar-fill {{ border-radius: 999px; background: #0a6ed1; transition: width 0.35s ease; }}
.so-flow-skin-sap .so-flow-node {{ width: 1.35rem; height: 1.35rem; border-radius: 999px; background: #fff; border: 2px solid #c6d0da; color: #6a7d90; font-size: 0.62rem; font-weight: 700; box-shadow: 0 0 0 3px #fff; }}
.so-flow-skin-sap .so-flow-node.done {{ border-color: #107e3e; background: #107e3e; color: #fff; }}
.so-flow-skin-sap .so-flow-node.current {{ border-color: #0a6ed1; color: #0a6ed1; transform: translateY(-1px) scale(1.04); box-shadow: 0 0 0 4px #fff, 0 0 0 7px rgba(10,110,209,0.14); }}
.so-flow-skin-sap .so-flow-label {{ color: #6a7d90; font-size: 0.68rem; font-weight: 400; }}
.so-flow-skin-sap .so-flow-label.done {{ color: #107e3e; font-weight: 600; }}
.so-flow-skin-sap .so-flow-label.current {{ color: #0a6ed1; font-weight: 700; }}

/* Skin: SSH terminal */
.so-flow-skin-ssh {{
    border-radius: 12px;
    border: 1px solid #1f2937;
    background: radial-gradient(circle at 12% 0%, rgba(34,197,94,0.12), transparent 34%), linear-gradient(180deg, #0b1120 0%, #020617 100%);
    box-shadow: 0 22px 46px rgba(2,6,23,0.28), inset 0 1px 0 rgba(255,255,255,0.05);
    font-family: "SFMono-Regular", "Consolas", "Liberation Mono", "Courier New", monospace;
}}
.so-flow-skin-ssh::before {{ content: "ssh sinlex@production-order --watch"; display: block; margin: -1.15rem -1.25rem 1rem; padding: 0.62rem 1rem; color: #94a3b8; font-size: 0.72rem; line-height: 1; border-bottom: 1px solid rgba(148,163,184,0.18); background: linear-gradient(180deg,#111827 0%,#0f172a 100%); }}
.so-flow-skin-ssh::after {{ content: ""; position: absolute; inset: 0; pointer-events: none; background: repeating-linear-gradient(180deg, transparent 0 6px, rgba(34,197,94,0.025) 6px 7px); }}
.so-flow-skin-ssh .so-flow-title {{ color: #e5e7eb; font-size: 0.92rem; font-weight: 750; }}
.so-flow-skin-ssh .so-flow-title::before {{ content: "$ "; color: #22c55e; }}
.so-flow-skin-ssh .so-flow-title::after {{ content: "./production_status --order --live"; display: block; margin-top: 0.28rem; color: #64748b; font-size: 0.72rem; font-weight: 500; }}
.so-flow-skin-ssh .so-flow-badge {{ min-height: 1.75rem; padding: 0 0.7rem; border-radius: 7px; border: 1px solid rgba(34,197,94,0.35); background: rgba(22,101,52,0.22); color: #86efac; font-size: 0.76rem; font-weight: 750; }}
.so-flow-skin-ssh .so-flow-meta {{ color: #94a3b8; font-size: 0.78rem; }}
.so-flow-skin-ssh .so-flow-meta::before {{ content: "> "; color: #22c55e; }}
.so-flow-skin-ssh .so-flow-meta b {{ color: #bbf7d0; font-weight: 800; }}
.so-flow-skin-ssh .so-flow-bar {{ height: 0.85rem; border-radius: 6px; border: 1px solid rgba(148,163,184,0.25); background: #020617; box-shadow: inset 0 1px 4px rgba(0,0,0,0.7); }}
.so-flow-skin-ssh .so-flow-bar::before {{ content: ""; position: absolute; inset: 0; background: repeating-linear-gradient(90deg, transparent 0 18px, rgba(148,163,184,0.13) 18px 19px); pointer-events: none; }}
.so-flow-skin-ssh .so-flow-bar-fill {{ border-radius: 5px; background: repeating-linear-gradient(90deg, rgba(187,247,208,0.18) 0 10px, transparent 10px 12px), linear-gradient(90deg,#15803d 0%,#22c55e 100%); transition: width 0.35s ease; box-shadow: 0 0 18px rgba(34,197,94,0.30); }}
.so-flow-skin-ssh .so-flow-node {{ width: 1.35rem; height: 1.35rem; border-radius: 6px; background: #020617; border: 1px solid rgba(148,163,184,0.42); color: #64748b; font-size: 0.62rem; font-weight: 800; box-shadow: 0 0 0 3px #020617; }}
.so-flow-skin-ssh .so-flow-node.done {{ border-color: rgba(34,197,94,0.7); background: #14532d; color: #bbf7d0; }}
.so-flow-skin-ssh .so-flow-node.current {{ border-color: #22c55e; background: #052e16; color: #dcfce7; transform: translateY(-1px); box-shadow: 0 0 0 3px #020617, 0 0 18px rgba(34,197,94,0.34); }}
.so-flow-skin-ssh .so-flow-label {{ color: #64748b; font-size: 0.62rem; font-weight: 650; }}
.so-flow-skin-ssh .so-flow-label.done {{ color: #86efac; }}
.so-flow-skin-ssh .so-flow-label.current {{ color: #dcfce7; text-shadow: 0 0 10px rgba(34,197,94,0.40); }}

/* Skin: Norton Commander */
.so-flow-skin-norton {{
    border-radius: 0;
    border: 2px solid #9be7ff;
    background: #001a8d;
    box-shadow: 0 0 0 2px #00004f, 0 16px 34px rgba(0,0,79,0.28), inset 0 0 0 1px #00a7d8;
    font-family: "Courier New", "Lucida Console", monospace;
}}
.so-flow-skin-norton::before {{ content: " SINLEX:/ORDERS/PRODUCTION.STATUS "; position: absolute; left: 0.85rem; top: -0.62rem; padding: 0 0.35rem; background: #001a8d; color: #ffff54; font-size: 0.68rem; font-weight: 800; }}
.so-flow-skin-norton::after {{ content: "F3 View   F5 Copy   F7 Mkdir   F10 Quit"; display: block; margin: 0.92rem -1.15rem -1rem; padding: 0.32rem 0.9rem; background: #00a7d8; color: #00004f; font-size: 0.68rem; line-height: 1; font-weight: 900; white-space: nowrap; overflow: hidden; }}
.so-flow-skin-norton .so-flow-title {{ color: #fff; font-size: 0.94rem; font-weight: 900; letter-spacing: 0.02em; text-transform: uppercase; }}
.so-flow-skin-norton .so-flow-title::before {{ content: "C:\PROD> "; color: #ffff54; }}
.so-flow-skin-norton .so-flow-title::after {{ content: "TRACK_ORDER.EXE /LIVE"; display: block; margin-top: 0.22rem; color: #9be7ff; font-size: 0.7rem; font-weight: 800; }}
.so-flow-skin-norton .so-flow-badge {{ min-height: 1.65rem; padding: 0 0.62rem; border-radius: 0; border: 1px solid #fff; background: #00a7d8; color: #00004f; font-size: 0.74rem; font-weight: 900; box-shadow: 2px 2px 0 #00004f; }}
.so-flow-skin-norton .so-flow-meta {{ color: #9be7ff; font-size: 0.78rem; font-weight: 800; }}
.so-flow-skin-norton .so-flow-meta::before {{ content: "INFO: "; color: #ffff54; }}
.so-flow-skin-norton .so-flow-meta b {{ color: #ffff54; font-weight: 900; }}
.so-flow-skin-norton .so-flow-bar {{ height: 1rem; border-radius: 0; border: 1px solid #9be7ff; background: repeating-linear-gradient(90deg,#00004f 0 14px,#001a8d 14px 16px); box-shadow: inset 0 0 0 1px #00004f; }}
.so-flow-skin-norton .so-flow-bar-fill {{ border-radius: 0; background: repeating-linear-gradient(90deg,#ffff54 0 12px,#ffd400 12px 14px); transition: width 0.35s steps(12,end); min-width: 10px; }}
.so-flow-skin-norton .so-flow-node {{ width: 1.46rem; height: 1.46rem; border-radius: 0; background: #001a8d; border: 1px solid #9be7ff; color: #9be7ff; font-size: 0.62rem; font-weight: 900; box-shadow: 2px 2px 0 #00004f; }}
.so-flow-skin-norton .so-flow-node.done {{ background: #00a7d8; color: #00004f; border-color: #fff; }}
.so-flow-skin-norton .so-flow-node.current {{ background: #ffff54; color: #00004f; border-color: #fff; transform: translateY(-2px); box-shadow: 3px 3px 0 #00004f; }}
.so-flow-skin-norton .so-flow-label {{ color: #9be7ff; font-size: 0.6rem; font-weight: 800; text-transform: uppercase; }}
.so-flow-skin-norton .so-flow-label.done {{ color: #fff; }}
.so-flow-skin-norton .so-flow-label.current {{ color: #ffff54; background: #00004f; }}

/* Skin: 8-bit УВР */
.so-flow-skin-tva {{
    border-radius: 4px;
    border: 3px solid #2a2118;
    background:
        linear-gradient(90deg, rgba(255, 199, 88, 0.04) 1px, transparent 1px),
        linear-gradient(0deg, rgba(255, 199, 88, 0.035) 1px, transparent 1px),
        linear-gradient(180deg, #2a2118 0%, #15100c 100%);
    background-size: 14px 14px, 14px 14px, auto;
    box-shadow:
        0 12px 0 rgba(42, 33, 24, 0.22),
        0 22px 42px rgba(42, 33, 24, 0.28),
        inset 0 2px 0 rgba(255, 230, 168, 0.12),
        inset 0 -4px 0 rgba(0,0,0,0.35);
    font-family: "Courier New", monospace;
}}
.so-flow-skin-tva::before {{
    content: "УВР // ДЕЛО ЗАКАЗА";
    position: absolute;
    right: 1rem;
    top: 0.78rem;
    color: rgba(255, 199, 88, 0.30);
    font-size: 0.62rem;
    font-weight: 900;
    letter-spacing: 0.14em;
}}
.so-flow-skin-tva::after {{
    content: "";
    position: absolute;
    inset: 0;
    background:
        repeating-linear-gradient(180deg, transparent 0 5px, rgba(255, 199, 88, 0.035) 5px 6px),
        radial-gradient(circle at 12% 8%, rgba(255, 199, 88, 0.10), transparent 28%);
    pointer-events: none;
}}
.so-flow-skin-tva .so-flow-title {{ color: #ffe6a8; font-size: 0.98rem; font-weight: 900; letter-spacing: 0.06em; text-transform: uppercase; text-shadow: 0 0 10px rgba(255,199,88,0.32); }}
.so-flow-skin-tva .so-flow-title::after {{ content: "Архив временного маршрута"; display: block; margin-top: 0.22rem; color: #b88945; font-size: 0.68rem; font-weight: 800; letter-spacing: 0.04em; }}
.so-flow-skin-tva .so-flow-badge {{ min-height: 1.82rem; padding: 0 0.72rem; border-radius: 2px; border: 2px solid #ffc758; background: linear-gradient(180deg, #3b2a1a 0%, #1f1710 100%); color: #ffc758; font-size: 0.74rem; font-weight: 900; box-shadow: inset 2px 2px 0 rgba(255,230,168,0.10), 4px 4px 0 rgba(0,0,0,0.24); }}
.so-flow-skin-tva .so-flow-meta {{ color: #caa05d; font-size: 0.78rem; font-weight: 800; }}
.so-flow-skin-tva .so-flow-meta::before {{ content: "LOG: "; color: #ffc758; }}
.so-flow-skin-tva .so-flow-meta b {{ color: #ffe6a8; font-weight: 900; }}
.so-flow-skin-tva .so-flow-bar {{ height: 1rem; border-radius: 2px; border: 2px solid #ffc758; background: repeating-linear-gradient(90deg, #15100c 0 14px, #241a12 14px 16px); box-shadow: inset 0 2px 0 rgba(255,230,168,0.08), 0 0 16px rgba(255,199,88,0.14); image-rendering: pixelated; }}
.so-flow-skin-tva .so-flow-bar-fill {{ border-radius: 0; background: repeating-linear-gradient(90deg, rgba(21,16,12,0.32) 0 2px, transparent 2px 10px), linear-gradient(180deg, #ffe6a8 0%, #ffc758 48%, #b86b24 100%); transition: width 0.36s steps(12,end); min-width: 10px; image-rendering: pixelated; box-shadow: 0 0 14px rgba(255,199,88,0.32); }}
.so-flow-skin-tva .so-flow-node {{ width: 1.45rem; height: 1.45rem; border-radius: 2px; background: #15100c; border: 2px solid #7f5a2d; color: #9b7541; font-size: 0.6rem; font-weight: 900; box-shadow: 3px 3px 0 rgba(0,0,0,0.28); }}
.so-flow-skin-tva .so-flow-node.done {{ background: #7f5a2d; border-color: #ffc758; color: #ffe6a8; }}
.so-flow-skin-tva .so-flow-node.current {{ background: #ffc758; border-color: #ffe6a8; color: #15100c; transform: translateY(-2px); box-shadow: 3px 3px 0 rgba(0,0,0,0.30), 0 0 18px rgba(255,199,88,0.38); }}
.so-flow-skin-tva .so-flow-label {{ color: #9b7541; font-size: 0.6rem; font-weight: 800; letter-spacing: 0.03em; text-transform: uppercase; }}
.so-flow-skin-tva .so-flow-label.done {{ color: #caa05d; }}
.so-flow-skin-tva .so-flow-label.current {{ color: #ffe6a8; text-shadow: 0 0 8px rgba(255,199,88,0.36); }}

/* Skin: Sega 16-bit */
.so-flow-skin-sega {{
    border-radius: 0;
    border: 3px solid #ffde59;
    background:
        linear-gradient(90deg, rgba(255,255,255,0.06) 1px, transparent 1px),
        linear-gradient(0deg, rgba(255,255,255,0.05) 1px, transparent 1px),
        linear-gradient(135deg, #15146f 0%, #3b1f8f 45%, #101042 100%);
    background-size: 10px 10px, 10px 10px, auto;
    box-shadow:
        0 0 0 3px #05051f,
        0 18px 36px rgba(5, 5, 31, 0.34),
        inset 0 2px 0 rgba(255,255,255,0.22),
        inset 0 -4px 0 rgba(5,5,31,0.32);
    font-family: "Trebuchet MS", "Arial Black", sans-serif;
}}
.so-flow-skin-sega::before {{
    content: "16-BIT PRODUCTION DRIVE";
    position: absolute;
    right: 1rem;
    top: 0.72rem;
    color: rgba(255, 222, 89, 0.32);
    font-size: 0.64rem;
    font-weight: 900;
    letter-spacing: 0.14em;
}}
.so-flow-skin-sega::after {{
    content: "";
    position: absolute;
    inset: 0;
    background: repeating-linear-gradient(180deg, transparent 0 4px, rgba(0,0,0,0.08) 4px 5px);
    pointer-events: none;
}}
.so-flow-skin-sega .so-flow-title {{ color: #ffffff; font-size: 1rem; font-weight: 900; letter-spacing: 0.02em; text-transform: uppercase; text-shadow: 2px 2px 0 #05051f, 0 0 12px rgba(0, 224, 255, 0.42); }}
.so-flow-skin-sega .so-flow-title::after {{ content: "MEGA PROCESS LINE"; display: block; margin-top: 0.2rem; color: #00e0ff; font-size: 0.68rem; font-weight: 900; letter-spacing: 0.08em; }}
.so-flow-skin-sega .so-flow-badge {{ min-height: 1.78rem; padding: 0 0.72rem; border-radius: 0; border: 2px solid #ffde59; background: linear-gradient(180deg, #ff4fd8 0%, #8d22ff 100%); color: #ffffff; font-size: 0.74rem; font-weight: 900; text-shadow: 1px 1px 0 #05051f; box-shadow: 3px 3px 0 #05051f, inset 1px 1px 0 rgba(255,255,255,0.35); }}
.so-flow-skin-sega .so-flow-meta {{ color: #b8f7ff; font-size: 0.78rem; font-weight: 800; text-shadow: 1px 1px 0 #05051f; }}
.so-flow-skin-sega .so-flow-meta::before {{ content: "RUN: "; color: #ffde59; }}
.so-flow-skin-sega .so-flow-meta b {{ color: #ffde59; font-weight: 900; }}
.so-flow-skin-sega .so-flow-bar {{ height: 1rem; border-radius: 0; border: 2px solid #00e0ff; background: repeating-linear-gradient(90deg,#05051f 0 12px,#15146f 12px 14px); box-shadow: inset 0 2px 0 rgba(255,255,255,0.12), 0 0 16px rgba(0,224,255,0.22); image-rendering: pixelated; }}
.so-flow-skin-sega .so-flow-bar-fill {{ border-radius: 0; background: repeating-linear-gradient(90deg, rgba(5,5,31,0.22) 0 2px, transparent 2px 10px), linear-gradient(90deg,#00e0ff 0%,#35ff69 48%,#ffde59 100%); transition: width 0.34s steps(16,end); min-width: 10px; box-shadow: 0 0 16px rgba(53,255,105,0.35); image-rendering: pixelated; }}
.so-flow-skin-sega .so-flow-node {{ width: 1.48rem; height: 1.48rem; border-radius: 0; background: #15146f; border: 2px solid #00e0ff; color: #00e0ff; font-size: 0.62rem; font-weight: 900; box-shadow: 3px 3px 0 #05051f; }}
.so-flow-skin-sega .so-flow-node.done {{ background: #35ff69; color: #05051f; border-color: #ffffff; }}
.so-flow-skin-sega .so-flow-node.current {{ background: #ffde59; color: #05051f; border-color: #ffffff; transform: translateY(-2px); box-shadow: 3px 3px 0 #05051f, 0 0 18px rgba(255,222,89,0.38); }}
.so-flow-skin-sega .so-flow-label {{ color: #00e0ff; font-size: 0.6rem; font-weight: 900; text-transform: uppercase; text-shadow: 1px 1px 0 #05051f; }}
.so-flow-skin-sega .so-flow-label.done {{ color: #35ff69; }}
.so-flow-skin-sega .so-flow-label.current {{ color: #ffde59; }}

/* Skin: Синлекс */
.so-flow-skin-sinlex {{
    border-radius: 22px;
    border: 1px solid rgba(13, 148, 136, 0.24);
    background:
        radial-gradient(circle at 88% 0%, rgba(20, 184, 166, 0.18), transparent 30%),
        linear-gradient(180deg, #ffffff 0%, #f4f7f8 100%);
    box-shadow: 0 18px 42px rgba(15, 23, 42, 0.09);
    font-family: Inter, "Segoe UI", system-ui, sans-serif;
}}
.so-flow-skin-sinlex::before {{
    content: "SINLEX";
    position: absolute;
    right: 1.25rem;
    top: 0.85rem;
    color: rgba(26, 29, 38, 0.08);
    font-size: 1.35rem;
    font-weight: 900;
    letter-spacing: 0.08em;
}}
.so-flow-skin-sinlex::after {{
    content: "";
    position: absolute;
    left: 1.25rem;
    right: 1.25rem;
    top: 0;
    height: 3px;
    border-radius: 999px;
    background: linear-gradient(90deg, #1a1d26, #0d9488, #14b8a6, transparent);
    pointer-events: none;
}}
.so-flow-skin-sinlex .so-flow-title {{ color: #1a1d26; font-size: 1.04rem; font-weight: 850; letter-spacing: -0.025em; }}
.so-flow-skin-sinlex .so-flow-title::after {{ content: "Контур заказа Sinlex"; display: block; margin-top: 0.2rem; color: #5f6b76; font-size: 0.74rem; font-weight: 560; letter-spacing: 0; }}
.so-flow-skin-sinlex .so-flow-badge {{ min-height: 1.9rem; padding: 0 0.78rem; border-radius: 999px; border: 1px solid rgba(13,148,136,0.28); background: linear-gradient(135deg, rgba(20,184,166,0.16), rgba(26,29,38,0.04)); color: #0f766e; font-size: 0.78rem; font-weight: 800; box-shadow: 0 8px 18px rgba(13,148,136,0.10); }}
.so-flow-skin-sinlex .so-flow-meta {{ color: #64748b; font-size: 0.82rem; font-weight: 560; }}
.so-flow-skin-sinlex .so-flow-meta b {{ color: #1a1d26; font-weight: 850; }}
.so-flow-skin-sinlex .so-flow-bar {{ height: 0.68rem; border-radius: 999px; background: #e4eaec; box-shadow: inset 0 1px 2px rgba(15,23,42,0.08); }}
.so-flow-skin-sinlex .so-flow-bar-fill {{ border-radius: 999px; background: linear-gradient(90deg, #1a1d26 0%, #595957 42%, #0d9488 78%, #14b8a6 100%); transition: width 0.42s ease; min-width: 0.7rem; box-shadow: 0 0 16px rgba(20,184,166,0.20); }}
.so-flow-skin-sinlex .so-flow-node {{ width: 1.42rem; height: 1.42rem; border-radius: 999px; background: #ffffff; border: 2px solid #cbd5e1; color: #94a3b8; font-size: 0.62rem; font-weight: 800; box-shadow: 0 0 0 4px #ffffff, 0 6px 14px rgba(15,23,42,0.08); }}
.so-flow-skin-sinlex .so-flow-node.done {{ background: #595957; border-color: #595957; color: #ffffff; }}
.so-flow-skin-sinlex .so-flow-node.current {{ background: #14b8a6; border-color: #0d9488; color: #ffffff; transform: translateY(-2px); box-shadow: 0 0 0 4px #ccfbf1, 0 10px 22px rgba(20,184,166,0.28); }}
.so-flow-skin-sinlex .so-flow-label {{ color: #94a3b8; font-size: 0.68rem; font-weight: 600; }}
.so-flow-skin-sinlex .so-flow-label.done {{ color: #595957; font-weight: 700; }}
.so-flow-skin-sinlex .so-flow-label.current {{ color: #0f766e; font-weight: 800; }}

/* Skin: Windows 95 */
.so-flow-skin-win95 {{
    border-radius: 0;
    border-width: 2px;
    border-style: solid;
    border-color: #ffffff #808080 #808080 #ffffff;
    background: #c0c0c0;
    box-shadow: 0 0 0 1px #000000, 0 16px 34px rgba(15,23,42,0.18);
    font-family: "MS Sans Serif", Tahoma, Arial, sans-serif;
}}
.so-flow-skin-win95::before {{
    content: "Production Status - Sinlex";
    display: block;
    margin: -1.15rem -1.25rem 0.9rem;
    padding: 0.32rem 0.55rem;
    color: #ffffff;
    font-size: 0.76rem;
    font-weight: 700;
    line-height: 1.05;
    background: linear-gradient(90deg, #000080 0%, #1084d0 100%);
}}
.so-flow-skin-win95 .so-flow-title {{ color: #000000; font-size: 0.92rem; font-weight: 700; letter-spacing: 0; }}
.so-flow-skin-win95 .so-flow-title::after {{ content: "Order process monitor"; display: block; margin-top: 0.18rem; color: #404040; font-size: 0.7rem; font-weight: 400; }}
.so-flow-skin-win95 .so-flow-badge {{ min-height: 1.65rem; padding: 0 0.62rem; border-radius: 0; border-width: 2px; border-style: solid; border-color: #808080 #ffffff #ffffff #808080; background: #c0c0c0; color: #000000; font-size: 0.74rem; font-weight: 700; }}
.so-flow-skin-win95 .so-flow-meta {{ color: #000000; font-size: 0.78rem; font-weight: 400; }}
.so-flow-skin-win95 .so-flow-meta b {{ color: #000080; font-weight: 700; }}
.so-flow-skin-win95 .so-flow-bar {{ height: 1rem; border-radius: 0; border-width: 2px; border-style: solid; border-color: #808080 #ffffff #ffffff #808080; background: #ffffff; }}
.so-flow-skin-win95 .so-flow-bar-fill {{ border-radius: 0; background: repeating-linear-gradient(90deg, #000080 0 10px, #1084d0 10px 12px); transition: width 0.35s steps(12,end); min-width: 10px; }}
.so-flow-skin-win95 .so-flow-node {{ width: 1.4rem; height: 1.4rem; border-radius: 0; background: #c0c0c0; border-width: 2px; border-style: solid; border-color: #ffffff #808080 #808080 #ffffff; color: #000000; font-size: 0.62rem; font-weight: 700; }}
.so-flow-skin-win95 .so-flow-node.done {{ background: #000080; color: #ffffff; border-color: #ffffff #404040 #404040 #ffffff; }}
.so-flow-skin-win95 .so-flow-node.current {{ background: #ffff00; color: #000000; border-color: #ffffff #808080 #808080 #ffffff; transform: translateY(-2px); }}
.so-flow-skin-win95 .so-flow-label {{ color: #404040; font-size: 0.6rem; font-weight: 400; }}
.so-flow-skin-win95 .so-flow-label.done {{ color: #000080; font-weight: 700; }}
.so-flow-skin-win95 .so-flow-label.current {{ color: #000000; background: #ffff00; font-weight: 700; }}

/* Skin: Windows XP */
.so-flow-skin-winxp {{
    border-radius: 10px;
    border: 1px solid #1f5fd0;
    background:
        linear-gradient(180deg, #f7fbff 0%, #dbeafe 100%);
    box-shadow: 0 18px 38px rgba(30, 64, 175, 0.18), inset 0 1px 0 rgba(255,255,255,0.95);
    font-family: Tahoma, "Segoe UI", Arial, sans-serif;
}}
.so-flow-skin-winxp::before {{
    content: "Production Status - Sinlex";
    display: block;
    margin: -1.15rem -1.25rem 0.9rem;
    padding: 0.42rem 0.72rem;
    color: #ffffff;
    font-size: 0.78rem;
    font-weight: 700;
    line-height: 1.05;
    border-radius: 9px 9px 0 0;
    background: linear-gradient(180deg, #6aa7ff 0%, #1f5fd0 48%, #0b3fa5 100%);
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.55), inset 0 -1px 0 rgba(0,0,0,0.20);
}}
.so-flow-skin-winxp .so-flow-title {{ color: #0f2f7a; font-size: 0.98rem; font-weight: 700; letter-spacing: -0.01em; }}
.so-flow-skin-winxp .so-flow-title::after {{ content: "Order process monitor"; display: block; margin-top: 0.18rem; color: #456184; font-size: 0.72rem; font-weight: 400; }}
.so-flow-skin-winxp .so-flow-badge {{ min-height: 1.78rem; padding: 0 0.72rem; border-radius: 12px; border: 1px solid #7fb35b; background: linear-gradient(180deg, #e9ffd8 0%, #9dd36d 48%, #5da130 100%); color: #143c06; font-size: 0.76rem; font-weight: 700; box-shadow: inset 0 1px 0 rgba(255,255,255,0.72), 0 8px 18px rgba(93,161,48,0.18); }}
.so-flow-skin-winxp .so-flow-meta {{ color: #334155; font-size: 0.8rem; font-weight: 400; }}
.so-flow-skin-winxp .so-flow-meta b {{ color: #0b3fa5; font-weight: 700; }}
.so-flow-skin-winxp .so-flow-bar {{ height: 0.95rem; border-radius: 999px; border: 1px solid #8aa7d8; background: linear-gradient(180deg, #ffffff 0%, #c8d8f0 100%); box-shadow: inset 0 1px 2px rgba(15,23,42,0.18); }}
.so-flow-skin-winxp .so-flow-bar-fill {{ border-radius: 999px; background: repeating-linear-gradient(90deg, rgba(255,255,255,0.28) 0 10px, transparent 10px 12px), linear-gradient(180deg, #a8e67b 0%, #56b531 48%, #2f7d16 100%); transition: width 0.38s ease; min-width: 0.8rem; box-shadow: inset 0 1px 0 rgba(255,255,255,0.6); }}
.so-flow-skin-winxp .so-flow-node {{ width: 1.42rem; height: 1.42rem; border-radius: 999px; background: linear-gradient(180deg, #ffffff 0%, #dbeafe 100%); border: 1px solid #7fa2dc; color: #30548c; font-size: 0.62rem; font-weight: 700; box-shadow: 0 0 0 4px #eef6ff, 0 4px 10px rgba(30,64,175,0.14); }}
.so-flow-skin-winxp .so-flow-node.done {{ background: linear-gradient(180deg, #9de174 0%, #4da52c 100%); border-color: #2f7d16; color: #ffffff; }}
.so-flow-skin-winxp .so-flow-node.current {{ background: linear-gradient(180deg, #fff6b8 0%, #f6c343 100%); border-color: #d08b00; color: #5c3b00; transform: translateY(-2px); box-shadow: 0 0 0 4px #fff7d1, 0 10px 20px rgba(208,139,0,0.22); }}
.so-flow-skin-winxp .so-flow-label {{ color: #456184; font-size: 0.64rem; font-weight: 400; }}
.so-flow-skin-winxp .so-flow-label.done {{ color: #2f7d16; font-weight: 700; }}
.so-flow-skin-winxp .so-flow-label.current {{ color: #0b3fa5; font-weight: 700; }}

/* Небольшой мигающий индикатор статуса по скинам */
.so-flow-badge::before {{
    content: "";
    display: inline-block;
    margin-right: 0.42rem;
    flex: 0 0 auto;
}}
@keyframes so-flow-status-dot {{
    0%, 48% {{ opacity: 1; }}
    49%, 100% {{ opacity: 0.25; }}
}}
.so-flow-skin-sap .so-flow-badge::before {{
    width: 0.48rem;
    height: 0.48rem;
    border-radius: 999px;
    background: #0a6ed1;
    animation: so-flow-status-dot 1.35s ease-in-out infinite;
}}
.so-flow-skin-ssh .so-flow-badge::before {{
    content: "▌";
    width: auto;
    height: auto;
    margin-right: 0.36rem;
    color: #22c55e;
    animation: so-flow-status-dot 1s steps(1,end) infinite;
}}
.so-flow-skin-norton .so-flow-badge::before {{
    content: "■";
    width: auto;
    height: auto;
    margin-right: 0.34rem;
    color: #ffff54;
    animation: so-flow-status-dot 1s steps(1,end) infinite;
}}
.so-flow-skin-tva .so-flow-badge::before {{
    width: 0.5rem;
    height: 0.5rem;
    border-radius: 2px;
    background: #ffc758;
    box-shadow: 0 0 10px rgba(255,199,88,0.62), 2px 2px 0 rgba(0,0,0,0.28);
    animation: so-flow-status-dot 1.1s steps(1,end) infinite;
}}
.so-flow-skin-sega .so-flow-badge::before {{
    width: 0.52rem;
    height: 0.52rem;
    border-radius: 0;
    background: #35ff69;
    box-shadow: 0 0 10px rgba(53,255,105,0.75), 2px 2px 0 #05051f;
    animation: so-flow-status-dot 0.9s steps(1,end) infinite;
}}
.so-flow-skin-sinlex .so-flow-badge::before {{
    width: 0.5rem;
    height: 0.5rem;
    border-radius: 999px;
    background: #14b8a6;
    box-shadow: 0 0 0 4px rgba(20,184,166,0.12), 0 0 14px rgba(20,184,166,0.52);
    animation: so-flow-status-dot 1.2s ease-in-out infinite;
}}
.so-flow-skin-win95 .so-flow-badge::before {{
    width: 0.48rem;
    height: 0.48rem;
    border-radius: 0;
    background: #008000;
    border: 1px solid #004000;
    animation: so-flow-status-dot 1s steps(1,end) infinite;
}}
.so-flow-skin-winxp .so-flow-badge::before {{
    width: 0.5rem;
    height: 0.5rem;
    border-radius: 999px;
    background: #34c924;
    box-shadow: 0 0 0 3px rgba(52,201,36,0.16), 0 0 10px rgba(52,201,36,0.50);
    animation: so-flow-status-dot 1.15s ease-in-out infinite;
}}

.so-flow-skin-sap .so-flow-back-title, .so-flow-skin-sap .so-flow-back-text, .so-flow-skin-sap .so-flow-back-metric .v {{ color: #223548; }}
.so-flow-skin-sap .so-flow-back-eyebrow, .so-flow-skin-sap .so-flow-back-action, .so-flow-skin-sap .so-flow-back-metric .k {{ color: #556b82; }}
.so-flow-skin-win95 .so-flow-back-title, .so-flow-skin-win95 .so-flow-back-text, .so-flow-skin-win95 .so-flow-back-metric .v {{ color: #000000; }}
.so-flow-skin-win95 .so-flow-back-eyebrow, .so-flow-skin-win95 .so-flow-back-action, .so-flow-skin-win95 .so-flow-back-metric .k {{ color: #404040; }}
.so-flow-skin-winxp .so-flow-back-title, .so-flow-skin-winxp .so-flow-back-text, .so-flow-skin-winxp .so-flow-back-metric .v {{ color: #0f2f7a; }}
.so-flow-skin-winxp .so-flow-back-eyebrow, .so-flow-skin-winxp .so-flow-back-action, .so-flow-skin-winxp .so-flow-back-metric .k {{ color: #456184; }}
.so-flow-skin-sinlex .so-flow-back-title, .so-flow-skin-sinlex .so-flow-back-text, .so-flow-skin-sinlex .so-flow-back-metric .v {{ color: #1a1d26; }}
.so-flow-skin-sinlex .so-flow-back-eyebrow, .so-flow-skin-sinlex .so-flow-back-action, .so-flow-skin-sinlex .so-flow-back-metric .k {{ color: #64748b; }}
.so-flow-skin-ssh .so-flow-back-title, .so-flow-skin-ssh .so-flow-back-text, .so-flow-skin-ssh .so-flow-back-metric .v {{ color: #dcfce7; }}
.so-flow-skin-ssh .so-flow-back-eyebrow, .so-flow-skin-ssh .so-flow-back-action, .so-flow-skin-ssh .so-flow-back-metric .k {{ color: #94a3b8; }}
.so-flow-skin-norton .so-flow-back-title, .so-flow-skin-norton .so-flow-back-text, .so-flow-skin-norton .so-flow-back-metric .v {{ color: #ffffff; }}
.so-flow-skin-norton .so-flow-back-eyebrow, .so-flow-skin-norton .so-flow-back-action, .so-flow-skin-norton .so-flow-back-metric .k {{ color: #9be7ff; }}
.so-flow-skin-tva .so-flow-back-title, .so-flow-skin-tva .so-flow-back-text, .so-flow-skin-tva .so-flow-back-metric .v {{ color: #ffe6a8; }}
.so-flow-skin-tva .so-flow-back-eyebrow, .so-flow-skin-tva .so-flow-back-action, .so-flow-skin-tva .so-flow-back-metric .k {{ color: #caa05d; }}
.so-flow-skin-sega .so-flow-back-title, .so-flow-skin-sega .so-flow-back-text, .so-flow-skin-sega .so-flow-back-metric .v {{ color: #ffffff; }}
.so-flow-skin-sega .so-flow-back-eyebrow, .so-flow-skin-sega .so-flow-back-action, .so-flow-skin-sega .so-flow-back-metric .k {{ color: #00e0ff; }}

@media (max-width: 720px) {{
    .so-flow-status {{ padding: 1rem; }}
    .so-flow-label {{ font-size: 0.54rem !important; }}
    .so-flow-node {{ width: 1.22rem !important; height: 1.22rem !important; font-size: 0.54rem !important; }}
    .so-flow-skin-norton::after {{ margin-left: -1rem; margin-right: -1rem; font-size: 0.58rem; }}
    .so-flow-skin-tva::before {{ display: none; }}
    .so-flow-skin-sega::before {{ display: none; }}
    .so-flow-skin-sinlex::before {{ display: none; }}
}}

/* Двухколоночный layout */
.so-layout {{
    display: grid;
    grid-template-columns: minmax(0, 1.55fr) minmax(260px, 1fr);
    gap: 1.25rem;
    align-items: start;
}}
@media (max-width: 900px) {{
    .so-layout {{ grid-template-columns: 1fr; }}
}}

.so-panel {{
    background: #fff;
    border: 1px solid #e6e8ec;
    border-radius: 18px;
    overflow: hidden;
    box-shadow: 0 10px 28px rgba(15, 23, 42, 0.045);
}}
.so-panel-h {{
    padding: 0.95rem 1.2rem;
    font-size: 0.68rem;
    font-weight: 800;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #64748b;
    background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
    border-bottom: 1px solid #e6e8ec;
}}
.so-spec {{
    padding: 0.25rem 0;
}}
.so-spec-row {{
    display: grid;
    grid-template-columns: 10rem 1fr;
    gap: 0.95rem;
    padding: 0.82rem 1.2rem;
    border-bottom: 1px solid #f1f5f9;
    font-size: 0.9rem;
    line-height: 1.45;
}}
.so-spec-row:last-child {{ border-bottom: none; }}
.so-spec-row .k {{
    color: {_C["muted"]};
    font-size: 0.82rem;
}}
.so-spec-row .v {{
    color: {_C["ink"]};
    font-weight: 500;
    word-break: break-word;
}}

.so-comment {{
    padding: 1rem 1.15rem;
    font-size: 0.9rem;
    line-height: 1.55;
    color: #374151;
    font-style: italic;
    border-left: 3px solid {o};
    margin: 0;
    background: #fffdfb;
}}

.so-files {{
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    padding: 1rem 1.15rem;
}}
.so-file {{
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 0.75rem;
    background: {_C["wash"]};
    border-radius: 8px;
    border: 1px solid {_C["line"]};
    font-size: 0.82rem;
    color: {_C["ink"]};
}}
.so-file .tag {{
    font-size: 0.62rem;
    font-weight: 800;
    letter-spacing: 0.05em;
    color: #fff;
    background: {o};
    padding: 0.15rem 0.35rem;
    border-radius: 4px;
}}

/* Сайдбар заказа */
.so-aside-total {{
    position: relative;
    overflow: hidden;
    padding: 1.45rem 1.25rem 1.2rem;
    text-align: center;
    border-bottom: 1px solid #0f766e;
    color: #fff;
    background:
        radial-gradient(circle at 84% 18%, rgba(255,255,255,0.18), transparent 30%),
        linear-gradient(145deg, #042f2e 0%, #0f766e 48%, #14b8a6 100%);
}}
.so-aside-total .lbl {{
    font-size: 0.68rem;
    font-weight: 800;
    letter-spacing: 0.13em;
    text-transform: uppercase;
    color: rgba(255,255,255,0.72);
}}
.so-aside-total .sum {{
    font-size: 2.15rem;
    font-weight: 850;
    color: #ffffff;
    letter-spacing: -0.045em;
    margin: 0.3rem 0;
    font-variant-numeric: tabular-nums;
    text-shadow: 0 10px 24px rgba(0,0,0,0.18);
}}
.so-aside-total .hint {{
    font-size: 0.8rem;
    color: rgba(255,255,255,0.78);
}}

.so-aside-block {{
    padding: 1.1rem 1.2rem;
    border-bottom: 1px solid {_C["line"]};
}}
.so-aside-block:last-child {{ border-bottom: none; }}
.so-aside-block h5 {{
    margin: 0 0 0.35rem;
    font-size: 0.95rem;
    font-weight: 600;
    color: {_C["ink"]};
}}
.so-aside-block p {{
    margin: 0 0 0.75rem;
    font-size: 0.82rem;
    color: {_C["muted"]};
    line-height: 1.45;
}}

.so-req-ok {{
    font-size: 0.8rem;
    color: #047857;
    background: #ecfdf5;
    border: 1px solid #a7f3d0;
    border-radius: 8px;
    padding: 0.5rem 0.65rem;
    margin-bottom: 0.65rem;
    line-height: 1.4;
}}

div[class*="st-key-so_aside_panel_"] {{
    background: #fff !important;
    border: 1px solid #e6e8ec !important;
    border-radius: 18px !important;
    padding: 0 0 1rem !important;
    box-shadow: 0 16px 36px rgba(15, 23, 42, 0.07) !important;
    overflow: hidden !important;
}}
div[class*="st-key-so_aside_panel_"] .so-panel {{
    border: none !important;
    box-shadow: none !important;
}}
div[class*="st-key-so_aside_panel_"] [data-testid="stFileUploader"],
div[class*="st-key-so_aside_panel_"] .stButton,
div[class*="st-key-so_aside_panel_"] .stLinkButton {{
    padding: 0 1.15rem !important;
}}
div[class*="st-key-so_aside_panel_"] a {{
    background: linear-gradient(135deg, {o}, #ff9a2e) !important;
    border: none !important;
    font-weight: 600 !important;
}}

div[class*="st-key-so_chat_card_"] {{
    margin-top: 1.35rem !important;
    padding: 0 !important;
    background:
        radial-gradient(circle at 14% 0%, rgba(249, 115, 22, 0.10), transparent 28%),
        linear-gradient(180deg, #ffffff 0%, #f7f8fb 100%) !important;
    border: 1px solid #dfe5ec !important;
    border-radius: 22px !important;
    box-shadow: 0 22px 54px rgba(15, 23, 42, 0.10) !important;
    overflow: hidden !important;
}}
div[class*="st-key-so_chat_card_"] [data-testid="stVerticalBlock"] {{ gap: 0.7rem !important; }}
.so-chat-section {{
    margin: 0;
    background: transparent;
    border: none;
    border-radius: 0;
    overflow: hidden;
}}
.so-chat-section-head {{
    position: relative;
    padding: 1.15rem 1.3rem 1rem 1.35rem;
    border-bottom: 1px solid rgba(226, 232, 240, 0.95);
    background:
        linear-gradient(135deg, #111827 0%, #2f3643 58%, #4a5568 100%);
}}
.so-chat-section-head::after {{
    content: "";
    position: absolute;
    right: 1.3rem;
    top: 1.1rem;
    width: 0.58rem;
    height: 0.58rem;
    border-radius: 999px;
    background: #f59e0b;
    box-shadow: 0 0 0 6px rgba(245, 158, 11, 0.14), 0 0 18px rgba(245, 158, 11, 0.32);
}}
.so-chat-section-head h5 {{
    margin: 0 0 0.28rem;
    color: #ffffff;
    font-size: 1.05rem;
    line-height: 1.15;
    font-weight: 850;
    letter-spacing: -0.02em;
}}
.so-chat-section-head p {{
    margin: 0;
    color: rgba(226, 232, 240, 0.88);
    font-size: 0.83rem;
}}
.so-chat-box {{
    padding: 1.15rem 1.25rem 0.75rem;
    display: flex;
    flex-direction: column-reverse;
    gap: 0.82rem;
    max-height: 390px;
    min-height: 230px;
    overflow-y: auto;
    background:
        linear-gradient(rgba(248, 250, 252, 0.92), rgba(241, 245, 249, 0.96)),
        radial-gradient(circle at 0 0, rgba(249, 115, 22, 0.08), transparent 24%);
    scrollbar-width: thin;
    scrollbar-color: #cbd5e1 transparent;
}}
.so-chat-box::-webkit-scrollbar {{ width: 8px; }}
.so-chat-box::-webkit-scrollbar-thumb {{ background: #cbd5e1; border-radius: 999px; }}
.so-chat-row {{ display: flex; align-items: flex-end; gap: 0.58rem; }}
.so-chat-row.user {{ flex-direction: row-reverse; }}
.so-chat-row.system {{ justify-content: center; }}
.so-chat-avatar {{
    width: 2rem;
    height: 2rem;
    flex: 0 0 2rem;
    border-radius: 999px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 0.72rem;
    font-weight: 850;
    letter-spacing: -0.02em;
    color: #ffffff;
    background: linear-gradient(135deg, #374151, #6b7280);
    box-shadow: 0 8px 18px rgba(55, 65, 81, 0.18);
}}
.so-chat-row.user .so-chat-avatar {{ background: linear-gradient(135deg, #1f2937, #475569); box-shadow: 0 8px 18px rgba(15, 23, 42, 0.18); }}
.so-chat-row.system .so-chat-avatar {{ display: none; }}
.so-chat-msg {{
    position: relative;
    max-width: min(74%, 660px);
    padding: 0.78rem 0.92rem 0.72rem;
    border-radius: 18px;
    border: 1px solid rgba(226, 232, 240, 0.96);
    box-shadow: 0 10px 26px rgba(15, 23, 42, 0.06);
}}
.so-chat-msg.user {{ background: linear-gradient(135deg, #1f2937, #374151); border-color: rgba(31, 41, 55, 0.30); color: #ffffff; border-bottom-right-radius: 7px; }}
.so-chat-msg.manager {{ background: #ffffff; border-color: #e2e8f0; color: #1f2937; border-bottom-left-radius: 7px; }}
.so-chat-msg.system {{ max-width: 100%; background: #f1f5f9; color: #64748b; border-radius: 999px; box-shadow: none; }}
.so-chat-meta {{
    margin: 0 0 0.28rem;
    color: #94a3b8;
    font-size: 0.68rem;
    font-weight: 760;
    letter-spacing: 0.01em;
}}
.so-chat-msg.user .so-chat-meta {{ color: rgba(241, 245, 249, 0.78); }}
.so-chat-text {{ margin: 0; color: inherit; font-size: 0.88rem; line-height: 1.5; white-space: pre-wrap; }}
.so-chat-empty {{
    min-height: 210px;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 1.4rem;
    color: #64748b;
    font-size: 0.86rem;
    line-height: 1.5;
    text-align: center;
    background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
}}
.so-chat-form-note {{ padding: 0.1rem 1.25rem 0; color: #64748b; font-size: 0.76rem; font-weight: 720; }}
div[class*="st-key-so_chat_card_"] div[class*="st-key-order_chat_text_"] {{ padding: 0 1.25rem !important; }}
div[class*="st-key-so_chat_card_"] div[class*="st-key-order_chat_text_"] textarea {{
    min-height: 7rem !important;
    border-radius: 16px !important;
    border: 1px solid #d8e0e8 !important;
    background: #ffffff !important;
    box-shadow: inset 0 1px 2px rgba(15, 23, 42, 0.04) !important;
    font-size: 0.9rem !important;
}}
div[class*="st-key-so_chat_card_"] div[class*="st-key-order_chat_send_"] {{ padding: 0 1.25rem 1.15rem !important; }}
div[class*="st-key-so_chat_card_"] div[class*="st-key-order_chat_send_"] button {{
    min-height: 2.8rem !important;
    border: none !important;
    border-radius: 14px !important;
    background: linear-gradient(135deg, #f97316, #f59e0b) !important;
    box-shadow: 0 12px 24px rgba(249, 115, 22, 0.22) !important;
    font-weight: 820 !important;
}}
div[class*="st-key-so_chat_card_"] div[class*="st-key-order_chat_send_"] button:hover {{
    transform: translateY(-1px);
    box-shadow: 0 16px 30px rgba(249, 115, 22, 0.28) !important;
}}
.so-detail-brief {{
    margin: 0.45rem 0 0;
    display: flex;
    flex-wrap: wrap;
    gap: 0.45rem;
}}
.so-detail-chip {{
    display: inline-flex;
    align-items: center;
    height: 1.8rem;
    padding: 0 0.65rem;
    border-radius: 999px;
    background: #ffffff;
    border: 1px solid #e5e7eb;
    color: #475569;
    font-size: 0.76rem;
    font-weight: 650;
}}
div[class*="st-key-so_back_"] {{ margin-bottom: 0.7rem !important; }}
div[class*="st-key-so_aside_panel_"] .stButton > button {{
    border-radius: 10px !important;
    min-height: 2.45rem !important;
    font-weight: 700 !important;
}}
div[class*="st-key-so_aside_panel_"] .stLinkButton a {{
    border-radius: 10px !important;
    min-height: 2.45rem !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
}}
</style>
<div id="sinlex-orders-page"></div>
"""


def _inject_orders_layout() -> None:
    st.markdown(_orders_css(), unsafe_allow_html=True)


def _esc(value) -> str:
    if value is None or value == "":
        return "—"
    return html.escape(str(value))


def _money(value) -> str:
    try:
        return f"{int(value):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def _stage_index(stage: str) -> int:
    keys = [s[0] for s in ORDER_STAGES]
    try:
        return keys.index(stage)
    except ValueError:
        return 0


def _order_stage_percent(order: dict) -> int:
    """Процент внутри текущего этапа: 0..100 до следующего этапа.

    В order.json можно указать одно из полей: progress_percent, stage_percent или progress.
    """
    for key in ("progress_percent", "stage_percent", "progress"):
        raw = order.get(key)
        if raw in (None, ""):
            continue
        try:
            value = float(str(raw).replace(",", ".").strip().rstrip("%"))
        except (TypeError, ValueError):
            continue
        return max(0, min(100, int(round(value))))
    return 0


def _order_total_progress(stage: str, stage_percent: int) -> int:
    idx = _stage_index(stage)
    n = len(ORDER_STAGES)
    if stage == "completed":
        return 100
    segment = 100 / max(n - 1, 1)
    return max(4, min(100, int(round((idx * segment) + (segment * (stage_percent / 100.0))))))


_FLOW_SKINS = {
    "sinlex": ("Синлекс", "so-flow-skin-sinlex"),
    "sap": ("SAP/Fiori", "so-flow-skin-sap"),
    "winxp": ("Windows XP", "so-flow-skin-winxp"),
    "win95": ("Windows 95", "so-flow-skin-win95"),
    "ssh": ("SSH terminal", "so-flow-skin-ssh"),
    "norton": ("Norton Commander", "so-flow-skin-norton"),
    "tva": ("8-bit УВР", "so-flow-skin-tva"),
    "sega": ("Sega 16-bit", "so-flow-skin-sega"),
}
_FLOW_SKIN_LABELS = [label for label, _cls in _FLOW_SKINS.values()]
_FLOW_SKIN_BY_LABEL = {label: key for key, (label, _cls) in _FLOW_SKINS.items()}


def _selected_flow_skin(order_id: str) -> str:
    state_key = f"flow_status_skin_{order_id}"
    selected = st.session_state.get(state_key, "norton")
    if selected not in _FLOW_SKINS:
        selected = "norton"
    label = _FLOW_SKINS[selected][0]
    try:
        index = _FLOW_SKIN_LABELS.index(label)
    except ValueError:
        index = 0
    with st.container(key=f"so_flow_skin_{order_id}"):
        picked = st.selectbox(
            "Стиль статуса производства",
            _FLOW_SKIN_LABELS,
            index=index,
            key=f"flow_status_skin_select_{order_id}",
        )
    selected = _FLOW_SKIN_BY_LABEL.get(picked, selected)
    st.session_state[state_key] = selected
    return selected


def _stage_detail_text(stage: str, current_label: str, next_label: str, stage_pct: int, is_completed: bool) -> str:
    if is_completed:
        return "Заказ прошёл производственный маршрут. Документы, параметры и финальные данные сохранены в карточке заказа."
    detail_by_stage = {
        "placed": "Заказ зарегистрирован в системе. Команда проверяет исходные данные, состав партии, материалы и полноту вложений перед передачей в работу.",
        "review": "Идёт инженерная проверка: уточняются технологичность, допуски, материал, объём партии и возможные производственные риски.",
        "production": "Заказ находится в производственном контуре. Выполняются операции по согласованному маршруту, статус обновляется по мере прохождения этапов.",
        "quality": "Партия проходит контроль качества. Проверяются ключевые параметры, комплектность и соответствие согласованной спецификации.",
        "shipment": "Заказ готовится к отгрузке: финализируются документы, упаковка и передача результата клиенту.",
    }
    base = detail_by_stage.get(stage, "Текущий этап активен. Производственный маршрут продолжается, данные по заказу сохраняются в карточке.")
    return f"{base} Прогресс внутри этапа: {stage_pct}%. Следующий ориентир: «{next_label}»."


def _render_track(order: dict, skin: str = "norton", order_id: str = "") -> None:
    stage = order.get("stage") or "placed"
    idx = _stage_index(stage)
    n = len(ORDER_STAGES)
    stage_pct = 100 if stage == "completed" else _order_stage_percent(order)
    pct = _order_total_progress(stage, stage_pct)
    current_label = stage_label(stage)
    is_completed = stage == "completed"
    fill_live = "" if is_completed else " is-live"
    skin_cls = _FLOW_SKINS.get(skin, _FLOW_SKINS["norton"])[1]

    nodes = []
    labels = []
    for i, (_key, label) in enumerate(ORDER_STAGES):
        if i < idx:
            ncls, lcls = "so-flow-node done", "so-flow-label done"
        elif i == idx:
            ncls, lcls = "so-flow-node current", "so-flow-label current"
        else:
            ncls, lcls = "so-flow-node", "so-flow-label"
        nodes.append(f'<div class="{ncls}">{i + 1}</div>')
        labels.append(f'<div class="{lcls}">{html.escape(label)}</div>')

    next_label = ORDER_STAGES[idx + 1][1] if idx + 1 < n else "Финиш"
    step_human = f"Этап {idx + 1} из {n}"
    stage_note = "завершено" if is_completed else f"{stage_pct}% до этапа «{next_label}»"
    detail_text = _stage_detail_text(stage, current_label, next_label, stage_pct, is_completed)
    face_html = (
        f'<div class="so-flow-status {skin_cls}">'
        f'<div class="so-flow-head">'
        f'<span class="so-flow-title">Статус производства</span>'
        f'<span class="so-flow-badge">{html.escape(current_label)}</span>'
        f"</div>"
        f'<div class="so-flow-meta">Общий прогресс: <b>{pct}%</b> · {html.escape(step_human)} · {html.escape(stage_note)}</div>'
        f'<div class="so-flow-rail">'
        f'<div class="so-flow-bar">'
        f'<div class="so-flow-bar-fill{fill_live}" style="width:{pct}%"></div>'
        f"</div>"
        f'<div class="so-flow-nodes">{"".join(nodes)}</div>'
        f"</div>"
        f'<div class="so-flow-labels">{"".join(labels)}</div>'
        f'<div class="so-flow-status-hint">Нажмите для деталей</div>'
        f"</div>"
    )
    back_html = (
        f'<div class="so-flow-status {skin_cls}">'
        f'<div class="so-flow-back-body">'
        f'<p class="so-flow-back-eyebrow">Подробности статуса</p>'
        f'<h4 class="so-flow-back-title">{html.escape(current_label)}</h4>'
        f'<p class="so-flow-back-text">{html.escape(detail_text)}</p>'
        f'<div class="so-flow-back-grid">'
        f'<div class="so-flow-back-metric"><p class="k">Общий прогресс</p><p class="v">{pct}%</p></div>'
        f'<div class="so-flow-back-metric"><p class="k">Текущий этап</p><p class="v">{html.escape(step_human)}</p></div>'
        f'<div class="so-flow-back-metric"><p class="k">Следующий шаг</p><p class="v">{html.escape("Финиш" if is_completed else next_label)}</p></div>'
        f'</div>'
        f'<p class="so-flow-back-action">Нажмите ещё раз, чтобы вернуться к шкале производства.</p>'
        f'</div></div>'
    )
    st.markdown(
        f'<details class="so-flow-flip">'
        f'<summary class="so-flow-flip-summary" aria-label="Показать подробности статуса производства">'
        f'<span class="so-flow-flip-inner">'
        f'<span class="so-flow-flip-face so-flow-flip-front">{face_html}</span>'
        f'<span class="so-flow-flip-face so-flow-flip-back">{back_html}</span>'
        f'</span></summary></details>',
        unsafe_allow_html=True,
    )


def _spec_table(rows: list[tuple[str, str]]) -> str:
    parts = ['<div class="so-spec">']
    for k, v in rows:
        if not v or v == "—":
            continue
        parts.append(
            f'<div class="so-spec-row"><div class="k">{html.escape(k)}</div>'
            f'<div class="v">{_esc(v)}</div></div>'
        )
    parts.append("</div>")
    return "".join(parts)


def _render_order_list(user_folder: str) -> None:
    orders = list_user_orders(user_folder)
    if not orders:
        st.markdown(
            """
<div class="so-empty">
  <h3>Заказов пока нет</h3>
  <p>Откройте 3D-проект, рассчитайте стоимость и нажмите «Размещение заказа» — заказ появится здесь.</p>
</div>
            """,
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        f'<div class="so-list-head"><span class="count">Заказов: <b>{len(orders)}</b></span></div>'
        '<div class="so-feed">',
        unsafe_allow_html=True,
    )

    for i, order in enumerate(orders):
        payload = order.get("payload") or {}
        title = order.get("project_name") or payload.get("Проект") or "Без названия"
        date_s = order.get("created_at_display") or payload.get("Дата") or "—"
        stage = order.get("stage") or "placed"
        total = _money(payload.get("Общая стоимость"))
        stage_cls = "so-stage is-active"

        with st.container(key=f"so_card_{i}"):
            st.markdown(
                f"""
<div class="so-row">
  <div>
    <p class="so-row-title">{_esc(title)}</p>
    <p class="so-row-meta">{_esc(date_s)}</p>
  </div>
  <span class="{stage_cls}">{_esc(stage_label(stage))}</span>
  <div class="so-price">{_esc(total)} <span>₽</span></div>
</div>
                """,
                unsafe_allow_html=True,
            )
            act_open, act_del = st.columns([5, 1])
            with act_open:
                if st.button("Открыть заказ →", key=f"order_open_{i}", type="secondary"):
                    st.session_state.my_order_id = order["id"]
                    st.rerun()
            with act_del:
                if st.button(
                    delete_button_label(),
                    key=delete_button_key("order", i),
                    type="secondary",
                    help="Удалить заказ",
                ):
                    try:
                        delete_user_order(user_folder, order["id"])
                        if st.session_state.get("my_order_id") == order["id"]:
                            st.session_state.pop("my_order_id", None)
                        st.toast("Заказ удалён", icon="🗑️")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Не удалось удалить: {exc}")

    st.markdown("</div>", unsafe_allow_html=True)


def _chat_history_path(order: dict) -> str:
    order_dir = (order.get("order_dir") or "").strip()
    return os.path.join(order_dir, "history.json") if order_dir else ""


def _load_chat_history(order: dict) -> list[dict]:
    path = _chat_history_path(order)
    if path and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            raw = data.get("messages") if isinstance(data, dict) else data
            if isinstance(raw, list):
                return [m for m in raw if isinstance(m, dict)]
        except (OSError, json.JSONDecodeError):
            pass
    raw = order.get("manager_chat") or order.get("chat") or []
    return [m for m in raw if isinstance(m, dict)]


def _save_chat_history(order: dict, messages: list[dict]) -> None:
    path = _chat_history_path(order)
    if not path:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "order_id": order.get("id") or "",
        "updated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "messages": messages,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _chat_messages(order: dict) -> list[dict]:
    return _load_chat_history(order)


def _chat_sender_label(role: str) -> str:
    return "Менеджер" if role == "manager" else ("Система" if role == "system" else "Вы")


def _chat_avatar(role: str) -> str:
    if role == "manager":
        return "СМ"
    if role == "system":
        return ""
    return "Вы"


def _render_manager_chat(order: dict) -> None:
    messages = _chat_messages(order)
    if not messages:
        st.markdown('<div class="so-chat-empty">История переписки пока пустая. Напишите менеджеру по заказу, и ответ появится здесь.</div>', unsafe_allow_html=True)
        return
    parts = ['<div class="so-chat-box">']
    for msg in reversed(messages[-20:]):
        role = (msg.get("role") or "user").strip()
        if role not in ("user", "manager", "system"):
            role = "user"
        created = msg.get("created_at") or ""
        text = msg.get("text") or ""
        sent = msg.get("sent")
        suffix = " · не отправлено" if role == "user" and sent is False else (" · отправлено" if role == "user" and sent is True else "")
        when = (" · " + html.escape(created[:16].replace("T", " "))) if created else ""
        label = html.escape(_chat_sender_label(role))
        avatar = html.escape(_chat_avatar(role))
        parts.append(
            f'<div class="so-chat-row {role}">'
            f'<div class="so-chat-avatar">{avatar}</div>'
            f'<div class="so-chat-msg {role}">'
            f'<p class="so-chat-meta">{label}{when}{suffix}</p>'
            f'<p class="so-chat-text">{_esc(text)}</p>'
            f'</div></div>'
        )
    parts.append('</div>')
    st.markdown("".join(parts), unsafe_allow_html=True)


def _send_manager_chat_email(order: dict, text: str, user_email: str) -> str:
    from order_placement import _smtp_candidates, _smtp_send_message

    candidates = _smtp_candidates()
    if not candidates:
        raise RuntimeError("Канал сообщений не настроен")
    cfg = candidates[0]
    from_addr = cfg.get("from") or cfg.get("smtp_user") or ""
    from_name = cfg.get("from_name") or "Sinlex"
    project = order.get("project_name") or (order.get("payload") or {}).get("Проект") or "Заказ"
    oid = order.get("id") or ""
    msg = EmailMessage()
    msg["From"] = formataddr((from_name, from_addr))
    msg["To"] = _MANAGER_EMAIL
    msg["Subject"] = f"[Sinlex] Чат с менеджером — заказ {oid} — {project}"[:180]
    message_id = make_msgid(domain="sinlex.tech")
    msg["Message-ID"] = message_id
    msg["Reply-To"] = _CHAT_REPLY_EMAIL
    msg.set_content(
        f"Сообщение из личного кабинета Sinlex\n\n"
        f"Заказ: {oid}\n"
        f"Проект: {project}\n"
        f"Пользователь: {user_email or '—'}\n\n"
        f"Сообщение:\n{text}\n"
    )
    _smtp_send_message(cfg, msg)
    return message_id


def _poll_manager_chat_replies(user_folder: str, order_id: str, order: dict) -> int:
    from email_logistics.config import email_settings
    from email_logistics.imap_receive import (
        _header_msg_ids,
        _imap_connect_and_select,
        _message_body_text,
        normalize_msg_id,
    )

    messages = _chat_messages(order)
    sent_ids = {
        normalize_msg_id(str(m.get("message_id") or ""))
        for m in messages
        if m.get("role") == "user" and m.get("message_id")
    }
    if not sent_ids:
        return 0
    existing_keys = {
        str(m.get("source_message_id") or m.get("text") or "")
        for m in messages
        if m.get("role") == "manager"
    }
    cfg = email_settings()
    imap = None
    added = 0
    try:
        imap = _imap_connect_and_select(cfg, readonly=False)
        status, data = imap.search(None, "UNSEEN")
        if status != "OK" or not data or not data[0]:
            return 0
        import email as _email

        for num in data[0].split():
            status, fetched = imap.fetch(num, "(RFC822)")
            if status != "OK" or not fetched or not fetched[0]:
                continue
            raw = fetched[0][1]
            if not isinstance(raw, (bytes, bytearray)):
                continue
            msg = _email.message_from_bytes(bytes(raw))
            refs = _header_msg_ids(msg, "In-Reply-To") | _header_msg_ids(msg, "References")
            if not (refs & sent_ids):
                continue
            body = _message_body_text(msg).strip()
            if not body:
                continue
            source_mid = normalize_msg_id(msg.get("Message-ID") or "") or body
            if source_mid in existing_keys:
                imap.store(num, "+FLAGS", "\\Seen")
                continue
            messages.append({
                "role": "manager",
                "text": body,
                "created_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
                "source_message_id": source_mid,
            })
            existing_keys.add(source_mid)
            added += 1
            imap.store(num, "+FLAGS", "\\Seen")
    finally:
        if imap is not None:
            try:
                imap.logout()
            except Exception:
                pass
    if added:
        _save_chat_history(order, messages)
    return added


def _append_chat_message(user_folder: str, order_id: str, order: dict, message: dict) -> None:
    messages = _chat_messages(order)
    messages.append(message)
    _save_chat_history(order, messages)


def _render_order_chat_section(user_folder: str, order_id: str, order: dict) -> None:
    try:
        if _poll_manager_chat_replies(user_folder, order_id, order):
            order = load_order(user_folder, order_id) or order
    except Exception:
        pass
    order = load_order(user_folder, order_id) or order
    input_version_key = f"order_chat_input_version_{order_id}"
    input_version = int(st.session_state.get(input_version_key, 0))
    with st.container(key=f"so_chat_card_{order_id}"):
        st.markdown(
            '<div class="so-chat-section"><div class="so-chat-section-head">'
            '<h5>Чат с менеджером</h5>'
            '<p>Сроки, оплата и уточнения по детали. Все сообщения сохраняются в карточке заказа.</p>'
            '</div></div>',
            unsafe_allow_html=True,
        )
        _render_manager_chat(order)
        st.markdown('<div class="so-chat-form-note">Новое сообщение менеджеру</div>', unsafe_allow_html=True)
        chat_text = st.text_area(
            "Новое сообщение менеджеру",
            key=f"order_chat_text_{order_id}_{input_version}",
            label_visibility="collapsed",
            height=120,
            placeholder="Напишите вопрос по срокам, оплате или производству...",
        )
        send_col, _ = st.columns([1, 2.2])
        with send_col:
            if st.button("Отправить сообщение", key=f"order_chat_send_{order_id}", type="primary", use_container_width=True):
                text = (chat_text or "").strip()
                if not text:
                    st.warning("Введите сообщение.")
                else:
                    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
                    msg = {"role": "user", "text": text, "created_at": now, "sent": False}
                    try:
                        message_id = _send_manager_chat_email(
                            order,
                            text,
                            st.session_state.get("original_email") or st.session_state.get("user_email") or "",
                        )
                        msg["sent"] = True
                        msg["message_id"] = message_id
                        _append_chat_message(user_folder, order_id, order, msg)
                        st.session_state[input_version_key] = input_version + 1
                        st.toast("Сообщение отправлено", icon="✅")
                        st.rerun(scope="fragment")
                    except Exception as exc:
                        msg["error"] = str(exc)
                        _append_chat_message(user_folder, order_id, order, msg)
                        st.error(f"Не удалось отправить сообщение: {exc}")


if hasattr(st, "fragment"):
    _render_order_chat_section = st.fragment(run_every="20s")(_render_order_chat_section)


def _render_order_detail(user_folder: str, order_id: str) -> None:
    order = load_order(user_folder, order_id)
    if not order:
        st.error("Заказ не найден.")
        with st.container(key="so_back_missing"):
            if st.button("К списку заказов", key="order_back_missing"):
                st.session_state.pop("my_order_id", None)
                st.rerun()
        return

    payload = order.get("payload") or {}
    project = order.get("project_name") or payload.get("Проект") or "Заказ"
    stage = order.get("stage") or "placed"
    date_s = order.get("created_at_display") or payload.get("Дата") or "—"
    total = _money(payload.get("Общая стоимость"))
    unit = _money(payload.get("Цена за ед."))
    batch = payload.get("Партия")
    batch_hint = f"Партия {batch} шт." if batch else ""
    unit_hint = f"{unit} ₽ / шт." if unit != "—" and batch else ""

    with st.container(key=f"so_back_{order_id}"):
        if st.button("← Все заказы", key="order_back"):
            st.session_state.pop("my_order_id", None)
            st.rerun()

    st.markdown(
        f"""
<div class="so-detail-shell">
  <div class="so-detail-top">
    <div class="so-detail-top-grid">
      <div>
        <div class="so-detail-eyebrow">Заказ · {_esc(order_id)}</div>
        <h1 class="so-detail-title">{_esc(project)}</h1>
        <p class="so-detail-sub">Размещён {_esc(date_s)}. Производственный статус и документы заказа собраны в одной карточке.</p>
        <div class="so-detail-brief">
          <span class="so-detail-chip">{_esc(stage_label(stage))}</span>
          <span class="so-detail-chip">{_esc(batch_hint or "Партия не указана")}</span>
          <span class="so-detail-chip">{_esc(unit_hint or "Цена за ед. —")}</span>
        </div>
      </div>
      <div class="so-detail-kpis">
        <div class="so-detail-kpi"><p class="k">Сумма</p><p class="v teal">{_esc(total)} ₽</p></div>
        <div class="so-detail-kpi"><p class="k">Этап</p><p class="v">{_esc(stage_label(stage))}</p></div>
      </div>
    </div>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )

    flow_skin = _selected_flow_skin(order_id)
    _render_track(order, flow_skin, order_id)

    spec_rows = [
        ("Материал", payload.get("Материал")),
        ("Габариты", payload.get("Габариты")),
        ("Партия", f"{batch} шт." if batch else None),
        ("Цена за ед.", f"{unit} ₽" if unit != "—" else None),
        ("Контакт", payload.get("Контакт")),
        ("Телефон", payload.get("Телефон")),
        ("Email", payload.get("Email")),
    ]
    comment = (payload.get("Комментарий") or "").strip()
    attachments = order.get("attachments") or {}
    hint = " · ".join(x for x in (batch_hint, unit_hint) if x)

    col_main, col_aside = st.columns([1.55, 1], gap="large")
    with col_main:
        left_html = '<div class="so-panel"><div class="so-panel-h">Спецификация</div>' + _spec_table(spec_rows)
        if comment and comment != "—":
            left_html += '<div class="so-panel-h" style="border-top:1px solid #e5e7eb">Комментарий</div>' + f'<p class="so-comment">{_esc(comment)}</p>'
        if attachments:
            chips = []
            for _kind, fname in attachments.items():
                ext = fname.rsplit(".", 1)[-1].upper() if "." in fname else "FILE"
                chips.append(f'<div class="so-file"><span class="tag">{html.escape(ext)}</span><span>{html.escape(fname)}</span></div>')
            left_html += '<div class="so-panel-h" style="border-top:1px solid #e5e7eb">Документы</div>' + f'<div class="so-files">{"".join(chips)}</div>'
        left_html += "</div>"
        st.markdown(left_html, unsafe_allow_html=True)

    with col_aside:
        with st.container(key=f"so_aside_panel_{order_id}"):
            st.markdown(
                f"""
<div class="so-panel">
  <div class="so-aside-total">
    <div class="lbl">Сумма заказа</div>
    <div class="sum">{_esc(total)} ₽</div>
    <div class="hint">{_esc(hint)}</div>
  </div>
  <div class="so-aside-block">
    <h5>Реквизиты</h5>
    <p>Загрузите карточку организации для выставления счёта.</p>
  </div>
</div>
                """,
                unsafe_allow_html=True,
            )
            existing = order.get("requisites_files") or []
            if existing:
                st.markdown(f'<div class="so-req-ok">Загружено: {_esc(", ".join(existing))}</div>', unsafe_allow_html=True)
            uploaded = st.file_uploader(
                "Файлы реквизитов",
                type=["pdf", "doc", "docx", "png", "jpg", "jpeg"],
                accept_multiple_files=True,
                key=f"order_req_{order_id}",
                label_visibility="collapsed",
            )
            if uploaded and st.button("Сохранить реквизиты", key=f"order_req_save_{order_id}", use_container_width=True):
                try:
                    add_requisites_files(user_folder, order_id, [(f.name, f.getvalue()) for f in uploaded])
                    st.toast("Реквизиты сохранены", icon="✅")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    _render_order_chat_section(user_folder, order_id, order)

    confirm_key = f"confirm_del_order_{order_id}"
    st.markdown(
        '<div class="so-danger-zone">'
        "<h5>Удаление заказа</h5>"
        "<p>Заказ и все загруженные файлы будут удалены без возможности восстановления.</p>"
        "</div>",
        unsafe_allow_html=True,
    )
    with st.container(key=f"so_delete_{order_id}"):
        if not st.session_state.get(confirm_key):
            if st.button("Удалить заказ", key=f"order_del_ask_{order_id}", type="secondary"):
                st.session_state[confirm_key] = True
                st.rerun()
        else:
            st.warning("Подтвердите удаление заказа.")
            c_yes, c_no = st.columns(2)
            with c_yes:
                if st.button("Да, удалить", key=f"order_del_yes_{order_id}", type="primary"):
                    try:
                        delete_user_order(user_folder, order_id)
                        st.session_state.pop("my_order_id", None)
                        st.session_state.pop(confirm_key, None)
                        st.toast("Заказ удалён", icon="🗑️")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Не удалось удалить: {exc}")
            with c_no:
                if st.button("Отмена", key=f"order_del_no_{order_id}"):
                    st.session_state.pop(confirm_key, None)
                    st.rerun()


def render() -> None:
    page_title("Мои заказы")
    inject_unified_main_scroll()
    _inject_orders_layout()
    inject_delete_icon_button_styles()

    if st.session_state.get("guest_mode") or not st.session_state.get("user_email"):
        st.warning("Войдите в аккаунт, чтобы видеть заказы.")
        return

    user_folder = (st.session_state.get("user_folder") or "").strip()
    if not user_folder:
        st.error("Не определена папка пользователя.")
        return

    order_id = st.session_state.get("my_order_id")
    if order_id:
        _render_order_detail(user_folder, order_id)
    else:
        _render_order_list(user_folder)
