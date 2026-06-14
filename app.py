import streamlit as st
import base64
import requests
import os
import json
import datetime
import hashlib
import shutil
import math
import re
import urllib.parse
from pathlib import Path
import html as html_module
import textwrap

from auth_store import create_session, get_session
from legal._terms import render_terms_page
from legal._privacy import render_privacy_page

import payment as sinlex_payment

from utils import (
    API_KEY,
    NGROK_URL,
    get_headers,
    transliterate,
)

sinlex_payment.load_env()

st.set_page_config(page_title="AI Технолог", page_icon="/opt/sinlex/static/favicon.ico", layout="wide", initial_sidebar_state="auto")

# Скрываем меню Streamlit; запрет горизонтальной прокрутки
st.markdown("""
<style>
    [data-testid="stToolbar"] { display: none; }

    /* Десктоп: сайдбар всегда развёрнут (270px), без кнопки сворачивания */
    @media (min-width: 769px) {
        [data-testid="stSidebar"] {
            transform: none !important;
            visibility: visible !important;
            min-width: 270px !important;
            max-width: 270px !important;
            width: 270px !important;
        }
        [data-testid="stSidebarCollapseButton"],
        [data-testid="stSidebarCollapsedControl"] {
            display: none !important;
            pointer-events: none !important;
        }
    }

    /* Смартфон: drawer, main на всю ширину; кнопка меню видна */
    @media (max-width: 768px) {
        [data-testid="stSidebarCollapseButton"],
        [data-testid="stSidebarCollapsedControl"] {
            display: flex !important;
            pointer-events: auto !important;
            z-index: 1001 !important;
        }
        [data-testid="stSidebar"] {
            min-width: unset !important;
            max-width: min(20rem, 88vw) !important;
            width: min(20rem, 88vw) !important;
            z-index: 1000 !important;
            box-shadow: 4px 0 24px rgba(15, 23, 42, 0.18);
        }
        [data-testid="stMain"] {
            margin-left: 0 !important;
            width: 100% !important;
            max-width: 100vw !important;
        }
    }

    html, body {
        overflow-x: hidden !important;
        max-width: 100vw !important;
    }
    [data-testid="stApp"],
    [data-testid="stAppViewContainer"],
    [data-testid="stMain"],
    [data-testid="stMainBlockContainer"],
    .main,
    .block-container,
    [data-testid="stVerticalBlock"],
    [data-testid="stHorizontalBlock"] {
        overflow-x: hidden !important;
        max-width: 100% !important;
    }
    [data-testid="stSidebar"] {
        overflow-x: hidden !important;
    }
    html, body,
    [data-testid="stAppViewContainer"],
    [data-testid="stMain"] {
        overscroll-behavior: none !important;
        overscroll-behavior-y: none !important;
    }
</style>
""", unsafe_allow_html=True)


from page_shell import (
    api_public_browser_url,
    current_access_state as _current_access_state,
    page_title as _page_title,
    refresh_projects_list as _refresh_projects_list,
    render_app_flow_balance_bar as _render_app_flow_balance_bar,
    maybe_redirect_to_yookassa as _maybe_redirect_to_yookassa,
    render_flow_topup_dialog_if_open as _render_flow_topup_dialog_if_open,
)

API_PUBLIC_BROWSER = api_public_browser_url()


def _inject_main_scroll_clamp() -> None:
    """Отключён JS-кламп прокрутки (во избежание конфликтов React)."""
    return


# ========== СТЕНА ВХОДА ==========
if "user_email" not in st.session_state:
    st.session_state.user_email = None
if "user_folder" not in st.session_state:
    st.session_state.user_folder = None
if "guest_mode" not in st.session_state:
    st.session_state.guest_mode = False
if "auth_sid" not in st.session_state:
    st.session_state.auth_sid = None


def _apply_session(sess: dict, sid: str) -> None:
    new_owner = (sess.get("folder") or sess.get("email") or "").strip()
    if (
        st.session_state.get("agent_sinlex_owner")
        and new_owner
        and st.session_state.get("agent_sinlex_owner") != new_owner
    ):
        _agent_sinlex_clear_session()
    st.session_state.user_email = sess["email"]
    st.session_state.original_email = sess.get("original_email", sess["email"])
    st.session_state.user_folder = sess["folder"]
    st.session_state.user_company = sess.get("company", "")
    st.session_state.auth_sid = sid
    st.session_state.guest_mode = False


def _load_accounts():
    with open("/opt/sinlex/accounts.json", encoding="utf-8") as f:
        return json.load(f)


