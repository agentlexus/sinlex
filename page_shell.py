"""Общие хелперы Streamlit-страниц (app.py и page_modules)."""
from __future__ import annotations

import html as html_module
import os

import requests
import streamlit as st

import payment as sinlex_payment
from utils import NGROK_URL, get_headers
from project_dates import sort_projects_by_created


def page_title(text: str) -> None:
    """Главный заголовок страницы (якорь верхней границы прокрутки)."""
    st.markdown('<div class="sinlex-page-top"></div>', unsafe_allow_html=True)
    st.title(text)




def inject_unified_main_scroll() -> None:
    """Один скролл в main + якорь page_title; clamp в app._inject_main_scroll_clamp()."""
    st.markdown(
        """
<style>
/* Единый скролл: без вложенных полос в main (сайдбар не трогаем) */
section[data-testid="stMain"] > div.block-container,
[data-testid="stMainBlockContainer"] {
    overflow: visible !important;
    max-height: none !important;
}
[data-testid="stMain"] [data-testid="stVerticalBlock"],
[data-testid="stStatusWidget"],
[data-testid="stForm"],
[data-testid="stExpander"] {
    overflow: visible !important;
}
/* Поля ввода: рамка не меняет высоту строки при наведении */
[data-testid="stNumberInput"] [data-baseweb="input"],
[data-testid="stSelectbox"] [data-baseweb="select"] > div,
[data-testid="stTextInput"] [data-baseweb="input"] {
    box-sizing: border-box !important;
    border-width: 1px !important;
}
[data-testid="stNumberInput"] [data-baseweb="input"]:hover,
[data-testid="stNumberInput"] [data-baseweb="input"]:focus-within,
[data-testid="stSelectbox"] [data-baseweb="select"]:hover,
[data-testid="stSelectbox"] [data-baseweb="select"]:focus-within,
[data-testid="stTextInput"] [data-baseweb="input"]:hover,
[data-testid="stTextInput"] [data-baseweb="input"]:focus-within {
    border-width: 1px !important;
}
</style>
        """,
        unsafe_allow_html=True,
    )

def refresh_projects_list() -> None:
    try:
        resp = requests.get(f"{NGROK_URL}/projects", headers=get_headers(), timeout=5)
        if resp.status_code == 200:
            st.session_state.projects = sort_projects_by_created(resp.json().get("projects", []))
    except Exception:
        pass


def refresh_casting_list() -> None:
    try:
        resp = requests.get(f"{NGROK_URL}/casting/projects", headers=get_headers(), timeout=5)
        if resp.status_code == 200:
            st.session_state.casting_projects = sort_projects_by_created(
                resp.json().get("projects", [])
            )
    except Exception:
        pass


def current_access_state() -> dict:
    if st.session_state.get("guest_mode") or not st.session_state.get("user_email"):
        return {"active": False, "reason": "guest"}
    return sinlex_payment.get_user_access_state(st.session_state.user_email)


def tariff_wall_message(access: dict) -> str:
    return ""


def api_public_browser_url() -> str:
    return os.environ.get("SINLEX_API_PUBLIC", "").strip().rstrip("/")


def show_flow_topbar() -> bool:
    return bool(st.session_state.get("user_email")) and not st.session_state.get("guest_mode")


_FLOW_TOPBAR_CSS = """
<style>
/* Фиксированная верхняя строка «Баланс» (прокрутка в stAppViewContainer, sticky не работает) */
[class*="st-key-app_topbar_flow"] {
    position: fixed !important;
    top: 0 !important;
    left: 270px !important;
    right: 0 !important;
    width: auto !important;
    z-index: 999 !important;
    background: #ffffff !important;
    border-bottom: 1px solid #e8eaed;
    margin: 0 !important;
    padding: 0.4rem 1.75rem 0.5rem 1.25rem !important;
    box-shadow: 0 2px 6px rgba(15, 23, 42, 0.06);
    box-sizing: border-box !important;
}
@media (max-width: 768px) {
    [class*="st-key-app_topbar_flow"] {
        left: 0 !important;
    }
}
section[data-testid="stMain"] > div.block-container,
[data-testid="stMainBlockContainer"] {
    padding-top: var(--sinlex-topbar-h, 3rem) !important;
}

.sinlex-topbar-user {
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: flex-end;
    gap: 0.05rem;
    min-width: 0;
    max-width: 100%;
    line-height: 1.2;
    text-align: right;
}
.sinlex-topbar-user-name {
    font-weight: 600;
    font-size: 0.9rem;
    color: #1e293b;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.sinlex-topbar-user-email {
    font-size: 0.78rem;
    color: #64748b;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
[class*="st-key-app_topbar_flow"] [data-testid="stHorizontalBlock"] {
    flex-direction: row !important;
    flex-wrap: nowrap !important;
    align-items: center !important;

    width: 100% !important;
}
[class*="st-key-app_topbar_flow"] [data-testid="column"]:first-child,
[class*="st-key-app_topbar_flow"] [data-testid="stColumn"]:first-child {
    flex: 1 1 auto !important;
    min-width: 0 !important;
}
[class*="st-key-app_topbar_flow"] [data-testid="column"]:nth-child(2),
[class*="st-key-app_topbar_flow"] [data-testid="stColumn"]:nth-child(2) {
    flex: 0 0 auto !important;
    min-width: 0 !important;
    max-width: none !important;
    text-align: right !important;
    overflow: visible !important;
    display: flex !important;
    justify-content: flex-end !important;
}
.st-key-topbar_user_popover {
    width: auto !important;
    min-width: max-content !important;
}
.st-key-topbar_user_popover .stPopover > button {
    padding: 0.35rem 0.45rem !important;
    gap: 0.2rem !important;
}
.st-key-topbar_user_popover .stPopover > button > div {
    gap: 0.2rem !important;
    padding: 0 !important;
    margin: 0 !important;
}
.st-key-topbar_user_popover [data-testid="stElementContainer"],
.st-key-topbar_user_popover [data-testid="stVerticalBlock"] {
    padding-left: 0 !important;
    padding-right: 0 !important;
    margin-left: 0 !important;
    margin-right: 0 !important;
}

.st-key-topbar_user_popover .stPopover {
    width: auto !important;
    min-width: max-content !important;
}
.sinlex-topbar-user {
    margin-left: auto;
    align-items: flex-end;
}


/* Не обрезать рамку/тень кнопки в popover «Баланс» */
[class*="st-key-global_flow_balance_popover"] [data-testid="stElementContainer"],
[class*="st-key-global_flow_balance_popover"] [data-testid="stVerticalBlock"],
[class*="st-key-global_flow_balance_popover"] .stButton,
div[class*="st-key-global_flow_topup_btn"],
div[class*="st-key-global_flow_topup_btn"] > div {
    overflow: visible !important;
    padding-bottom: 3px !important;
    padding-left: 2px !important;
}
div[class*="st-key-global_flow_topup_btn"] button {
    margin-bottom: 1px !important;
    margin-left: 1px !important;
}

/* Кнопка пополнения в popover «Баланс» — как «Поток» */
div[class*="st-key-global_flow_topup_btn"] button[kind="secondary"],
div[class*="st-key-global_flow_topup_btn"] button {
    width: auto !important;
    max-width: 12rem !important;
    display: inline-flex !important;
    justify-content: center !important;
    background-color: #14b8a6 !important;
    border-color: #14b8a6 !important;
    color: #ffffff !important;
}
div[class*="st-key-global_flow_topup_btn"] button:hover:not(:disabled) {
    background-color: #0d9488 !important;
    border-color: #0d9488 !important;
    color: #ffffff !important;
}
div[class*="st-key-global_flow_topup_btn"] button:focus:not(:disabled) {
    box-shadow: 0 0 0 0.2rem rgba(20, 184, 166, 0.45) !important;
}
div[class*="st-key-global_flow_topup_btn"] button:disabled {
    background-color: #99f6e4 !important;
    border-color: #99f6e4 !important;
    color: #ffffff !important;
    opacity: 0.85;
}
div[class*="st-key-global_flow_topup_btn"] button p,
div[class*="st-key-global_flow_topup_btn"] button div {
    color: #ffffff !important;
}

[class*="st-key-app_topbar_flow"] .stPopover > button,
[class*="st-key-global_flow_balance_popover"] button {
    display: inline-flex !important;
    flex-direction: row !important;
    align-items: center !important;
    justify-content: center !important;
    gap: 0.35rem !important;
    white-space: nowrap !important;
    font-weight: 600 !important;
}
[class*="st-key-app_topbar_flow"] .stPopover > button > div,
[class*="st-key-global_flow_balance_popover"] button > div {
    display: inline-flex !important;
    flex-direction: row !important;
    align-items: center !important;
    gap: 0.35rem !important;
}
[class*="st-key-app_topbar_flow"] .stPopover > button p,
[class*="st-key-global_flow_balance_popover"] button p {
    margin: 0 !important;
    display: inline !important;
}

[class*="st-key-app_topbar_flow"],
[class*="st-key-app_topbar_flow"] [data-testid="stVerticalBlock"],
[class*="st-key-app_topbar_flow"] [data-testid="stHorizontalBlock"],
[class*="st-key-app_topbar_flow"] [data-testid="column"],
[class*="st-key-app_topbar_flow"] [data-testid="stColumn"],
[class*="st-key-app_topbar_flow"] .stPopover,
[class*="st-key-global_flow_balance_popover"] {
    overflow: visible !important;
}
[class*="st-key-app_topbar_flow"] [data-testid="column"]:last-child,
[class*="st-key-app_topbar_flow"] [data-testid="stColumn"]:last-child {
    min-width: max-content !important;
    flex: 0 0 auto !important;
    width: auto !important;
    overflow: visible !important;
    padding-right: 0.25rem !important;
}
[class*="st-key-app_topbar_flow"] .stPopover {
    width: auto !important;
    min-width: max-content !important;
}
[class*="st-key-app_topbar_flow"] .stPopover > button,
[class*="st-key-global_flow_balance_popover"] button {
    padding: 0.45rem 0.85rem !important;
    min-width: max-content !important;
    width: auto !important;
    max-width: none !important;
    overflow: visible !important;
}
</style>
"""




def topbar_user_data() -> tuple[str, str]:
    """(company, email) for topbar user area."""
    company = (st.session_state.get("user_company") or "").strip()
    email = (
        st.session_state.get("original_email")
        or st.session_state.get("user_email")
        or ""
    ).strip()
    return company, email



def fetch_flow_balance() -> int:
    """Баланс «Поток» в рублях (кеш в session_state)."""
    email = (st.session_state.get("user_email") or "").strip()
    if not email or st.session_state.get("guest_mode"):
        return 0
    try:
        resp = requests.get(
            f"{NGROK_URL}/payments/flow-balance",
            headers=get_headers(),
            timeout=15,
        )
        if resp.status_code == 200:
            bal = int(resp.json().get("balance") or 0)
            st.session_state.flow_balance_cache = bal
            return bal
    except Exception:
        pass
    return int(st.session_state.get("flow_balance_cache") or 0)

def render_app_flow_balance_bar() -> None:
    """Верхняя строка приложения: виджет «Баланс» (все страницы после входа)."""
    if not show_flow_topbar():
        return
    st.markdown(_FLOW_TOPBAR_CSS, unsafe_allow_html=True)
    flow_bal = fetch_flow_balance()
    with st.container(key="app_topbar_flow"):
        _spacer, col_user, col_bal = st.columns(
            [1, 0.22, 0.2], gap="xsmall", vertical_alignment="center"
        )
        with col_user:
            company, email = topbar_user_data()
            if company or email:
                name = email or company or "Пользователь"
                with st.popover(name, key="topbar_user_popover"):
                    if company:
                        st.caption(company)
                    if email:
                        st.markdown(email)
                    elif not company:
                        st.caption("Email не задан")
        with col_bal:
            with st.popover("Баланс", icon="🌀", key="global_flow_balance_popover"):
                st.metric('Режим "Поток"', f"{flow_bal:,} ₽".replace(",", " "))
                st.caption("Баланс используется для анализа чертежей.")
                if st.button(
                    "Пополнить баланс",
                    key="global_flow_topup_btn",
                    use_container_width=True,
                ):
                    st.session_state.show_flow_topup_form = True
                    st.rerun()
    # Отступ под фиксированный topbar — CSS var(--sinlex-topbar-h), без отдельного DOM-узла


