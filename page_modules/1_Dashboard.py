"""Личный кабинет — операционная сводка Sinlex."""
from __future__ import annotations

import base64
import html
import os
from collections import Counter
from datetime import datetime, timedelta, timezone

import streamlit as st

from orders_store import ORDER_STAGES, list_user_orders, stage_label
from project_dates import parse_project_datetime
from project_store import _safe_dir_name, projects_base_dir

_C = {
    "orange": "#ff8800",
    "teal": "#14b8a6",
    "teal_dark": "#0d9488",
    "ink": "#111827",
    "soft_ink": "#374151",
    "muted": "#6b7280",
    "faint": "#9ca3af",
    "line": "#e5e7eb",
    "line_dark": "#d1d5db",
    "wash": "#f7f8fa",
    "panel": "#ffffff",
}


def _esc(value) -> str:
    if value is None or value == "":
        return "—"
    return html.escape(str(value))


def _money(value) -> str:
    try:
        return f"{int(float(value)):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def _stage_index(stage: str) -> int:
    keys = [key for key, _label in ORDER_STAGES]
    try:
        return keys.index(stage)
    except ValueError:
        return 0


def _stage_pct(stage: str) -> int:
    return int((_stage_index(stage) / max(len(ORDER_STAGES) - 1, 1)) * 100)


