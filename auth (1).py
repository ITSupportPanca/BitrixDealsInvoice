import random
import time
import requests
import streamlit as st

WEBHOOK_MAIN = st.secrets["config"]["BITRIX_WEBHOOK"]

def get_bitrix_user_by_email(email):
    """Cari User ID Bitrix berdasarkan email."""
    url = WEBHOOK_MAIN + "user.get.json"
    clean_email = email.strip().lower()
    payload = {
        "FILTER": {
            "=EMAIL": clean_email,
            "ACTIVE": "Y"
        }
    }
    try:
        resp = requests.post(url, json=payload, timeout=10).json()
        users = resp.get("result", [])
        for u in users:
            user_email = str(u.get("EMAIL", "")).strip().lower()
            if user_email == clean_email:
                full_name = f"{u.get('NAME', '')} {u.get('LAST_NAME', '')}".strip()
                return u.get("ID"), full_name or email
    except Exception as e:
        st.error(f"Gagal terhubung ke Bitrix: {e}")
    return None, None

def send_bitrix_otp_notification(user_id, otp_code):
    """Kirim OTP via Task Bitrix24."""
    url = WEBHOOK_MAIN + "task.item.add.json"
    payload = {
        "ARFIELDS": {
            "TITLE": f"🔑 KODE OTP STREAMLIT: {otp_code}",
            "DESCRIPTION": f"Kode OTP Login Aplikasi Anda adalah: {otp_code}\n\nKode ini berlaku selama 5 menit.",
            "RESPONSIBLE_ID": user_id,
            "DEADLINE": time.strftime('%Y-%m-%dT%H:%M:%S+07:00', time.localtime(time.time() + 300))
        }
    }
    try:
        resp = requests.post(url, json=payload, timeout=10).json()
        if "result" in resp and resp["result"]:
            return True
        else:
            st.error(f"Bitrix Reject: {resp}")
            return False
    except Exception as e:
        st.error(f"Gagal mengirim notifikasi OTP: {e}")
        return False

def login_page_otp(get_user_role):
    """Halaman Login OTP."""
    st.set_page_config(page_title="Login - Bitrix24 Report", page_icon="🔐", layout="centered")
    st.title("🔐 Login")
    st.caption("Masukkan email Bitrix Anda untuk menerima kode OTP di notifikasi Bitrix24.")

    # Cek apakah email terdaftar di secrets
    def is_email_allowed(email):
        users = st.secrets.get("users", {})
        return email.strip().lower() in [k.strip().lower() for k in users.keys()]

    if "otp_sent" not in st.session_state:
        st.session_state["otp_sent"] = False

    if not st.session_state["otp_sent"]:
        with st.form("form_email"):
            email = st.text_input("Email", placeholder="Masukkan email Anda")
            submit = st.form_submit_button("📨 Kirim Kode OTP", type="primary")
            if submit:
                if not email:
                    st.error("Email tidak boleh kosong!")
                elif not is_email_allowed(email):
                    st.error(f"Email **{email}** tidak terdaftar di sistem. Hubungi IT Support.")
                else:
                    with st.spinner("Mengirim kode OTP..."):
                        user_id, user_name = get_bitrix_user_by_email(email)
                        if user_id:
                            otp = str(random.randint(100000, 999999))
                            if send_bitrix_otp_notification(user_id, otp):
                                st.session_state["generated_otp"]  = otp
                                st.session_state["otp_time"]       = time.time()
                                st.session_state["otp_email"]      = email
                                st.session_state["otp_user_name"]  = user_name
                                st.session_state["otp_sent"]       = True
                                st.session_state["otp_attempts"]   = 0
                                st.rerun()
                        else:
                            st.error("Email tidak ditemukan atau akun tidak aktif di Bitrix24.")
    else:
        email     = st.session_state.get("otp_email", "")
        user_name = st.session_state.get("otp_user_name", "")
        sisa      = int(300 - (time.time() - st.session_state.get("otp_time", 0)))
        attempts  = st.session_state.get("otp_attempts", 0)

        if sisa <= 0:
            st.error("⏱️ Kode OTP sudah kadaluarsa. Silakan minta kode baru.")
            if st.button("🔄 Minta Kode Baru"):
                for k in ["otp_sent","generated_otp","otp_time","otp_email","otp_user_name","otp_attempts"]:
                    st.session_state.pop(k, None)
                st.rerun()
            return

        menit = sisa // 60
        detik = sisa % 60
        st.caption(f"Kode OTP telah dikirim ke notifikasi Bitrix24 akun **{user_name}** ({email})")
        st.info(f"⏱️ Kode berlaku: **{menit}:{detik:02d}** menit")

        with st.form("form_otp"):
            otp_input = st.text_input("Masukkan Kode OTP", placeholder="6 digit kode OTP", max_chars=6)
            submit    = st.form_submit_button("✅ Verifikasi", type="primary")
            if submit:
                if not otp_input:
                    st.error("Kode OTP tidak boleh kosong!")
                elif otp_input != st.session_state.get("generated_otp"):
                    st.session_state["otp_attempts"] = attempts + 1
                    remaining = 3 - (attempts + 1)
                    if remaining <= 0:
                        st.error("❌ Terlalu banyak percobaan. Silakan minta kode baru.")
                        for k in ["otp_sent","generated_otp","otp_time","otp_email","otp_user_name","otp_attempts"]:
                            st.session_state.pop(k, None)
                        st.rerun()
                    else:
                        st.error(f"❌ Kode OTP salah. Sisa percobaan: **{remaining}x**")
                else:
                    st.session_state["logged_in"]  = True
                    st.session_state["user_email"] = email
                    st.session_state["user_role"]  = get_user_role(email)
                    for k in ["otp_sent","generated_otp","otp_time","otp_email","otp_user_name","otp_attempts"]:
                        st.session_state.pop(k, None)
                    st.rerun()

        st.divider()
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            if st.button("← Ganti Email", use_container_width=True):
                for k in ["otp_sent","generated_otp","otp_time","otp_email","otp_user_name","otp_attempts"]:
                    st.session_state.pop(k, None)
                st.rerun()
