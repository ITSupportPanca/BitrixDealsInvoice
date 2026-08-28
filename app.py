import streamlit as st
import pandas as pd
import requests
from auth import login_page_otp

# ==================== CONFIG & HELPER ROLES ====================
WEBHOOK = st.secrets["config"]["BITRIX_WEBHOOK"]

def get_user_role(email):
    roles = st.secrets.get("roles", {})
    return roles.get(email, "guest")

# ==================== GATEKEEPER LOGIN OTP ====================
if not st.session_state.get("logged_in"):
    login_page_otp(get_user_role)
    st.stop()

# ==================== FETCH DATA BITRIX ====================
@st.cache_data(ttl=300)
def fetch_bitrix_deals():
    url = WEBHOOK + "crm.deal.list.json"
    payload = {
        "select": ["ID", "TITLE", "STAGE_ID", "OPPORTUNITY", "CURRENCY_ID", "ASSIGNED_BY_ID", "COMPANY_ID", "BEGINDATE", "CLOSEDATE"],
        "order": {"ID": "DESC"}
    }
    try:
        resp = requests.post(url, json=payload, timeout=15).json()
        return resp.get("result", [])
    except Exception as e:
        st.error(f"Gagal mengambil data Deals: {e}")
        return []

@st.cache_data(ttl=300)
def fetch_bitrix_invoices():
    url = WEBHOOK + "crm.invoice.list.json"
    payload = {
        "select": ["ID", "ORDER_TOPIC", "STATUS_ID", "PRICE", "CURRENCY", "PAY_BEFORE", "DATE_BILL"],
        "order": {"ID": "DESC"}
    }
    try:
        resp = requests.post(url, json=payload, timeout=15).json()
        return resp.get("result", [])
    except Exception as e:
        st.error(f"Gagal mengambil data Invoices: {e}")
        return []

# ==================== DASHBOARD UTAMA ====================
st.set_page_config(page_title="Bitrix24 Deals & Invoice Report", page_icon="📊", layout="wide")

# Header & Logout
col_title, col_logout = st.columns([4, 1])
with col_title:
    st.title("📊 Bitrix24 Deals & Invoice Outstanding")
    st.write(f"Selamat datang, **{st.session_state.get('user_email')}** (Role: `{st.session_state.get('user_role')}`)")
with col_logout:
    st.write("")
    if st.button("🚪 Logout", type="secondary"):
        st.session_state.clear()
        st.rerun()

st.divider()

# Load Data
with st.spinner("Memuat data dari Bitrix24..."):
    deals_data = fetch_bitrix_deals()
    invoices_data = fetch_bitrix_invoices()

df_deals = pd.DataFrame(deals_data)
df_invoices = pd.DataFrame(invoices_data)

# Metric Summary
m1, m2, m3 = st.columns(3)
with m1:
    st.metric("Total Deals", len(df_deals) if not df_deals.empty else 0)
with m2:
    st.metric("Total Invoices", len(df_invoices) if not df_invoices.empty else 0)
with m3:
    total_val = df_deals["OPPORTUNITY"].astype(float).sum() if not df_deals.empty and "OPPORTUNITY" in df_deals.columns else 0
    st.metric("Total Value Deals", f"Rp {total_val:,.0f}")

# Tabs Tampilan Data
tab1, tab2 = st.tabs(["📋 Deals List", "🧾 Invoices Outstanding"])

with tab1:
    st.subheader("Data Deals Bitrix24")
    if not df_deals.empty:
        st.dataframe(df_deals, use_container_width=True)
    else:
        st.info("Tidak ada data Deals.")

with tab2:
    st.subheader("Data Invoices Outstanding")
    if not df_invoices.empty:
        st.dataframe(df_invoices, use_container_width=True)
    else:
        st.info("Tidak ada data Invoices.")