def _css() -> str:
    c = _C
    return f"""
<style>
#sinlex-dashboard-page {{ display: none !important; }}
[data-testid="stAppViewContainer"]:has(#sinlex-dashboard-page) [data-testid="stTitle"],
[data-testid="stAppViewContainer"]:has(#sinlex-dashboard-page) .sinlex-page-top {{
    display: none !important;
}}
[data-testid="stAppViewContainer"]:has(#sinlex-dashboard-page) [data-testid="stMainBlockContainer"] {{
    max-width: 1240px !important;
    padding-top: 0.4rem !important;
}}
[data-testid="stAppViewContainer"]:has(#sinlex-dashboard-page) [data-testid="column"] {{
    min-width: 0 !important;
}}

.sx {{
    color: {c['ink']};
    font-family: inherit;
}}
.sx-shell {{
    display: grid;
    gap: 1rem;
}}
.sx-top {{
    display: block;
    position: relative;
    min-height: 285px;
    padding: 0.2rem 0 1.1rem;
    border-bottom: 1px solid {c['line']};
}}
.sx-top > div:first-child {{
    max-width: 560px;
    position: relative;
    z-index: 1;
}}
.sx-overline {{
    margin: 0 0 0.45rem;
    color: {c['faint']};
    font-size: 0.68rem;
    font-weight: 700;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    white-space: nowrap;
}}
.sx-title {{
    margin: 0;
    color: {c['ink']};
    font-size: clamp(1.45rem, 2.5vw, 2.15rem);
    font-weight: 760;
    letter-spacing: -0.04em;
    line-height: 1.08;
}}
.sx-sub {{
    margin: 0.55rem 0 0;
    color: {c['muted']};
    font-size: 0.92rem;
    line-height: 1.55;
    max-width: 46rem;
}}
.sx-top-right {{
    position: absolute;
    top: -30px;
    right: 0;
    z-index: 0;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    justify-content: flex-start;
    gap: 0.72rem;
    width: min(620px, 54vw);
    min-width: 0;
}}
.sx-lathe-card {{
    width: 100%;
    max-width: 620px;
    min-width: 0;
    height: 220px;
    border: none;
    border-radius: 0;
    background: transparent;
    box-shadow: none;
    overflow: hidden;
    position: relative;
    pointer-events: none;
}}
.sx-lathe-img {{
    width: 100%;
    height: 100%;
    object-fit: contain;
    object-position: center right;
    display: block;
    filter: none;
}}
.sx-statusbar {{
    display: flex;
    gap: 0.5rem;
    justify-content: flex-end;
    align-items: center;
    flex-wrap: wrap;
}}
.sx-pill {{
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    height: 2.25rem;
    padding: 0 0.75rem;
    border-radius: 999px;
    background: {c['panel']};
    border: 1px solid {c['line']};
    color: {c['soft_ink']};
    font-size: 0.78rem;
    font-weight: 650;
    white-space: nowrap;
}}
.sx-pill strong {{ color: {c['ink']}; font-weight: 760; }}
.sx-pill.flow {{ border-color: #99f6e4; background: #f0fdfa; color: {c['teal_dark']}; }}
.sx-dot {{
    width: 0.45rem;
    height: 0.45rem;
    border-radius: 999px;
    background: {c['teal']};
    box-shadow: 0 0 0 4px rgba(20, 184, 166, 0.12);
}}

.sx-board {{
    display: grid;
    grid-template-columns: minmax(0, 1.75fr) minmax(320px, 0.85fr);
    gap: 1rem;
    align-items: start;
    margin-top: 1rem;
}}
@media (max-width: 980px) {{
    .sx-board {{ grid-template-columns: 1fr; }}
    .sx-top {{ min-height: 0; }}
    .sx-top > div:first-child {{ max-width: 100%; }}
    .sx-top-right {{
        position: relative;
        top: auto;
        right: auto;
        z-index: 0;
        width: min(100%, 620px);
        align-items: flex-start;
        margin-top: 1.2rem;
    }}
    .sx-lathe-card {{ width: min(100%, 620px); min-width: 0; height: 220px; }}
    .sx-statusbar {{ justify-content: flex-start; }}
}}
@media (max-width: 620px) {{
    .sx-overline {{ white-space: normal; }}
    .sx-lathe-card {{ height: 180px; }}
}}
.sx-stack {{ display: grid; gap: 1rem; }}

[data-testid="stAppViewContainer"]:has(#sinlex-dashboard-page) section[data-testid="stMain"] [data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] {{
    gap: 0.85rem !important;
}}
[data-testid="stAppViewContainer"]:has(#sinlex-dashboard-page) section[data-testid="stMain"] [data-testid="stElementContainer"]:has(.sx-section),
[data-testid="stAppViewContainer"]:has(#sinlex-dashboard-page) section[data-testid="stMain"] [data-testid="stElementContainer"]:has(.sx-side-card) {{
    margin-bottom: 0.95rem !important;
}}

.sx-summary {{
    display: grid;
    grid-template-columns: minmax(260px, 0.9fr) minmax(0, 1.4fr);
    gap: 0;
    overflow: hidden;
    border: 1px solid {c['line']};
    border-radius: 18px;
    background: {c['panel']};
    box-shadow: 0 14px 35px rgba(17, 24, 39, 0.05);
    margin-bottom: 1.2rem;
}}
@media (max-width: 760px) {{ .sx-summary {{ grid-template-columns: 1fr; }} }}
.sx-balance {{
    position: relative;
    overflow: hidden;
    padding: 1.45rem;
    color: #fff;
    background:
        radial-gradient(circle at 85% 12%, rgba(255,255,255,0.2), transparent 30%),
        linear-gradient(145deg, #042f2e 0%, #0f766e 52%, #14b8a6 100%);
    isolation: isolate;
}}
.sx-balance::before {{
    content: "";
    position: absolute;
    inset: -45%;
    z-index: 0;
    background:
        radial-gradient(circle at 24% 42%, rgba(94, 234, 212, 0.28) 0%, transparent 32%),
        radial-gradient(circle at 72% 34%, rgba(255, 255, 255, 0.16) 0%, transparent 28%),
        linear-gradient(120deg, rgba(255,255,255,0) 22%, rgba(255,255,255,0.14) 46%, rgba(255,255,255,0) 70%);
    filter: blur(10px);
    opacity: 0.7;
    transform: translate3d(-6%, 0, 0) scale(1.02);
    animation: sx-balance-sheen 12s ease-in-out infinite alternate;
}}
.sx-balance::after {{
    content: "";
    position: absolute;
    inset: 0;
    z-index: 0;
    background: linear-gradient(105deg, transparent 34%, rgba(255, 255, 255, 0.18) 50%, transparent 66%);
    opacity: 0.0;
    transform: translateX(-42%);
    animation: sx-balance-glint 9s ease-in-out infinite;
}}
@keyframes sx-balance-sheen {{
    0% {{ transform: translate3d(-7%, 2%, 0) scale(1.02); opacity: 0.58; }}
    50% {{ transform: translate3d(3%, -1%, 0) scale(1.06); opacity: 0.78; }}
    100% {{ transform: translate3d(8%, 2%, 0) scale(1.03); opacity: 0.64; }}
}}
@keyframes sx-balance-glint {{
    0%, 64% {{ opacity: 0; transform: translateX(-48%); }}
    76% {{ opacity: 0.42; }}
    100% {{ opacity: 0; transform: translateX(48%); }}
}}
.sx-balance .label {{
    margin: 0 0 0.9rem;
    opacity: 0.82;
    font-size: 0.72rem;
    font-weight: 750;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    position: relative;
    z-index: 1;
}}
.sx-balance .value {{
    margin: 0;
    font-size: clamp(2rem, 4vw, 2.75rem);
    line-height: 0.95;
    font-weight: 820;
    letter-spacing: -0.05em;
    position: relative;
    z-index: 1;
    text-shadow: 0 10px 30px rgba(0, 0, 0, 0.18);
}}
.sx-balance .note {{
    margin: 0.9rem 0 0;
    max-width: 18rem;
    color: rgba(255,255,255,0.86);
    font-size: 0.82rem;
    line-height: 1.45;
    position: relative;
    z-index: 1;
}}
.sx-scoregrid {{
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    border-left: 1px solid {c['line']};
}}
@media (max-width: 760px) {{ .sx-scoregrid {{ border-left: 0; grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
.sx-score {{
    min-height: 8.2rem;
    padding: 1.25rem 1.15rem;
    border-right: 1px solid {c['line']};
    border-bottom: 1px solid {c['line']};
    background: linear-gradient(180deg, #fff 0%, #fbfbfc 100%);
}}
.sx-score:nth-child(4n) {{ border-right: 0; }}
.sx-score .num {{
    margin: 0;
    color: {c['ink']};
    font-size: 1.7rem;
    font-weight: 780;
    letter-spacing: -0.04em;
}}
.sx-score .cap {{
    margin: 0.45rem 0 0;
    color: {c['muted']};
    font-size: 0.78rem;
    line-height: 1.35;
}}
.sx-score .trend {{
    display: inline-block;
    margin-top: 0.8rem;
    color: {c['teal_dark']};
    font-size: 0.72rem;
    font-weight: 700;
}}

.sx-section {{
    border: 1px solid {c['line']};
    border-radius: 16px;
    background: {c['panel']};
    overflow: hidden;
    box-shadow: 0 8px 24px rgba(17, 24, 39, 0.035);
    margin-bottom: 1.15rem;
}}
.sx-section-head {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding: 1rem 1.15rem;
    border-bottom: 1px solid {c['line']};
    background: #fff;
}}
.sx-section-title {{
    margin: 0;
    color: {c['ink']};
    font-size: 0.92rem;
    font-weight: 760;
    letter-spacing: -0.01em;
}}
.sx-section-meta {{
    color: {c['muted']};
    font-size: 0.76rem;
    font-weight: 650;
}}
.sx-section-body {{ padding: 0.35rem 0; }}

.sx-pipeline {{
    display: grid;
    grid-template-columns: repeat(6, minmax(0, 1fr));
    gap: 0;
    padding: 0.9rem 1rem 0.75rem;
    border-bottom: 1px solid {c['line']};
    background: {c['wash']};
}}
.sx-step {{
    position: relative;
    min-width: 0;
    padding-right: 0.45rem;
}}
.sx-step::before {{
    content: "";
    display: block;
    height: 3px;
    border-radius: 999px;
    background: {c['line_dark']};
    margin-bottom: 0.55rem;
}}
.sx-step.live::before {{ background: linear-gradient(90deg, {c['teal']}, {c['teal_dark']}); }}
.sx-step .count {{
    color: {c['ink']};
    font-size: 1.05rem;
    font-weight: 760;
}}
.sx-step .name {{
    display: block;
    overflow: hidden;
    color: {c['muted']};
    font-size: 0.68rem;
    text-overflow: ellipsis;
    white-space: nowrap;
}}

.sx-order-row {{
    display: grid;
    grid-template-columns: minmax(0, 1.5fr) 7.5rem 7rem;
    gap: 1rem;
    align-items: center;
    padding: 0.95rem 1.15rem;
    border-bottom: 1px solid #f1f2f4;
}}
.sx-order-row:last-child {{ border-bottom: 0; }}
.sx-name {{
    margin: 0;
    overflow: hidden;
    color: {c['ink']};
    font-size: 0.9rem;
    font-weight: 700;
    text-overflow: ellipsis;
    white-space: nowrap;
}}
.sx-subtle {{
    margin: 0.22rem 0 0;
    color: {c['muted']};
    font-size: 0.75rem;
}}
.sx-stage {{
    display: inline-flex;
    justify-content: center;
    padding: 0.28rem 0.55rem;
    border: 1px solid #99f6e4;
    border-radius: 999px;
    background: #f0fdfa;
    color: {c['teal_dark']};
    font-size: 0.7rem;
    font-weight: 760;
    white-space: nowrap;
}}
.sx-amount {{
    color: {c['ink']};
    font-size: 0.88rem;
    font-weight: 760;
    text-align: right;
    white-space: nowrap;
}}
.sx-progress {{
    grid-column: 1 / -1;
    height: 4px;
    overflow: hidden;
    border-radius: 999px;
    background: {c['line']};
}}
.sx-progress > span {{
    display: block;
    height: 100%;
    border-radius: 999px;
    background: linear-gradient(90deg, {c['teal']}, {c['teal_dark']});
}}
@media (max-width: 680px) {{
    .sx-order-row {{ grid-template-columns: 1fr; gap: 0.45rem; }}
    .sx-amount {{ text-align: left; }}
}}

.sx-table {{ width: 100%; border-collapse: collapse; }}
.sx-table th {{
    padding: 0.75rem 1.15rem;
    border-bottom: 1px solid {c['line']};
    color: {c['faint']};
    font-size: 0.68rem;
    font-weight: 760;
    letter-spacing: 0.09em;
    text-align: left;
    text-transform: uppercase;
}}
.sx-table td {{
    padding: 0.85rem 1.15rem;
    border-bottom: 1px solid #f1f2f4;
    color: {c['soft_ink']};
    font-size: 0.82rem;
    vertical-align: middle;
}}
.sx-table tr:last-child td {{ border-bottom: 0; }}
.sx-table .main {{ color: {c['ink']}; font-weight: 720; }}
.sx-table .right {{ text-align: right; white-space: nowrap; }}
.sx-chip {{
    display: inline-flex;
    align-items: center;
    height: 1.55rem;
    padding: 0 0.5rem;
    border-radius: 999px;
    background: {c['wash']};
    color: {c['muted']};
    font-size: 0.68rem;
    font-weight: 700;
}}
.sx-chip.ok {{ background: #ecfdf5; color: {c['teal_dark']}; }}

.sx-side-card {{
    border: 1px solid {c['line']};
    border-radius: 16px;
    background: #fff;
    overflow: hidden;
    box-shadow: 0 8px 24px rgba(17, 24, 39, 0.035);
    margin-bottom: 1rem;
}}
.sx-side-inner {{ padding: 1rem 1.1rem; }}
.sx-callout {{
    padding: 1rem 1.1rem;
    border-bottom: 1px solid {c['line']};
    background:
        linear-gradient(135deg, rgba(255,136,0,0.08), transparent 55%),
        #fff;
}}
.sx-callout .k {{
    margin: 0 0 0.3rem;
    color: {c['faint']};
    font-size: 0.68rem;
    font-weight: 760;
    letter-spacing: 0.12em;
    text-transform: uppercase;
}}
.sx-callout .v {{
    margin: 0;
    color: {c['ink']};
    font-size: 1.15rem;
    font-weight: 780;
    letter-spacing: -0.025em;
}}
.sx-mini-list {{ display: grid; gap: 0.72rem; }}
.sx-mini {{
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 1rem;
    padding-bottom: 0.72rem;
    border-bottom: 1px solid #f1f2f4;
}}
.sx-mini:last-child {{ border-bottom: 0; padding-bottom: 0; }}
.sx-mini span {{ color: {c['muted']}; font-size: 0.78rem; }}
.sx-mini strong {{ color: {c['ink']}; font-size: 0.86rem; }}
.sx-empty {{
    padding: 1.35rem;
    color: {c['muted']};
    font-size: 0.86rem;
    line-height: 1.5;
    background: {c['wash']};
}}

div[class*="st-key-sx_btn_"] {{
    margin: 0.62rem 0 0 !important;
}}
div[class*="st-key-sx_btn_"] + div[class*="st-key-sx_btn_"] {{
    margin-top: 0.48rem !important;
}}
div[class*="st-key-sx_btn_"] .stButton > button {{
    border-radius: 11px !important;
    min-height: 2.55rem !important;
    font-size: 0.84rem !important;
    font-weight: 720 !important;
    letter-spacing: -0.01em !important;
    box-shadow: 0 1px 2px rgba(17, 24, 39, 0.05) !important;
    transition: transform 0.16s ease, box-shadow 0.16s ease, background 0.16s ease, border-color 0.16s ease !important;
}}
div[class*="st-key-sx_btn_"] .stButton > button:hover {{
    transform: translateY(-1px) !important;
    box-shadow: 0 10px 22px rgba(17, 24, 39, 0.10) !important;
}}
div[class*="st-key-sx_btn_"] .stButton > button:active {{
    transform: translateY(0) !important;
    box-shadow: 0 3px 8px rgba(17, 24, 39, 0.08) !important;
}}
div[class*="st-key-sx_btn_primary"] .stButton > button {{
    background: linear-gradient(135deg, {c['teal']} 0%, {c['teal_dark']} 100%) !important;
    border-color: rgba(13, 148, 136, 0.9) !important;
    color: #fff !important;
}}
div[class*="st-key-sx_btn_primary"] .stButton > button:hover {{
    background: linear-gradient(135deg, #2dd4bf 0%, {c['teal_dark']} 100%) !important;
    border-color: {c['teal_dark']} !important;
}}
div[class*="st-key-sx_btn_orange"] .stButton > button {{
    background: linear-gradient(135deg, {c['orange']} 0%, #f97316 100%) !important;
    border-color: {c['orange']} !important;
    color: #fff !important;
}}
div[class*="st-key-sx_btn_orange"] .stButton > button:hover {{
    background: linear-gradient(135deg, #ff9a2e 0%, {c['orange']} 100%) !important;
    border-color: #f97316 !important;
}}
div[class*="st-key-sx_btn_plain"] .stButton > button {{
    background: linear-gradient(180deg, #ffffff 0%, #f9fafb 100%) !important;
    border: 1px solid {c['line_dark']} !important;
    color: {c['soft_ink']} !important;
}}
div[class*="st-key-sx_btn_plain"] .stButton > button:hover {{
    border-color: {c['teal']} !important;
    color: {c['teal_dark']} !important;
    background: #f0fdfa !important;
}}
</style>
<div id="sinlex-dashboard-page"></div>
"""