def _restore_auth_from_storage() -> bool:
    """Восстановить вход по sid в URL или cookie (не трогаем session_state Streamlit)."""
    if st.session_state.user_email or st.session_state.guest_mode:
        return True

    sid = st.query_params.get("sid")
    if not sid:
        try:
            from streamlit.runtime.scriptrunner import get_script_run_ctx

            if get_script_run_ctx() is not None:
                sid = st.context.cookies.get("sinlex_sid")
        except Exception:
            sid = None

    if sid:
        sess = get_session(sid)
        if sess:
            _apply_session(sess, sid)
            if st.query_params.get("sid") != sid:
                st.query_params["sid"] = sid
            return True
        if "sid" in st.query_params:
            del st.query_params["sid"]

    # Миграция со старого token=base64(email)
    legacy = st.query_params.get("token")
    if legacy:
        try:
            decoded = base64.b64decode(legacy.encode()).decode()
            acc = _load_accounts().get(decoded)
            if acc:
                sid = create_session(
                    decoded,
                    acc["folder"],
                    acc.get("company_name", ""),
                    acc.get("original_email", decoded),
                )
                _apply_session(get_session(sid), sid)
                del st.query_params["token"]
                st.query_params["sid"] = sid
                st.rerun()
        except Exception:
            pass

    return False


def _set_auth_cookie(sid: str) -> None:
    """Дублируем sid в cookie — запасной канал, если Streamlit сохранил контекст."""
    try:
        st.html(
            f'<script>document.cookie="sinlex_sid={sid};path=/;max-age={30 * 24 * 3600};SameSite=Lax";</script>',
        )
    except Exception:
        pass


def _login_user(key_email: str, acc: dict, display_email: str) -> None:
    sid = create_session(
        key_email,
        acc["folder"],
        acc.get("company_name", ""),
        acc.get("original_email", display_email),
    )
    _apply_session(get_session(sid), sid)
    st.query_params["sid"] = sid
    if "token" in st.query_params:
        del st.query_params["token"]
    _set_auth_cookie(sid)
    st.rerun()


# Демо-режим (не сбрасываем остальные query-параметры)
if st.query_params.get("demo") == "1":
    st.session_state.guest_mode = True
    if "demo" in st.query_params:
        del st.query_params["demo"]

_restore_auth_from_storage()

authorized = st.session_state.user_email is not None or st.session_state.guest_mode

if not authorized:
    st.markdown("""
    <style>
        body, .main, .block-container { background-color: #ffffff !important; overflow: hidden; }
        [data-testid="stSidebar"] { display: none !important; }
        section[data-testid="stSidebarContent"] { display: none !important; }
        header[data-testid="stHeader"] {
            height: auto !important;
            min-height: unset !important;
            visibility: visible !important;
            pointer-events: auto !important;
        }
        section[data-testid="stMain"] > div.block-container {
            width: clamp(360px, 40vw, 840px) !important;
            max-width: clamp(360px, 40vw, 840px) !important;
            min-width: unset !important;
            margin-left: auto !important;
            margin-right: auto !important;
            padding-top: 2rem !important;
            text-align: center !important;
        }
        section[data-testid="stMain"] [data-testid="stVerticalBlock"],
        section[data-testid="stMain"] [data-testid="stForm"],
        section[data-testid="stMain"] .stTextInput,
        section[data-testid="stMain"] .stButton {
            max-width: 100% !important;
        }
        .stImage, h1 { text-align: center; }
        div[data-testid="stForm"] { width: 100%; }
        .stTextInput, .stButton { text-align: center; }
    </style>
    """, unsafe_allow_html=True)
    logo_path = "/opt/sinlex/static/logo.svg"
    if os.path.exists(logo_path):
        st.markdown(f"<div style='text-align: center; margin-top: 10px; position: relative; left: 8px;'><img src='data:image/svg+xml;base64,{__import__('base64').b64encode(open(logo_path, 'rb').read()).decode()}' width='130'></div>", unsafe_allow_html=True)
    st.markdown("<div style='text-align: center; font-size: 2.5rem; font-weight: bold; margin-bottom: 1rem;'>Вход</div>", unsafe_allow_html=True)
    _legal_view = st.query_params.get("legal") or st.query_params.get("nav")
    if _legal_view == "terms":
        render_terms_page()
        if st.button("← К входу", key="login_back_terms"):
            for _p in ("legal", "nav"):
                if _p in st.query_params:
                    del st.query_params[_p]
            st.rerun()
        st.stop()
    if _legal_view == "privacy":
        render_privacy_page()
        if st.button("← К входу", key="login_back_privacy"):
            for _p in ("legal", "nav"):
                if _p in st.query_params:
                    del st.query_params[_p]
            st.rerun()
        st.stop()
    show_register = (st.query_params.get("register") == "Sinlex2026")
    tab1, tab2 = st.tabs(["Вход", "Регистрация компании"])
    if not show_register:
        st.markdown("<style>div[data-baseweb='tab-list'] button:nth-child(2) { display: none; }</style>", unsafe_allow_html=True)
    
    with tab1:
        with st.form("login_form"):
            email = st.text_input("Email", key="login_email")
            password = st.text_input("Пароль", type="password", key="login_password")
            if st.form_submit_button("Войти"):
                def hash_pw(pw):
                    return hashlib.pbkdf2_hmac("sha256", pw.encode(), b"sinlex_salt_static", 100000).hex()
                try:
                    with open("/opt/sinlex/accounts.json") as f:
                        accounts = json.load(f)
                    # Ищем по транслитерированному ключу
                    key_email = transliterate(email)
                    acc = accounts.get(key_email)
                    if acc and acc["password_hash"] == hash_pw(password):
                        _login_user(key_email, acc, email)
                    else:
                        st.error("Неверный email или пароль")
                except Exception as e:
                    st.error(f"Ошибка: {e}")
    
    with tab2:
        with st.form("register_form"):
            company_name = st.text_input("Название компании *", key="reg_company")
            new_email = st.text_input("Email администратора *", key="reg_email")
            new_password = st.text_input("Пароль *", type="password", key="reg_password")
            if st.form_submit_button("Зарегистрироваться"):
                def hash_pw(pw):
                    return hashlib.pbkdf2_hmac("sha256", pw.encode(), b"sinlex_salt_static", 100000).hex()
                try:
                    with open("/opt/sinlex/accounts.json") as f:
                        accounts = json.load(f)
                except:
                    accounts = {}
                key_email = transliterate(new_email)
                if key_email in accounts:
                    st.error("Email уже занят")
                elif not company_name or not company_name.strip():
                    st.error("Название компании обязательно")
                elif not new_password:
                    st.error("Пароль обязателен")
                else:
                    # Формируем папку из названия компании
                    safe_folder = transliterate(re.sub(r'[^a-zA-Zа-яА-Я0-9 _-]', '', company_name))
                    safe_folder = safe_folder.strip().replace(' ', '_').lower()
                    if not safe_folder:
                        safe_folder = transliterate(new_email.replace("@", "_").replace(".", "_"))
                    
                    # Проверяем существующую компанию
                    existing_company = None
                    for acc in accounts.values():
                        if acc.get("folder") == safe_folder:
                            existing_company = acc.get("company_name", company_name.strip())
                            break
                    
                    if existing_company:
                        accounts[key_email] = {
                            "password_hash": hash_pw(new_password),
                            "company_name": existing_company,
                            "folder": safe_folder,
                            "original_email": new_email
                        }
                        with open("/opt/sinlex/accounts.json", "w") as f:
                            json.dump(accounts, f, indent=2)

                        st.success(f"Вы присоединились к компании «{existing_company}». Теперь войдите.")
                    else:
                        accounts[key_email] = {
                            "password_hash": hash_pw(new_password),
                            "company_name": company_name.strip(),
                            "folder": safe_folder,
                            "original_email": new_email
                        }
                        os.makedirs(os.path.join("/opt/sinlex/projects", safe_folder), exist_ok=True)
                        with open("/opt/sinlex/accounts.json", "w") as f:
                            json.dump(accounts, f, indent=2)

                        st.success("Регистрация успешна! Теперь войдите.")
    st.markdown("---")
    _lc1, _lc2 = st.columns(2)
    with _lc1:
        if st.button("Условия использования ↘", key="login_link_terms", use_container_width=True):
            st.query_params["legal"] = "terms"
            st.rerun()
    with _lc2:
        if st.button("Политика конфиденциальности ↘", key="login_link_privacy", use_container_width=True):
            st.query_params["legal"] = "privacy"
            st.rerun()
    st.stop()

# ========== КОНЕЦ СТЕНЫ ==========

st.markdown("""
<style>
.project-row { background-color: #ffffff; border-radius: 8px; padding: 8px; margin: 4px 0; }
.project-row:hover { background-color: #e9ecef; }
[data-testid="stMainBlockContainer"] button[kind="tertiary"] { text-align: left !important; padding-left: 0 !important; font-weight: 600 !important; font-size: 14px !important; color: #1a73e8 !important; background: none !important; border: none !important; width: 100% !important; }
button[kind="secondary"] { background: none !important; border: none !important; box-shadow: none !important; padding: 2px 4px !important; font-size: 16px !important; }

[data-testid="stMainBlockContainer"] .st-key-projects_new_btn button[kind="secondary"],
[data-testid="stMainBlockContainer"] .st-key-projects_new_btn button[kind="primary"],
[data-testid="stMainBlockContainer"] .st-key-projects_new_btn button {
    background-color: #ff8800 !important;
    background: #ff8800 !important;
    border: 1px solid #ff8800 !important;
    border-color: #ff8800 !important;
    color: #ffffff !important;
    box-shadow: none !important;
    padding: 0.45rem 1rem !important;
    font-size: 14px !important;
    font-weight: 600 !important;
    min-height: 2.5rem !important;
}
[data-testid="stMainBlockContainer"] .st-key-projects_new_btn button[kind="primary"]:hover,
[data-testid="stMainBlockContainer"] .st-key-projects_new_btn button:hover {
    background-color: #595957 !important;
    background: #595957 !important;
    border-color: #595957 !important;
    color: #ffffff !important;
}
[data-testid="stMainBlockContainer"] .st-key-projects_new_btn button[kind="primary"]:focus,
[data-testid="stMainBlockContainer"] .st-key-projects_new_btn button:focus {
    background-color: #ff8800 !important;
    border-color: #ff8800 !important;
    color: #ffffff !important;
    box-shadow: 0 0 0 0.2rem rgba(255, 136, 0, 0.35) !important;
}
    [data-testid="stMainBlockContainer"] div[data-testid="stButton"] button[kind="tertiary"] {
        display: flex;
        justify-content: flex-start;
    }
</style>
""", unsafe_allow_html=True)