def start_flow_topup(amount: int) -> None:
    """Создать платёж ЮKassa на пополнение баланса «Поток»."""
    sid = st.session_state.get("auth_sid") or ""
    resp = requests.post(
        f"{NGROK_URL}/payments/flow-topup",
        json={"amount": int(amount), "return_sid": sid},
        headers=get_headers(),
        timeout=30,
    )
    if resp.status_code != 200:
        detail = resp.json().get("detail", resp.text)
        raise RuntimeError(detail if isinstance(detail, str) else str(detail))
    payload = resp.json()
    pid = payload.get("payment_id")
    url = (payload.get("confirmation_url") or "").strip()
    if not url:
        raise RuntimeError("Не получена ссылка на оплату.")
    st.session_state.pending_payment_id = pid
    st.session_state.pending_payment_purpose = sinlex_payment.PURPOSE_FLOW_TOKENS
    st.session_state.payment_redirect_url = url
    st.session_state.show_flow_topup_form = False


def maybe_redirect_to_yookassa() -> None:
    """Переход на страницу оплаты ЮKassa (с любой страницы приложения)."""
    url = (st.session_state.pop("payment_redirect_url", None) or "").strip()
    if not url:
        return
    safe = html_module.escape(url, quote=True)
    st.markdown(
        f'<meta http-equiv="refresh" content="0;url={safe}">',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<p style="margin:1rem 0;">Переход на оплату… '
        f'<a href="{safe}">Открыть страницу ЮKassa</a></p>',
        unsafe_allow_html=True,
    )
    st.stop()


def _on_flow_topup_dialog_dismiss() -> None:
    st.session_state.show_flow_topup_form = False


@st.dialog(
    "Пополнение баланса «Поток»",
    width="small",
    icon="🌀",
    on_dismiss=_on_flow_topup_dialog_dismiss,
)
def flow_topup_dialog() -> None:
    st.caption("Зачисление на баланс после успешной оплаты")
    with st.form("flow_topup_dialog_form", clear_on_submit=False):
        amount = st.number_input(
            "Сумма, ₽",
            min_value=sinlex_payment.FLOW_TOPUP_MIN_AMOUNT,
            value=sinlex_payment.FLOW_TOPUP_MIN_AMOUNT,
            step=sinlex_payment.FLOW_RUB_PER_TOKEN,
            help=f"Минимум {sinlex_payment.FLOW_TOPUP_MIN_AMOUNT} ₽",
        )
        submitted = st.form_submit_button(
            "Оплатить картой (ЮKassa)",
            type="primary",
            use_container_width=True,
        )
    if st.button("Отмена", key="flow_topup_dialog_cancel", use_container_width=True):
        st.session_state.show_flow_topup_form = False
        st.rerun()
    st.info("Оплата по счёту для юр.лиц — скоро.")
    if submitted:
        try:
            start_flow_topup(int(amount))
            st.rerun()
        except Exception as exc:
            st.error(str(exc))


def render_flow_topup_dialog_if_open() -> None:
    """Модальное окно пополнения поверх текущей страницы."""
    if not st.session_state.get("show_flow_topup_form"):
        return
    if st.session_state.get("guest_mode") or not st.session_state.get("user_email"):
        st.session_state.show_flow_topup_form = False
        return
    flow_topup_dialog()