def _inject_layout() -> None:
    st.markdown(_css(), unsafe_allow_html=True)


def _account_name() -> str:
    company = (st.session_state.get("user_company") or "").strip()
    if company:
        return company
    email = (st.session_state.get("original_email") or st.session_state.get("user_email") or "").strip()
    return email.split("@", 1)[0] if "@" in email else (email or "Пользователь")


def _date_label() -> str:
    months = (
        "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря",
    )
    now = datetime.now()
    return f"{now.day} {months[now.month - 1]}"


def _project_has_pdf(user_folder: str, name: str, storage: str) -> bool:
    pdir = os.path.join(projects_base_dir(user_folder, storage=storage), _safe_dir_name(name))
    if not os.path.isdir(pdir):
        return False
    return any(fname.lower().endswith(".pdf") for fname in os.listdir(pdir))


def _is_analyzed(project: dict) -> bool:
    for key in ("total_cost", "machining_hours", "volume"):
        value = project.get(key)
        if value in (None, "", 0, "0"):
            continue
        try:
            if float(value) > 0:
                return True
        except (TypeError, ValueError):
            return True
    return False


def _recent_count(projects: list[dict], days: int = 7) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    total = 0
    for project in projects:
        dt = parse_project_datetime(project.get("created_at") or project.get("updated_at"))
        if dt and dt >= cutoff:
            total += 1
    return total


