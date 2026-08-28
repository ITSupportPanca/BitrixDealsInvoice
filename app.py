import streamlit as st
import pandas as pd
import requests
from datetime import datetime, date
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
def fetch_bitrix_deals(start_date, end_date):
    url = WEBHOOK + "crm.deal.list.json"
    # Format tanggal Bitrix ISO: YYYY-MM-DDT00:00:00
    s_date = f"{start_date}T00:00:00"
    e_date = f"{end_date}T23:59:59"
    
    payload = {
        "filter": {
            ">=BEGINDATE": s_date,
            "<=BEGINDATE": e_date
        },
        "select": ["ID", "TITLE", "STAGE_ID", "OPPORTUNITY", "CURRENCY_ID", "ASSIGNED_BY_ID", "COMPANY_ID", "BEGINDATE", "CLOSEDATE"],
        "order": {"ID": "DESC"}
    }
    try:
        resp = requests.post(url, json=payload, timeout=20).json()
        return resp.get("result", [])
    except Exception as e:
        st.error(f"Gagal mengambil data Deals: {e}")
        return []

@st.cache_data(ttl=300)
def fetch_bitrix_invoices(start_date, end_date):
    url = WEBHOOK + "crm.invoice.list.json"
    s_date = f"{start_date}T00:00:00"
    e_date = f"{end_date}T23:59:59"
    
    payload = {
        "filter": {
            ">=DATE_BILL": s_date,
            "<=DATE_BILL": e_date
        },
        "select": ["ID", "ORDER_TOPIC", "STATUS_ID", "PRICE", "CURRENCY", "PAY_BEFORE", "DATE_BILL"],
        "order": {"ID": "DESC"}
    }
    try:
        resp = requests.post(url, json=payload, timeout=20).json()
        return resp.get("result", [])
    except Exception as e:
        st.error(f"Gagal mengambil data Invoices: {e}")
        return []

# ==================== DASHBOARD UTAMA ====================
st.set_page_config(page_title="Bitrix24 Report Generator", page_icon="📊", layout="wide")

# Header & Logout
col_title, col_logout = st.columns([4, 1])
with col_title:
    st.title("📊 Bitrix24 Report Generator")
    st.write(f"Selamat datang, **{st.session_state.get('user_email')}** (Role: `{st.session_state.get('user_role')}`)")
with col_logout:
    st.write("")
    if st.button("🚪 Logout", type="secondary"):
        st.session_state.clear()
        st.rerun()

st.divider()

# TAB PILIHAN LAPORAN
tab1, tab2 = st.tabs(["📋 Deals Belum Invoice", "🧾 Invoice Outstanding (OS)"])

# -------------------------------------------------------------------
# TAB 1: DEALS BELUM INVOICE
# -------------------------------------------------------------------
with tab1:
    st.subheader("Filter Periode Deals")
    
    c1, c2, c3 = st.columns([2, 2, 1])
    with c1:
        d1_start = st.date_input("Tanggal Mulai (Deals)", value=date.today().replace(day=1), key="d1_start")
    with c2:
        d1_end = st.date_input("Tanggal Selesai (Deals)", value=date.today(), key="d1_end")
    with c3:
        st.write("")
        st.write("")
        btn_gen_deals = st.button("🔄 Generate Deals", type="primary", key="btn_deals")

    if btn_gen_deals or st.session_state.get("deals_generated"):
        st.session_state["deals_generated"] = True
        with st.spinner("Memproses data Deals..."):
            deals_data = fetch_bitrix_deals(d1_start, d1_end)
            df_deals = pd.DataFrame(deals_data)

        st.divider()
        if not df_deals.empty:
            st.success(f"Ditemukan {len(df_deals)} data Deals pada periode {d1_start} s/d {d1_end}")
            
            # Tampilkan Data
            st.dataframe(df_deals, use_container_width=True)
            
            # Export CSV
            csv_deals = df_deals.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Export Deals to CSV",
                data=csv_deals,
                file_name=f"deals_report_{d1_start}_to_{d1_end}.csv",
                mime="text/csv",
                type="secondary"
            )
        else:
            st.info("Tidak ada data Deals pada periode yang dipilih.")

# -------------------------------------------------------------------
# TAB 2: INVOICE OUTSTANDING (OS)
# -------------------------------------------------------------------
with tab2:
    st.subheader("Filter Periode Invoice")
    
    c1, c2, c3 = st.columns([2, 2, 1])
    with c1:
        inv_start = st.date_input("Tanggal Mulai (Invoice)", value=date.today().replace(day=1), key="inv_start")
    with c2:
        inv_end = st.date_input("Tanggal Selesai (Invoice)", value=date.today(), key="inv_end")
    with c3:
        st.write("")
        st.write("")
        btn_gen_inv = st.button("🔄 Generate Invoice", type="primary", key="btn_inv")

    if btn_gen_inv or st.session_state.get("inv_generated"):
        st.session_state["inv_generated"] = True
        with st.spinner("Memproses data Invoice..."):
            invoices_data = fetch_bitrix_invoices(inv_start, inv_end)
            df_invoices = pd.DataFrame(invoices_data)

        st.divider()
        if not df_invoices.empty:
            st.success(f"Ditemukan {len(df_invoices)} data Invoice pada periode {inv_start} s/d {inv_end}")
            
            # Tampilkan Data
            st.dataframe(df_invoices, use_container_width=True)
            
            # Export CSV
            csv_inv = df_invoices.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Export Invoices to CSV",
                data=csv_inv,
                file_name=f"invoices_report_{inv_start}_to_{inv_end}.csv",
                mime="text/csv",
                type="secondary"
            )
        else:
            st.info("Tidak ada data Invoice pada periode yang dipilih.")
