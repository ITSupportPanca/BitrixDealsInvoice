import random
import time
import requests
import streamlit as st

# Ambil webhook URL dari Streamlit secrets biar aman di GitHub
BITRIX_WEBHOOK_URL = st.secrets["BITRIX_WEBHOOK_URL"]

def get_user_id_by_email(email):
    """Mencari User ID Bitrix berdasarkan Email"""
    url = f"{BITRIX_WEBHOOK_URL}user.get"
    payload = {"FILTER": {"EMAIL": email, "ACTIVE": "Y"}}
    try:
        response = requests.post(url, json=payload, timeout=10).json()
        result = response.get("result", [])
        if result:
            return result[0]["ID"]
    except Exception as e:
        st.error(f"Error koneksi ke Bitrix: {e}")
    return None

def send_bitrix_otp(user_id, otp_code):
    """Mengirim notifikasi lonceng ke Bitrix"""
    url = f"{BITRIX_WEBHOOK_URL}im.notify.system.add"
    payload = {
        "USER_ID": user_id,
        "MESSAGE": f"Kode OTP Login Apps Anda adalah: [B]{otp_code}[/B]. Berlaku selama 5 menit."
    }
    try:
        response = requests.post(url, json=payload, timeout=10).json()
        return response.get("result")
    except Exception as e:
        st.error(f"Gagal mengirim notifikasi: {e}")
        return False

def show_login_ui():
    """Tampilan Form Login OTP"""
    st.subheader("Login Dashboard Deals")
    
    # Inisialisasi Session State
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if "otp_sent" not in st.session_state:
        st.session_state.otp_sent = False
    if "generated_otp" not in st.session_state:
        st.session_state.generated_otp = None
    if "otp_time" not in st.session_state:
        st.session_state.otp_time = 0

    if st.session_state.authenticated:
        return True

    # Form Input Email
    email_input = st.text_input("Masukkan Email Bitrix Anda:")
    
    if st.button("Kirim Kode OTP"):
        if email_input:
            user_id = get_user_id_by_email(email_input)
            if user_id:
                otp = str(random.randint(100000, 999999))
                st.session_state.generated_otp = otp
                st.session_state.otp_time = time.time()
                st.session_state.otp_sent = True
                
                send_bitrix_otp(user_id, otp)
                st.success("Kode OTP telah dikirim ke notifikasi Bitrix Anda!")
            else:
                st.error("Email tidak ditemukan atau user tidak aktif di Bitrix.")
        else:
            st.warning("Silakan masukkan email terlebih dahulu.")

    # Form Input OTP (muncul jika tombol Kirim Kode OTP sudah diklik)
    if st.session_state.otp_sent:
        otp_input = st.text_input("Masukkan Kode OTP:", type="password")
        if st.button("Verifikasi & Login"):
            # Cek Expiry (5 menit = 300 detik)
            if time.time() - st.session_state.otp_time > 300:
                st.error("Kode OTP sudah kedaluwarsa. Silakan minta OTP baru.")
                st.session_state.otp_sent = False
            elif otp_input == st.session_state.generated_otp:
                st.session_state.authenticated = True
                st.success("Verifikasi Berhasil!")
                st.rerun()
            else:
                st.error("Kode OTP salah, silakan coba lagi.")

    return False