def _stats(user_folder: str, projects: list[dict], casting: list[dict]) -> dict:
    all_projects = projects + casting
    drawings = 0
    analyzed = 0
    for storage, items in (("projects", projects), ("casting", casting)):
        for project in items:
            name = (project.get("name") or "").strip()
            if not name:
                continue
            analyzed += 1 if _is_analyzed(project) else 0
            drawings += 1 if user_folder and _project_has_pdf(user_folder, name, storage) else 0
    return {
        "projects": len(projects),
        "casting": len(casting),
        "analyzed": analyzed,
        "drawings": drawings,
        "recent": _recent_count(all_projects),
    }


def _orders_meta(orders: list[dict]) -> dict:
    active = [o for o in orders if (o.get("stage") or "") != "completed"]
    amount = 0
    for order in orders:
        try:
            amount += int(float((order.get("payload") or {}).get("Общая стоимость") or 0))
        except (TypeError, ValueError):
            pass
    return {"active": len(active), "amount": amount, "by_stage": Counter(o.get("stage") or "placed" for o in orders)}


def _lathe_image_html() -> str:
    path = "/opt/sinlex/assets/lathe.png"
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("ascii")
    except OSError:
        return ""
    return (
        '<div class="sx-lathe-card">'
        f'<img class="sx-lathe-img" src="data:image/png;base64,{encoded}" alt="Токарная обработка">'
        '</div>'
    )

def _render_header(flow_balance: int, orders: list[dict], is_guest: bool) -> None:
    meta = _orders_meta(orders)
    flow_label = "—" if is_guest else f"{flow_balance:,} ₽".replace(",", " ")
    lathe_html = _lathe_image_html()
    st.markdown(
        f"""
<div class="sx sx-top">
  <div>
    <p class="sx-overline">Производственный контур Sinlex · {_esc(_date_label())}</p>
    <h1 class="sx-title">{_esc(_account_name())}</h1>
    <p class="sx-sub">Операционная сводка по расчётам, чертежам, заказам и балансу «Поток». Без тарифных ограничений: проекты можно создавать свободно.</p>
  </div>
  <div class="sx-top-right">
    {lathe_html}
    <div class="sx-statusbar">
      <span class="sx-pill"><span class="sx-dot"></span> Контур активен</span>
      <span class="sx-pill">Заказы в работе: <strong>{meta['active']}</strong></span>
      <span class="sx-pill flow">Поток: <strong>{_esc(flow_label)}</strong></span>
    </div>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )


def _render_summary(stats: dict, flow_balance: int, is_guest: bool) -> None:
    balance = "—" if is_guest else f"{flow_balance:,} ₽".replace(",", " ")
    st.markdown(
        f"""
<div class="sx sx-summary">
  <div class="sx-balance">
    <p class="label">Баланс «Поток»</p>
    <p class="value">{_esc(balance)}</p>
    <p class="note">Средства используются только для высокоточного анализа чертежей. Обычные 3D-проекты без лимитов.</p>
  </div>
  <div class="sx-scoregrid">
    <div class="sx-score"><p class="num">{stats['projects']}</p><p class="cap">3D-проектов в кабинете</p><span class="trend">+{stats['recent']} за 7 дней</span></div>
    <div class="sx-score"><p class="num">{stats['casting']}</p><p class="cap">литейных расчётов</p><span class="trend">ЛПД / литьё</span></div>
    <div class="sx-score"><p class="num">{stats['analyzed']}</p><p class="cap">проанализировано 3D-моделей</p><span class="trend">данные готовы</span></div>
    <div class="sx-score"><p class="num">{stats['drawings']}</p><p class="cap">чертежей в проектах</p><span class="trend">PDF / КД</span></div>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )


def _pipeline_html(orders: list[dict]) -> str:
    counts = _orders_meta(orders)["by_stage"]
    pieces = ['<div class="sx-pipeline">']
    for key, label in ORDER_STAGES:
        count = counts.get(key, 0)
        cls = "sx-step live" if count else "sx-step"
        pieces.append(
            f'<div class="{cls}"><span class="count">{count}</span><span class="name">{html.escape(label)}</span></div>'
        )
    pieces.append("</div>")
    return "".join(pieces)


def _order_rows_html(orders: list[dict]) -> str:
    if not orders:
        return '<div class="sx-empty">Заказов пока нет. После размещения они появятся здесь с производственным статусом.</div>'
    rows = []
    for order in orders[:4]:
        payload = order.get("payload") or {}
        title = order.get("project_name") or payload.get("Проект") or "Без названия"
        date = order.get("created_at_display") or payload.get("Дата") or "—"
        stage = order.get("stage") or "placed"
        amount = _money(payload.get("Общая стоимость"))
        pct = _stage_pct(stage)
        rows.append(
            f"""
<div class="sx-order-row">
  <div><p class="sx-name">{_esc(title)}</p><p class="sx-subtle">{_esc(date)}</p></div>
  <span class="sx-stage">{_esc(stage_label(stage))}</span>
  <div class="sx-amount">{_esc(amount)} ₽</div>
  <div class="sx-progress"><span style="width:{pct}%"></span></div>
</div>
            """
        )
    return "".join(rows)


def _render_orders(orders: list[dict]) -> None:
    st.markdown(
        f"""
<div class="sx sx-section">
  <div class="sx-section-head">
    <h2 class="sx-section-title">Производственный статус заказов</h2>
    <span class="sx-section-meta">{len(orders)} заказ(ов)</span>
  </div>
  {_pipeline_html(orders)}
  <div class="sx-section-body">{_order_rows_html(orders)}</div>
</div>
        """,
        unsafe_allow_html=True,
    )
    if orders:
        with st.container(key="sx_btn_plain_orders"):
            if st.button("Открыть все заказы", key="sx_open_orders", use_container_width=True):
                st.session_state.page = "orders"
                st.rerun()
    else:
        with st.container(key="sx_btn_orange_orders_empty"):
            if st.button("Создать расчёт для заказа", key="sx_empty_order_upload", use_container_width=True):
                st.session_state.page = "upload"
                st.rerun()


def _render_projects(projects: list[dict]) -> None:
    if not projects:
        body = '<div class="sx-empty">Проектов пока нет. Загрузите 3D-модель в формате STEP, чтобы получить расчёт стоимости и технологические данные.</div>'
    else:
        rows = []
        for project in projects[:6]:
            name = project.get("name") or "—"
            material = project.get("material") or "—"
            status = "Рассчитан" if _is_analyzed(project) else "Черновик"
            chip = "sx-chip ok" if status == "Рассчитан" else "sx-chip"
            cost = project.get("total_cost")
            cost_text = f"{_money(cost)} ₽" if cost not in (None, "", 0, "0") else "—"
            rows.append(
                f"<tr><td><span class=\"main\">{_esc(name)}</span><br><span class=\"sx-subtle\">{_esc(material)}</span></td>"
                f"<td><span class=\"{chip}\">{status}</span></td><td class=\"right\">{_esc(cost_text)}</td></tr>"
            )
        body = (
            '<table class="sx-table"><thead><tr><th>Проект</th><th>Готовность</th><th class="right">Стоимость</th></tr></thead><tbody>'
            + "".join(rows)
            + "</tbody></table>"
        )
    st.markdown(
        f"""
<div class="sx sx-section">
  <div class="sx-section-head">
    <h2 class="sx-section-title">Портфель расчётов</h2>
    <span class="sx-section-meta">последние проекты</span>
  </div>
  {body}
</div>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key="sx_btn_primary_projects"):
        if st.button("Перейти к проектам", key="sx_open_projects", use_container_width=True):
            st.session_state.page = "projects"
            st.rerun()


def _render_side_panel(stats: dict, orders: list[dict], flow_balance: int, is_guest: bool) -> None:
    meta = _orders_meta(orders)
    amount = _money(meta["amount"])
    low_balance = (flow_balance < 5000) and not is_guest
    next_text = "Пополнить баланс «Поток»" if low_balance else "Запустить новый расчёт"
    next_hint = "Баланс ниже рекомендуемого минимума" if low_balance else "Загрузите 3D-модель или откройте чертёж"
    st.markdown(
        f"""
<div class="sx sx-side-card">
  <div class="sx-callout"><p class="k">Следующее действие</p><p class="v">{_esc(next_text)}</p></div>
  <div class="sx-side-inner">
    <div class="sx-mini-list">
      <div class="sx-mini"><span>Причина</span><strong>{_esc(next_hint)}</strong></div>
      <div class="sx-mini"><span>Сумма заказов</span><strong>{amount} ₽</strong></div>
      <div class="sx-mini"><span>Данные в работе</span><strong>{stats['projects'] + stats['casting']} проектов</strong></div>
      <div class="sx-mini"><span>КД обработано</span><strong>{stats['drawings']} чертежей</strong></div>
    </div>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )

    with st.container(key="sx_btn_orange_upload"):
        if st.button("Новый расчёт 3D-модели", key="sx_upload", use_container_width=True):
            st.session_state.page = "upload"
            st.rerun()
    with st.container(key="sx_btn_primary_flow"):
        if st.button("Открыть «Поток»", key="sx_flow", use_container_width=True):
            st.session_state.page = "flow"
            st.rerun()
    if not is_guest:
        with st.container(key="sx_btn_plain_topup"):
            if st.button("Пополнить баланс", key="sx_topup", use_container_width=True):
                st.session_state.show_flow_topup_form = True
                st.rerun()
    with st.container(key="sx_btn_plain_casting"):
        if st.button("Литьевые проекты", key="sx_casting", use_container_width=True):
            st.session_state.project_domain = "casting"
            st.session_state.page = "casting"
            st.rerun()


def render() -> None:
    from page_shell import fetch_flow_balance, inject_unified_main_scroll, page_title, refresh_casting_list, refresh_projects_list

    page_title("Личный кабинет")
    inject_unified_main_scroll()
    _inject_layout()

    refresh_projects_list()
    refresh_casting_list()

    is_guest = st.session_state.get("guest_mode") or not st.session_state.get("user_email")
    user_folder = (st.session_state.get("user_folder") or "").strip()
    projects = st.session_state.get("projects") or []
    casting = st.session_state.get("casting_projects") or []
    orders = list_user_orders(user_folder) if user_folder else []
    flow_balance = 0 if is_guest else fetch_flow_balance()
    stats = _stats(user_folder, projects, casting)

    _render_header(flow_balance, orders, is_guest)
    _render_summary(stats, flow_balance, is_guest)

    left, right = st.columns([1.72, 0.88], gap="medium")
    with left:
        _render_orders(orders)
        _render_projects(projects)
    with right:
        _render_side_panel(stats, orders, flow_balance, is_guest)
