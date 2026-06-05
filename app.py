import streamlit as st
import requests
import pandas as pd
import time
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from io import BytesIO
from collections import defaultdict
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# =====================================
# PAGE CONFIG
# =====================================
st.set_page_config(
    page_title="Bitrix Deal Monitor",
    page_icon="📊",
    layout="centered"
)

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&family=DM+Mono&display=swap');
    html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
    .main-title { font-size: 2rem; font-weight: 600; color: #1a1a2e; margin-bottom: 0.2rem; }
    .sub-title { color: #666; font-size: 0.95rem; margin-bottom: 2rem; }
    .log-box {
        background: #0f0f1a; color: #7effa0;
        font-family: 'DM Mono', monospace; font-size: 0.8rem;
        padding: 1rem; border-radius: 8px; max-height: 300px;
        overflow-y: auto; line-height: 1.8;
    }
    .stat-card {
        background: #f8f9ff; border-left: 4px solid #4361ee;
        padding: 1rem 1.2rem; border-radius: 6px; margin-bottom: 0.8rem;
    }
    .stat-label { color: #888; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; }
    .stat-value { font-size: 1.8rem; font-weight: 600; color: #1a1a2e; }
    .stButton > button {
        background: #4361ee; color: white; border: none;
        padding: 0.7rem 2rem; font-size: 1rem; font-weight: 500;
        border-radius: 8px; width: 100%; cursor: pointer; transition: background 0.2s;
    }
    .stButton > button:hover { background: #3451d1; }
    .stButton > button:disabled { background: #aaa; }
</style>
""", unsafe_allow_html=True)

# =====================================
# LOAD SECRETS
# =====================================
USERS      = st.secrets["users"]
ADMINS     = set(k for k, v in st.secrets.get("admins", {}).items() if v)
WEBHOOK    = st.secrets["config"]["BITRIX_WEBHOOK"]
SMTP_HOST  = st.secrets["config"]["SMTP_HOST"]
SMTP_PORT  = int(st.secrets["config"]["SMTP_PORT"])
SMTP_USER  = st.secrets["config"]["SMTP_USER"]
SMTP_PASS  = st.secrets["config"]["SMTP_PASS"]
EMAIL_FROM = st.secrets["config"]["EMAIL_FROM"]
CC_DIREKSI = st.secrets["config"].get("CC_EMAIL", "")
# TO_EMAIL = email user yang login (dinamis)

DELAY = 0.3

# =====================================
# LOGIN GATE
# =====================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "logged_user" not in st.session_state:
    st.session_state.logged_user = ""

if not st.session_state.authenticated:
    st.markdown('<div class="main-title">📊 Bitrix Deal Monitor</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">Login untuk melanjutkan</div>', unsafe_allow_html=True)
    st.divider()
    email = st.text_input("Email", placeholder="email@panca-kusuma.com")
    pwd   = st.text_input("Password", type="password", placeholder="Masukkan password...")
    if st.button("Login", use_container_width=True):
        email_input = email.strip().lower()
        if email_input in USERS and USERS[email_input] == pwd:
            st.session_state.authenticated = True
            st.session_state.logged_user = email_input
            st.rerun()
        else:
            st.error("❌ Email atau password salah!")
    st.stop()

# =====================================
# HEADER
# =====================================
col_title, col_logout = st.columns([4, 1])
with col_title:
    st.markdown('<div class="main-title">📊 Bitrix Deal Monitor</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="sub-title">Login sebagai: {st.session_state.logged_user}</div>', unsafe_allow_html=True)
with col_logout:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🚪 Logout", use_container_width=True):
        st.session_state.authenticated = False
        st.session_state.logged_user = ""
        st.rerun()
st.divider()

# =====================================
# HELPERS
# =====================================
def make_session():
    session = requests.Session()
    retry = Retry(total=5, backoff_factor=2, status_forcelist=[500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session

def bx_get(session, method, params, timeout=60):
    url = WEBHOOK + method
    for attempt in range(1, 4):
        try:
            resp = session.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            time.sleep(DELAY)
            return resp.json()
        except requests.exceptions.ConnectTimeout:
            time.sleep(attempt * 10)
        except requests.exceptions.RequestException:
            break
    return {}

def bitrix_get_all(session, method, params, log_fn=None):
    results = []
    start = 0
    while True:
        p = {**params, "start": start}
        data = bx_get(session, method, p)
        batch = data.get("result", [])
        results.extend(batch)
        if log_fn:
            log_fn(f"  → Fetched {len(results)} records...")
        if "next" not in data:
            break
        start = data["next"]
    return results

def get_user_by_email(session, email):
    """Cari user Bitrix berdasarkan email login"""
    data = bx_get(session, "user.get.json", {
        "filter[EMAIL]": email,
        "select[]": ["ID", "NAME", "LAST_NAME", "EMAIL", "UF_DEPARTMENT"]
    })
    users = data.get("result", [])
    return users[0] if users else None

def get_dept_info(session, dept_id):
    """Ambil info department by ID"""
    data = bx_get(session, "department.get.json", {"ID": dept_id})
    depts = data.get("result", [])
    return depts[0] if depts else None

def get_dept_members(session, dept_id):
    """Ambil semua member dari satu department"""
    members = bitrix_get_all(session, "user.get.json", {
        "filter[UF_DEPARTMENT]": dept_id,
        "select[]": ["ID", "NAME", "LAST_NAME", "EMAIL"]
    }, log_fn=None)
    return members

def get_team_scope(session, current_user_bitrix_id, log_fn=None):
    """
    Logic universal:
    1. Ambil semua dept yang dimiliki user
    2. Kumpulkan semua member dari semua dept tersebut
    3. Cari supervisor dari dept pertama (untuk CC email)
    Return: (set of user IDs, supervisor info or None)
    """
    if log_fn:
        log_fn("  → Mengambil info department user...")

    user_data = bx_get(session, "user.get.json", {
        "filter[ID]": current_user_bitrix_id,
        "select[]": ["ID", "NAME", "LAST_NAME", "EMAIL", "UF_DEPARTMENT"]
    })
    users = user_data.get("result", [])
    if not users:
        return {str(current_user_bitrix_id)}, None

    current_user = users[0]
    dept_ids = current_user.get("UF_DEPARTMENT", [])
    if not dept_ids:
        return {str(current_user_bitrix_id)}, None

    if not isinstance(dept_ids, list):
        dept_ids = [dept_ids]

    if log_fn:
        log_fn(f"  → User terdaftar di {len(dept_ids)} department")

    all_member_ids = set()
    supervisor_info = None

    for dept_id in dept_ids:
        dept = get_dept_info(session, dept_id)
        if not dept:
            continue

        dept_name = dept.get("NAME", dept_id)
        members = get_dept_members(session, dept_id)
        member_ids = {str(m["ID"]) for m in members}
        all_member_ids.update(member_ids)

        if log_fn:
            log_fn(f"  → Dept '{dept_name}': {len(member_ids)} member")

        # Cari supervisor dari dept pertama (untuk CC)
        if supervisor_info is None:
            head_id = str(dept.get("UF_HEAD", ""))
            if head_id and head_id != str(current_user_bitrix_id):
                sup_data = bx_get(session, "user.get.json", {
                    "filter[ID]": head_id,
                    "select[]": ["ID", "NAME", "LAST_NAME", "EMAIL"]
                })
                sups = sup_data.get("result", [])
                if sups:
                    supervisor_info = sups[0]

    # Pastikan user sendiri selalu masuk
    all_member_ids.add(str(current_user_bitrix_id))

    return all_member_ids, supervisor_info

def get_users_info_batch(session, user_ids):
    unique_ids = list(set(str(uid) for uid in user_ids if uid))
    user_map = {}
    for i in range(0, len(unique_ids), 50):
        chunk = unique_ids[i:i+50]
        params = {"select[]": ["ID", "NAME", "LAST_NAME", "WORK_POSITION", "EMAIL"]}
        for j, uid in enumerate(chunk):
            params[f"filter[ID][{j}]"] = uid
        data = bx_get(session, "user.get.json", params)
        for u in data.get("result", []):
            full_name = f"{u.get('NAME', '')} {u.get('LAST_NAME', '')}".strip()
            user_map[str(u["ID"])] = {
                "name": full_name or str(u["ID"]),
                "position": u.get("WORK_POSITION", "-"),
                "email": u.get("EMAIL", "-") or "-"
            }
    return user_map

def get_all_companies_batch(session, company_ids):
    unique_ids = list(set(str(cid) for cid in company_ids if cid))
    company_map = {}
    for i in range(0, len(unique_ids), 50):
        chunk = unique_ids[i:i+50]
        params = {"select[]": ["ID", "TITLE"]}
        for j, cid in enumerate(chunk):
            params[f"filter[ID][{j}]"] = cid
        data = bx_get(session, "crm.company.list.json", params)
        for c in data.get("result", []):
            company_map[str(c["ID"])] = c.get("TITLE", "-")
    return company_map

def send_email(to_email, cc_email, deals, sender_name=""):
    df = pd.DataFrame(deals)
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Deals')
    buffer.seek(0)
    excel_data = buffer.read()

    msg = MIMEMultipart("mixed")
    msg["Subject"] = "Deals WON Belum Invoice"
    msg["From"] = EMAIL_FROM
    msg["To"] = to_email
    if cc_email:
        msg["Cc"] = cc_email

    body = MIMEMultipart("alternative")
    html = f"""
    <html><body>
    <p>Halo,</p>
    <p>Berikut kami lampirkan daftar deals WON yang belum memiliki invoice.</p>
    <p>Mohon segera dibuatkan invoice untuk deals tersebut.</p>
    <br><p>Terima kasih.</p>
    </body></html>
    """
    body.attach(MIMEText(html, "html"))
    msg.attach(body)

    part = MIMEBase("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    part.set_payload(excel_data)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", 'attachment; filename="deals_belum_invoice.xlsx"')
    msg.attach(part)

    recipients = [to_email]
    if cc_email:
        recipients += [cc.strip() for cc in cc_email.split(",") if cc.strip()]

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(EMAIL_FROM, recipients, msg.as_string())

    return excel_data

# =====================================
# MAIN UI
# =====================================
if "result_df" not in st.session_state:
    st.session_state.result_df = None
if "excel_data" not in st.session_state:
    st.session_state.excel_data = None

run_btn = st.button("🚀 Jalankan & Kirim Email", use_container_width=True)

if run_btn:
    log_placeholder = st.empty()
    logs = []

    def log(msg):
        logs.append(msg)
        log_placeholder.markdown(
            '<div class="log-box">' + "<br>".join(logs[-20:]) + '</div>',
            unsafe_allow_html=True
        )

    try:
        session = make_session()
        logged_email = st.session_state.logged_user

        # Cari user Bitrix berdasarkan email login
        log(f"🔍 Mencari akun Bitrix untuk {logged_email}...")
        bitrix_user = get_user_by_email(session, logged_email)
        if not bitrix_user:
            st.error(f"❌ Email {logged_email} tidak ditemukan di Bitrix24!")
            st.stop()

        bitrix_user_id = str(bitrix_user["ID"])
        user_fullname = f"{bitrix_user.get('NAME','')} {bitrix_user.get('LAST_NAME','')}".strip()
        log(f"✅ Ditemukan: {user_fullname} (ID: {bitrix_user_id})")

        # Cek apakah super admin
        is_admin = logged_email in ADMINS

        # Cek struktur tim
        to_email = logged_email
        cc_parts = []

        if is_admin:
            log("👑 Mode: Super Admin — akses semua deals")
            team_ids = None  # None = tidak filter, ambil semua
        else:
            log("🏢 Mengecek struktur tim dari Bitrix...")
            team_ids, supervisor = get_team_scope(session, bitrix_user_id, log_fn=log)
            log(f"✅ Total user dalam scope: {len(team_ids)}")
            if supervisor:
                sup_email = supervisor.get("EMAIL", "")
                if sup_email and sup_email != logged_email:
                    cc_parts.append(sup_email)
                    log(f"📬 CC ke supervisor: {sup_email}")

        if CC_DIREKSI:
            for e in CC_DIREKSI.split(","):
                e = e.strip()
                if e and e not in cc_parts:
                    cc_parts.append(e)
            log(f"📬 CC ke direksi: {CC_DIREKSI}")
        cc_email = ", ".join(cc_parts)

        # Ambil semua deals WON
        log("📋 Mengambil deals WON...")
        all_deals = bitrix_get_all(session, "crm.deal.list.json", {
            "filter[STAGE_SEMANTIC_ID]": "S",
            "select[]": ["ID", "TITLE", "STAGE_ID", "OPPORTUNITY", "ASSIGNED_BY_ID", "COMPANY_ID"]
        }, log_fn=log)
        log(f"✅ Total deals WON: {len(all_deals)}")

        # Filter deals
        if team_ids is None:
            team_deals = all_deals  # admin = semua deals
        else:
            team_deals = [d for d in all_deals if str(d.get("ASSIGNED_BY_ID", "")) in team_ids]
        log(f"✅ Deals dalam scope: {len(team_deals)}")

        # Ambil invoice
        log("📄 Mengambil invoice...")
        invoice_deal_ids = set()
        all_invoices = bitrix_get_all(session, "crm.invoice.list.json", {"select": ["UF_DEAL_ID"]}, log_fn=log)
        for row in all_invoices:
            did = row.get("UF_DEAL_ID")
            if did:
                invoice_deal_ids.add(str(did))
        log(f"✅ Deal sudah ada invoice: {len(invoice_deal_ids)}")

        # Filter belum invoice
        deals_filtered = [d for d in team_deals if str(d["ID"]) not in invoice_deal_ids]
        log(f"📊 Deals WON belum invoice: {len(deals_filtered)}")

        if not deals_filtered:
            log("🎉 Semua deals sudah punya invoice!")
            st.success("✅ Semua deals sudah punya invoice. Tidak ada email yang dikirim.")
            st.stop()

        # Ambil info user & company
        log("👤 Mengambil info user & company...")
        user_map = get_users_info_batch(session, [d.get("ASSIGNED_BY_ID") for d in deals_filtered])
        company_map = get_all_companies_batch(session, [d.get("COMPANY_ID") for d in deals_filtered])

        all_clean_deals = []
        for deal in deals_filtered:
            uid = str(deal.get("ASSIGNED_BY_ID", ""))
            cid = str(deal.get("COMPANY_ID", ""))
            ui = user_map.get(uid, {"name": "-", "position": "-", "email": "-"})
            all_clean_deals.append({
                "Deal ID": deal.get("ID"),
                "Company Name": company_map.get(cid, "-"),
                "Deal Name": deal.get("TITLE"),
                "Stage": deal.get("STAGE_ID"),
                "Amount": deal.get("OPPORTUNITY"),
                "Responsible": ui["name"],
            })

        # Kirim email
        log(f"📧 Mengirim email ke {to_email}...")
        if cc_email:
            log(f"   CC: {cc_email}")
        excel_data = send_email(to_email, cc_email, all_clean_deals, user_fullname)
        log(f"✅ Email terkirim!")
        log("🎉 Selesai!")

        st.session_state.result_df = pd.DataFrame(all_clean_deals)
        st.session_state.excel_data = excel_data

    except Exception as e:
        log(f"❌ Error: {e}")
        st.error(f"Terjadi error: {e}")

# =====================================
# RESULT
# =====================================
if st.session_state.result_df is not None:
    df = st.session_state.result_df
    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-label">Total Deals</div>
            <div class="stat-value">{len(df)}</div>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        total_amount = pd.to_numeric(df["Amount"], errors="coerce").sum()
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-label">Total Amount</div>
            <div class="stat-value">{total_amount:,.0f}</div>
        </div>
        """, unsafe_allow_html=True)

    st.dataframe(df, use_container_width=True, hide_index=True)

    st.download_button(
        label="⬇️ Download Excel",
        data=st.session_state.excel_data,
        file_name="deals_belum_invoice.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )
