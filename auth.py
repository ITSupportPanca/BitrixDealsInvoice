import random
import time
import requests
import streamlit as st

# Ambil URL kedua Webhook dari Secrets
WEBHOOK_MAIN = st.secrets["config"]["BITRIX_WEBHOOK"]
WEBHOOK_IM = st.secrets["config"].get("BITRIX_WEBHOOK_IM", WEBHOOK_MAIN)

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
    """Kirim notifikasi lonceng menggunakan Webhook khusus IM"""
    url = WEBHOOK_IM + "im.notify.system.add.json"
    payload = {
        "USER_ID": user_id,
        "MESSAGE": f"Kode OTP Login Streamlit App Anda: [B]{otp_code}[/B]. Berlaku selama 5 menit."
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
