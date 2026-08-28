import random
import time
import requests
import streamlit as st

# Ambil URL Webhook dari Secrets
WEBHOOK = st.secrets["config"]["BITRIX_WEBHOOK"]

def get_bitrix_user_by_email(email):
    """Cari User ID Bitrix berdasarkan email secara akurat"""
    url = WEBHOOK + "user.get.json"
    # Pastikan email di-trim dan dipaksa lowercase biar pencarian akurat
    clean_email = email.strip().lower()
    
    payload = {
        "FILTER": {
            "=EMAIL": clean_email,  # Gunakan '=EMAIL' agar pencarian exact match (presisi)
            "ACTIVE": "Y"
        }
    }
    try:
        resp = requests.post(url, json=payload, timeout=10).json()
        users = resp.get("result", [])
        
        # Loop untuk memastikan email benar-benar cocok 100%
        for u in users:
            user_email = str(u.get("EMAIL", "")).strip().lower()
            if user_email == clean_email:
                full_name = f"{u.get('NAME', '')} {u.get('LAST_NAME', '')}".strip()
                return u.get("ID"), full_name or email

    except Exception as e:
        st.error(f"Gagal terhubung ke Bitrix: {e}")
    return None, None

def send_bitrix_otp_notification(user_id, otp_code):
    """Kirim notifikasi lonceng ke Bitrix"""
    url = WEBHOOK + "im.notify.system.add.json"
    payload = {
        "USER_ID": user_id,
        "MESSAGE": f"Kode OTP Login Streamlit App Anda: [B]{otp_code}[/B]\n\n*Berlaku selama 5 menit. Jangan berikan kode ini ke siapa pun.*",
        "NOTIFY_TYPE": 4,  # Type 4 = SYSTEM notification (Lonceng)
    }
    try:
        resp = requests.post(url, json=payload, timeout=10).json()
        # Jika respon ada result (mengembalikan ID notification), berarti sukses
        if "result" in resp and resp["result"]:
            return True
        else:
            st.error(f"Bitrix Reject: {resp}")
            return False
    except Exception as e:
        st.error(f"Gagal mengirim notifikasi OTP: {e}")
        return False

def login_page_otp(get_user_role):
    st.set_page_config(page_title="Login - Bitrix24 Report", page_icon="🔐", layout="centered")
    st.title("🔐 Login via Bitrix OTP")
    st.caption("Masukkan email Bitrix Anda untuk menerima kode OTP di notifikasi Bitrix24.")

    if "otp_sent" not in st.session_state:
        st.session_state["otp_sent"] = False

    # Input Email
    email = st.text_input("Email Bitrix", placeholder="email@domain.com")

    if st.button("📨 Kirim Kode OTP", type="primary"):
        if not email:
            st.error("Email tidak boleh kosong!")
        else:
            with st.spinner("Mengecek email dan mengirim OTP..."):
                user_id, user_name = get_bitrix_user_by_email(email)
                if user_id:
                    otp = str(random.randint(100000, 999999))
                    st.session_state["generated_otp"] = otp
                    st.session_state["otp_time"] = time.time()
                    st.session_state["otp_email"] = email
                    st.session_state["otp_user_name"] = user_name
                    st.session_state["otp_sent"] = True

                    send_bitrix_otp_notification(user_id, otp)
                    st.success(f"✅ Kode OTP telah dikirim ke notifikasi Bitrix24 ({user_name})!")
                else:
                    st.error("Email tidak ditemukan atau akun tidak aktif di Bitrix24.")

    # Input Kode OTP (Muncul setelah tombol Kirim diklik)
    if st.session_state.get("otp_sent"):
        st.divider()
        otp_input = st.text_input("Masukkan Kode OTP (6 digit)", type="password", placeholder="123456")
        if st.button("🔓 Verifikasi & Login"):
            if time.time() - st.session_state.get("otp_time", 0) > 300:
                st.error("Kode OTP sudah kedaluwarsa. Silakan minta kode OTP baru.")
                st.session_state["otp_sent"] = False
            elif otp_input == st.session_state.get("generated_otp"):
                st.session_state["logged_in"] = True
                st.session_state["user_email"] = st.session_state["otp_email"]
                st.session_state["user_role"] = get_user_role(st.session_state["otp_email"])
                st.rerun()
            else:
                st.error("Kode OTP salah, silakan cek notifikasi Bitrix24 Anda.")
