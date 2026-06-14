"""Реквизиты оператора сервиса «AI Технолог» / Sinlex."""

COMPANY = {
    "name": 'ООО «Солид»',
    "inn": "7811581101",
    "kpp": "780101001",
    "address": "199178, г. Санкт-Петербург, линия 13-я В.О., д. 72, литера А, помещение 1-Н",
    "service": "AI Технолог (Sinlex)",
    "email": "support@sinlex.tech",
    "updated": "16.05.2026",
}


def render_requisites():
    import streamlit as st

    st.markdown(
        f"""
**{COMPANY["name"]}**  
ИНН {COMPANY["inn"]} · КПП {COMPANY["kpp"]}  
{COMPANY["address"]}
"""
    )


PAYMENT = {
    "name": "ИП Балагуров А.И.",
    "inn": "141402971228",
    "bank": "СЕВЕРО-ЗАПАДНЫЙ БАНК ПАО СБЕРБАНК Г. Санкт-Петербург",
    "account": "40802810855000071607",
    "corr_account": "30101810500000000653",
    "bik": "044030653",
}


def render_payment_requisites():
    import streamlit as st

    p = PAYMENT
    st.markdown(
        f"""
**{p["name"]}**  
ИНН {p["inn"]}  
{p["bank"]}  
р/с {p["account"]}  
к/с {p["corr_account"]}  
БИК {p["bik"]}
"""
    )