if "page" not in st.session_state: st.session_state.page = "dashboard"
_nav = st.query_params.get("nav")
if _nav in ("terms", "privacy"):
    st.session_state.page = _nav
    if "nav" in st.query_params:
        del st.query_params["nav"]
_page_qp = (st.query_params.get("page") or "").strip().replace("-", "_")
if _page_qp == "payment_success":
    st.session_state.page = "flow"
elif _page_qp == "payment":
    st.session_state.page = "flow"
    st.session_state.show_flow_topup_form = True
if st.session_state.get("page") == "agent_lexus":
    st.session_state.page = "agent_sinlex"
if st.query_params.get("payment_id"):
    st.session_state.pending_payment_id = st.query_params.get("payment_id")


def _handle_payment_return_after_yookassa() -> None:
    """После возврата с ЮKassa (?sid=...) — проверить платёж без page=payment_success."""
    if st.session_state.get("yookassa_return_checked"):
        return
    if st.session_state.get("guest_mode") or not st.session_state.get("user_email"):
        return
    page_qp = (st.query_params.get("page") or "").strip().replace("-", "_")
    if page_qp == "payment_success":
        return
    st.session_state.yookassa_return_checked = True

    payment_id = (
        st.session_state.get("pending_payment_id")
        or st.query_params.get("payment_id")
        or ""
    ).strip()
    if not payment_id:
        try:
            pr = requests.get(
                f"{NGROK_URL}/payments/pending",
                headers=get_headers(),
                timeout=15,
            )
            if pr.status_code == 200 and pr.json().get("pending"):
                payment_id = (pr.json()["pending"] or {}).get("payment_id") or ""
        except Exception:
            payment_id = ""
    if not payment_id:
        return

    st.session_state.pending_payment_id = payment_id
    try:
        sr = requests.get(
            f"{NGROK_URL}/payments/status/{payment_id}",
            headers=get_headers(),
            timeout=15,
        )
        status = "unknown"
        if sr.status_code == 200:
            status = (sr.json().get("status") or "unknown").strip()

        if status == "canceled":
            st.session_state.pop("pending_payment_id", None)
            st.session_state.payment_return_notice = (
                "info",
                "Оплата отменена.",
            )
            return
        if status == "pending":
            st.session_state.payment_return_notice = (
                "warning",
                "Платёж ещё не завершён. Обновите страницу после оплаты.",
            )
            return
        if status != "succeeded":
            st.session_state.payment_return_notice = (
                "info",
                "Оплата не завершена." if status == "unknown" else f"Статус платежа: {status}",
            )
            return

        cr = requests.post(
            f"{NGROK_URL}/payments/confirm/{payment_id}",
            headers=get_headers(),
            timeout=30,
        )
        if cr.status_code == 200:
            result = cr.json().get("result") or {}
            purpose = (
                st.session_state.get("pending_payment_purpose")
                or result.get("purpose")
                or ""
            )
            if purpose == "flow_tokens" or result.get("purpose") == "flow_tokens":
                credited = result.get("credited")
                balance = result.get("balance")
                if result.get("already_credited"):
                    st.session_state.payment_return_notice = (
                        "success",
                        f"Баланс пополнен. На счёте: **{balance:,} ₽**.".replace(",", " "),
                    )
                elif balance is not None:
                    amt = credited if credited is not None else ""
                    released = result.get("released") or []
                    rel_note = ""
                    if released:
                        rel_note = f" Разблокировано результатов «Поток»: **{len(released)}**."
                    st.session_state.payment_return_notice = (
                        "success",
                        f"Зачислено **{amt:,} ₽**. Баланс: **{balance:,} ₽**.{rel_note}".replace(",", " "),
                    )
                else:
                    st.session_state.payment_return_notice = (
                        "warning",
                        "Платёж получен. Средства зачислятся в течение минуты.",
                    )
                st.session_state.pop("flow_balance_cache", None)
                st.session_state["flow_pending_unlock_after_topup"] = True
            st.session_state.pop("pending_payment_id", None)
            st.session_state.pop("pending_payment_purpose", None)
        else:
            detail = cr.json().get("detail", "Не удалось подтвердить платёж")
            if isinstance(detail, str) and "canceled" in detail.lower():
                st.session_state.pop("pending_payment_id", None)
                st.session_state.payment_return_notice = (
                    "info",
                    "Оплата отменена.",
                )
            else:
                st.session_state.payment_return_notice = ("error", str(detail))
    except Exception as exc:
        st.session_state.payment_return_notice = ("error", f"Ошибка проверки: {exc}")


_handle_payment_return_after_yookassa()

if "projects" not in st.session_state: st.session_state.projects = []
if "selected_project" not in st.session_state: st.session_state.selected_project = None
if "cached_step" not in st.session_state: st.session_state.cached_step = None
if "cached_step_name" not in st.session_state: st.session_state.cached_step_name = None
if "auto_process" not in st.session_state: st.session_state.auto_process = False
if "projects_loaded" not in st.session_state:
    try:
        resp = requests.get(f"{NGROK_URL}/projects", headers=get_headers(), timeout=5)
        if resp.status_code == 200:
            st.session_state.projects = sort_projects_by_created(resp.json().get("projects", []))
    except: pass
    st.session_state.projects_loaded = True

def _agent_sinlex_enabled() -> bool:
    for var in ("SINLEX_ENABLE_AGENT_SINLEX", "SINLEX_ENABLE_AGENT_LEXUS"):
        if os.environ.get(var, "").strip().lower() in ("1", "true", "yes"):
            return True
    return False


def _agent_sinlex_clear_session() -> None:
    import importlib.util

    _path = Path(__file__).resolve().parent / "page_modules" / "4_Agent_Sinlex.py"
    _spec = importlib.util.spec_from_file_location("sinlex_page_agent_sinlex", _path)
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    _mod.clear_page_session_state()


def _sidebar_nav_css(active_key: str = "") -> str:
    """Стили навигации в сайдбаре: только фон, цвет текста не меняем."""
    nav_keys = (
        "nav_dashboard",
        "nav_projects",
        "nav_casting",
        "nav_flow",
        "nav_orders",
        "nav_agent_sinlex",
    )
    menu_keys = nav_keys + ("logout_btn",)
    scope = '[data-testid="stSidebar"]'
    text_color = "rgb(49, 51, 63)"
    btn = ",\n".join(
        f"{scope} .st-key-{k} button, {scope} [class*=\"st-key-{k}\"] button" for k in menu_keys
    )
    btn_text = ",\n".join(
        f"{scope} .st-key-{k} button p, {scope} .st-key-{k} button div, "
        f"{scope} [class*=\"st-key-{k}\"] button p, {scope} [class*=\"st-key-{k}\"] button div"
        for k in menu_keys
    )
    hover = ",\n".join(
        f"{scope} .st-key-{k} button:hover, {scope} [class*=\"st-key-{k}\"] button:hover"
        for k in menu_keys
    )
    hover_text = ",\n".join(
        f"{scope} .st-key-{k} button:hover p, {scope} .st-key-{k} button:hover div, "
        f"{scope} [class*=\"st-key-{k}\"] button:hover p, "
        f"{scope} [class*=\"st-key-{k}\"] button:hover div"
        for k in menu_keys
    )
    css = f"""
{btn} {{
    border-radius: 6px !important;
    padding: 0.45rem 0.6rem 0.45rem 0.45rem !important;
    margin: 2px 0 !important;
    border: none !important;
    box-shadow: none !important;
    background-color: transparent !important;
    color: {text_color} !important;
    -webkit-text-fill-color: {text_color} !important;
    transition: background-color 0.15s ease !important;
}}
{btn_text} {{
    color: {text_color} !important;
    -webkit-text-fill-color: {text_color} !important;
}}
{hover} {{
    background-color: #d4d7dd !important;
    border-color: transparent !important;
    color: {text_color} !important;
    -webkit-text-fill-color: {text_color} !important;
}}
{hover_text} {{
    color: {text_color} !important;
    -webkit-text-fill-color: {text_color} !important;
}}
"""
    if active_key in nav_keys:
        active_btn = (
            f"{scope} .st-key-{active_key} button, "
            f"{scope} [class*=\"st-key-{active_key}\"] button, "
            f"{scope} .st-key-{active_key} button:hover, "
            f"{scope} [class*=\"st-key-{active_key}\"] button:hover, "
            f"{scope} .st-key-{active_key} button:focus, "
            f"{scope} [class*=\"st-key-{active_key}\"] button:focus"
        )
        active_text = (
            f"{scope} .st-key-{active_key} button p, {scope} .st-key-{active_key} button div, "
            f"{scope} [class*=\"st-key-{active_key}\"] button p, "
            f"{scope} [class*=\"st-key-{active_key}\"] button div, "
            f"{scope} .st-key-{active_key} button:hover p, {scope} .st-key-{active_key} button:hover div, "
            f"{scope} [class*=\"st-key-{active_key}\"] button:hover p, "
            f"{scope} [class*=\"st-key-{active_key}\"] button:hover div"
        )
        css += f"""
{active_btn} {{
    background-color: #ffffff !important;
    border-color: transparent !important;
    color: {text_color} !important;
    -webkit-text-fill-color: {text_color} !important;
}}
{active_text} {{
    color: {text_color} !important;
    -webkit-text-fill-color: {text_color} !important;
}}
"""
    return css


_page_nav = st.session_state.get("page", "")
_domain_nav = st.session_state.get("project_domain", "")
_nav_active_key = {
    "dashboard": "nav_dashboard",
    "projects": "nav_projects",
    "upload": "nav_projects",
    "casting": "nav_casting",
    "orders": "nav_orders",
    "materials": "nav_orders",
    "agent_sinlex": "nav_agent_sinlex",
    "flow": "nav_flow",
}.get(_page_nav, "")
if _page_nav == "upload" and _domain_nav == "casting":
    _nav_active_key = "nav_casting"

st.markdown(
    f"<style>{_sidebar_nav_css(_nav_active_key)}</style>",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("""
    <style>
        [data-testid="stSidebar"],
        [data-testid="stSidebar"] > div,
        [data-testid="stSidebarUserContent"],
        [data-testid="stSidebarContent"] {
            resize: none !important;
            overscroll-behavior: none !important;
            overscroll-behavior-y: none !important;
            -webkit-overflow-scrolling: auto !important;
            scroll-behavior: auto !important;
            scrollbar-width: none !important;
            -ms-overflow-style: none !important;
        }
        [data-testid="stSidebar"]::-webkit-scrollbar,
        [data-testid="stSidebar"] > div::-webkit-scrollbar,
        [data-testid="stSidebarUserContent"]::-webkit-scrollbar,
        [data-testid="stSidebarContent"]::-webkit-scrollbar {
            display: none !important;
            width: 0 !important;
            height: 0 !important;
        }
        @media (min-width: 769px) {
            [data-testid="stSidebar"],
            [data-testid="stSidebar"] > div,
            [data-testid="stSidebarUserContent"],
            [data-testid="stSidebarContent"] {
                width: 270px !important;
                min-width: 270px !important;
                max-width: 270px !important;
            }
        }
        @media (max-width: 768px) {
            [data-testid="stSidebar"],
            [data-testid="stSidebar"] > div,
            [data-testid="stSidebarUserContent"],
            [data-testid="stSidebarContent"] {
                width: 100% !important;
                min-width: unset !important;
                max-width: 100% !important;
                overflow-y: auto !important;
                touch-action: pan-y !important;
            }
        }
        @media (min-width: 769px) {
            [data-testid="stSidebar"],
            [data-testid="stSidebar"] > div,
            [data-testid="stSidebarUserContent"],
            [data-testid="stSidebarContent"] {
                overflow: hidden !important;
                overflow-y: hidden !important;
                max-height: 100vh !important;
                touch-action: none !important;
            }
        }
        [data-testid="stSidebar"] {
            padding-top: 0 !important;
        }
        [data-testid="stSidebar"] [data-testid="stSidebarUserContent"],
        [data-testid="stSidebar"] [data-testid="stSidebarContent"] {
            margin-top: -1.6rem !important;
        }
        [data-testid="stSidebar"] [data-testid="stSidebarHeader"] {
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            min-height: unset !important;
        }
        [data-testid="stSidebar"] .block-container {
            padding-top: 0 !important;
            padding-left: 1.05rem !important;
            padding-right: 1rem !important;
        }
        [data-testid="stSidebar"] [data-testid="stVerticalBlock"],
        [data-testid="stSidebar"] [data-testid="stElementContainer"],
        [data-testid="stSidebar"] .stButton {
            padding-left: 0.35rem !important;
            margin-left: 0 !important;
        }
        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] [data-testid="stHeading"] {
            text-align: left !important;
            padding-left: 0.35rem !important;
            margin-left: 0 !important;
        }
        [data-testid="stSidebar"] .stButton > button {
            justify-content: flex-start !important;
            text-align: left !important;
            width: 100% !important;
            padding-left: 0.35rem !important;
            padding-right: 0 !important;
            margin-left: 0 !important;
        }
        [data-testid="stSidebar"] .stButton > button p,
        [data-testid="stSidebar"] .stButton > button div {
            text-align: left !important;
            justify-content: flex-start !important;
            width: 100% !important;
            margin-left: 0 !important;
            padding-left: 0 !important;
        }
        [data-testid="stSidebar"] .sinlex-sidebar-user-line,
        [data-testid="stSidebar"] .sinlex-sidebar-engraved,
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
            text-align: left !important;
            margin-left: 0 !important;
            padding-left: 0.35rem !important;
        }
        [data-testid="stSidebar"] .sinlex-sidebar-user-line {
            margin: 0.15rem 0 !important;
            padding-top: 0.35rem !important;
            padding-bottom: 0.35rem !important;
            font-size: 1rem !important;
            line-height: 1.4 !important;
            color: rgb(49, 51, 63) !important;
        }
        [data-testid="stSidebar"] .st-key-logout_btn {
            margin-top: 5px !important;
        }
        [data-testid="stSidebar"] hr {
            margin-left: 0.35rem !important;
            margin-right: 0 !important;
        }
        [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"]:first-child,
        [data-testid="stSidebar"] [data-testid="stVerticalBlock"]:first-of-type {
            margin-top: 0 !important;
            padding-top: 0 !important;
            gap: 0 !important;
        }
        [data-testid="stSidebarResizer"] {
            display: none !important;
        }
        [data-testid="stSidebar"] .sinlex-sidebar-logo {
            text-align: left !important;
            margin: -2px 0 0 0 !important;
            padding: 0 0 0 0.35rem !important;
        }
        [data-testid="stSidebar"] .sinlex-sidebar-logo img {
            display: block !important;
            margin: 0 !important;
        }
        [data-testid="stSidebar"] .sinlex-sidebar-engraved {
            margin: calc(0.2rem + 10px) 0 0.75rem 0 !important;
            padding: 0 !important;
            font-size: 0.75rem !important;
            line-height: 1.45 !important;
            font-weight: 500 !important;
            letter-spacing: 0.02em !important;
            color: rgba(82, 86, 94, 0.68) !important;
            text-shadow:
                0 1px 0 rgba(255, 255, 255, 0.92),
                0 -1px 0 rgba(0, 0, 0, 0.14) !important;
        }
        [data-testid="stSidebar"] .st-key-nav_terms {
            margin-top: calc(0.15rem + 4px) !important;
            margin-bottom: 0 !important;
        }
        [data-testid="stSidebar"] .st-key-nav_privacy {
            margin-top: 1px !important;
            margin-bottom: 0 !important;
        }
        [data-testid="stSidebar"] .st-key-nav_terms button,
        [data-testid="stSidebar"] .st-key-nav_privacy button,
        [data-testid="stSidebar"] .st-key-nav_terms button p,
        [data-testid="stSidebar"] .st-key-nav_privacy button p,
        [data-testid="stSidebar"] .st-key-nav_terms button div,
        [data-testid="stSidebar"] .st-key-nav_privacy button div {
            padding: 0 !important;
            min-height: unset !important;
            height: auto !important;
            line-height: 1.45 !important;
            font-size: 13px !important;
            font-weight: 500 !important;
            letter-spacing: 0.02em !important;
            color: rgba(82, 86, 94, 0.68) !important;
            -webkit-text-fill-color: rgba(82, 86, 94, 0.68) !important;
            text-shadow:
                0 1px 0 rgba(255, 255, 255, 0.92),
                0 -1px 0 rgba(0, 0, 0, 0.14) !important;
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
            text-align: left !important;
            justify-content: flex-start !important;
            width: 100% !important;
        }
        [data-testid="stSidebar"] .st-key-nav_terms button:hover,
        [data-testid="stSidebar"] .st-key-nav_privacy button:hover,
        [data-testid="stSidebar"] .st-key-nav_terms button:hover p,
        [data-testid="stSidebar"] .st-key-nav_privacy button:hover p {
            color: rgba(72, 76, 84, 0.82) !important;
            -webkit-text-fill-color: rgba(72, 76, 84, 0.82) !important;
            text-shadow:
                0 1px 0 rgba(255, 255, 255, 0.96),
                0 -1px 0 rgba(0, 0, 0, 0.18) !important;
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
        }
        [data-testid="stSidebar"] .st-key-nav_terms button:active,
        [data-testid="stSidebar"] .st-key-nav_privacy button:active,
        [data-testid="stSidebar"] .st-key-nav_terms button:active p,
        [data-testid="stSidebar"] .st-key-nav_privacy button:active p {
            color: rgba(62, 66, 74, 0.78) !important;
            -webkit-text-fill-color: rgba(62, 66, 74, 0.78) !important;
            text-shadow:
                0 1px 1px rgba(0, 0, 0, 0.12),
                0 -1px 0 rgba(255, 255, 255, 0.75) !important;
        }
    </style>
    """, unsafe_allow_html=True)
    logo_path = "/opt/sinlex/static/logo.svg"
    if os.path.exists(logo_path):
        with open(logo_path, "rb") as _lf:
            _logo_b64 = base64.b64encode(_lf.read()).decode()
        st.markdown(
            f"<div class='sinlex-sidebar-logo'>"
            f"<img src='data:image/svg+xml;base64,{_logo_b64}' width='80' alt='Sinlex'>"
            f"</div>",
            unsafe_allow_html=True,
        )
    st.title(os.environ.get("SINLEX_SIDEBAR_TITLE", "Технолог").strip() or "Технолог")
    st.markdown("---")
    if st.button("Личный кабинет", key="nav_dashboard"):
        st.session_state.page = "dashboard"
        st.rerun()
    if st.button("3D проекты", key="nav_projects"):
        st.session_state.project_domain = "machining"
        st.session_state.page = "projects"
        st.rerun()
    if st.button("Литье", key="nav_casting"):
        st.session_state.project_domain = "casting"
        st.session_state.page = "casting"
        st.rerun()
    if st.button("🌀 Поток", key="nav_flow"):
        st.session_state.page = "flow"
        st.rerun()
    if st.button("Мои заказы", key="nav_orders"):
        st.session_state.page = "orders"
        st.rerun()
    if _agent_sinlex_enabled():
        if st.button("Agent Sinlex", key="nav_agent_sinlex"):
            st.session_state.page = "agent_sinlex"
            st.rerun()
    st.markdown("---")
    if st.session_state.get("user_email"):
        if st.button("Выйти", key="logout_btn"):

            _logout_sid = st.session_state.get("auth_sid") or st.query_params.get("sid")
            _logout_url = "/api/auth/logout"
            if _logout_sid:
                _logout_url += f"?sid={_logout_sid}"
            _logout_safe = html_module.escape(_logout_url, quote=True)
            st.markdown(
                f'<meta http-equiv="refresh" content="0;url={_logout_safe}">',
                unsafe_allow_html=True,
            )
            st.stop()
    st.markdown(
        '<p class="sinlex-sidebar-engraved">© ООО "Солид" 2026</p>',
        unsafe_allow_html=True,
    )
    if st.button("Условия использования ↘", key="nav_terms", type="tertiary"):
        st.session_state.page = "terms"
        st.rerun()
    if st.button("Политика конфиденциальности ↘", key="nav_privacy", type="tertiary"):
        st.session_state.page = "privacy"
        st.rerun()

access_state = _current_access_state()
_inject_main_scroll_clamp()
st.markdown(
    """
<style>
    header[data-testid="stHeader"] {
        height: 0 !important;
        min-height: 0 !important;
        visibility: hidden !important;
        pointer-events: none !important;
    }
    [data-testid="stMainBlockContainer"] {
        padding-top: 0 !important;
    }
    section[data-testid="stMain"] > div.block-container {
        padding-top: 0.35rem !important;
        max-width: 100% !important;
    }
    .sinlex-page-top {
        display: block;
        height: 0;
        margin: 0;
        padding: 0;
        overflow: hidden;
    }
</style>
    """,
    unsafe_allow_html=True,
)
_render_app_flow_balance_bar()

_maybe_redirect_to_yookassa()
_render_flow_topup_dialog_if_open()
_notice = st.session_state.pop("payment_return_notice", None)
if _notice:
    _kind, _msg = _notice
    if _kind == "success":
        st.success(_msg)
    elif _kind == "warning":
        st.warning(_msg)
    elif _kind == "info":
        st.info(_msg)
    else:
        st.error(_msg)

if st.session_state.page == "dashboard":
    import importlib.util

    _dashboard_path = Path(__file__).resolve().parent / "page_modules" / "1_Dashboard.py"
    _spec = importlib.util.spec_from_file_location("sinlex_page_dashboard", _dashboard_path)
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    _mod.render()

elif st.session_state.page == "upload":
    import importlib.util

    if st.session_state.get("project_domain") == "casting":
        _upload_path = Path(__file__).resolve().parent / "page_modules" / "8_Casting_Project.py"
        _spec = importlib.util.spec_from_file_location("sinlex_page_casting_project", _upload_path)
    else:
        _upload_path = Path(__file__).resolve().parent / "page_modules" / "5_Upload.py"
        _spec = importlib.util.spec_from_file_location("sinlex_page_upload", _upload_path)
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    _mod.render()

elif st.session_state.page == "casting":
    import importlib.util as _ilu
    _casting_path = Path(__file__).resolve().parent / "page_modules" / "7_Casting.py"
    _spec = _ilu.spec_from_file_location("sinlex_page_casting", _casting_path)
    _mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    _mod.render()

if st.session_state.page == "projects":
    import importlib.util

    _projects_path = Path(__file__).resolve().parent / "page_modules" / "2_Projects.py"
    _spec = importlib.util.spec_from_file_location("sinlex_page_projects", _projects_path)
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    _mod.render()

elif st.session_state.page in ("orders", "materials"):
    import importlib.util

    _orders_path = Path(__file__).resolve().parent / "page_modules" / "9_My_Orders.py"
    _spec = importlib.util.spec_from_file_location("sinlex_page_orders", _orders_path)
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    _mod.render()
elif st.session_state.page == "agent_sinlex":
    import importlib.util

    _agent_sinlex_path = Path(__file__).resolve().parent / "page_modules" / "4_Agent_Sinlex.py"
    _spec = importlib.util.spec_from_file_location("sinlex_page_agent_sinlex", _agent_sinlex_path)
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    _mod.render()
elif st.session_state.page == "flow":
    import importlib.util

    _flow_path = Path(__file__).resolve().parent / "page_modules" / "6_Flow.py"
    _spec = importlib.util.spec_from_file_location("sinlex_page_flow", _flow_path)
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    _mod.render()

elif st.session_state.page == "terms":
    render_terms_page()
    if st.button("← Назад", key="back_from_terms"):
        st.session_state.page = "dashboard"
        st.rerun()
elif st.session_state.page == "privacy":
    render_privacy_page()
    if st.button("← Назад", key="back_from_privacy"):
        st.session_state.page = "dashboard"
        st.rerun()
elif st.session_state.page in ("payment", "payment_success"):
    _open_topup = st.session_state.page == "payment"
    st.session_state.page = "flow"
    if _open_topup:
        st.session_state.show_flow_topup_form = True
    st.rerun()

