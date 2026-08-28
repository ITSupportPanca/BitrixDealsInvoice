import random
import time
import requests
import streamlit as st

# Gunakan Webhook utama yang sudah berjalan
WEBHOOK_MAIN = st.secrets["config"]["BITRIX_WEBHOOK"]

def get_bitrix_user_by_email(email):
    """Cari User ID Bitrix berdasarkan email"""
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
    """
    Mengirim OTP via Notifikasi Task Bitrix24 (bypass limitasi REST API Chat/IM)
    """
    url = WEBHOOK_MAIN + "task.item.add.json"
    
    # Payload Task otomatis memicu notifikasi lonceng ke user penerima (RESPONSIBLE_ID)
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
