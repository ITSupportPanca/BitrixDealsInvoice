"""
Bitrix24 - Deals Outstanding Report
"""

import streamlit as st
import requests
import pandas as pd
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from io import BytesIO
from collections import defaultdict
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ==================== CONFIG ====================
WEBHOOK    = st.secrets["config"]["BITRIX_WEBHOOK"]
DELAY      = 0.1

SMTP_HOST  = st.secrets["config"]["SMTP_HOST"]
SMTP_PORT  = int(st.secrets["config"]["SMTP_PORT"])
SMTP_USER  = st.secrets["config"]["SMTP_USER"]
SMTP_PASS  = st.secrets["config"]["SMTP_PASS"]
EMAIL_FROM = st.secrets["config"]["EMAIL_FROM"]
CC_EMAILS  = [st.secrets["config"]["CC_EMAIL"]]
# ================================================


def make_session():
    session = requests.Session()
    retry = Retry(total=5, backoff_factor=2, status_forcelist=[500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session

SESSION = make_session()


def bx_get(method, params, timeout=60):
    url = WEBHOOK + method
    for attempt in range(1, 4):
        try:
            resp = SESSION.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            time.sleep(DELAY)
            return resp.json()
        except requests.exceptions.ConnectTimeout:
            time.sleep(attempt * 10)
        except requests.exceptions.RequestException:
            break
    return {}


def bx_post(method, params, timeout=60):
    url = WEBHOOK + method
    for attempt in range(1, 4):
        try:
            resp = SESSION.post(url, json=params, timeout=timeout)
            resp.raise_for_status()
            time.sleep(DELAY)
            return resp.json()
        except requests.exceptions.ConnectTimeout:
            time.sleep(attempt * 10)
        except requests.exceptions.RequestException:
            break
    return {}


def bitrix_get_all(method, params):
    results = []
    start = 0
    while True:
        p = {**params, "start": start}
        data = bx_get(method, p)
        batch = data.get("result", [])
        results.extend(batch)
        if "next" not in data:
            break
        start = data["next"]
    return results


def get_users_batch(user_ids):
    unique_ids = list(set(str(uid) for uid in user_ids if uid))
    user_map = {}
    chunk_size = 50
    for i in range(0, len(unique_ids), chunk_size):
        chunk = unique_ids[i:i+chunk_size]
        params = {"select[]": ["ID", "NAME", "LAST_NAME"]}
        for j, uid in enumerate(chunk):
            params[f"filter[ID][{j}]"] = uid
        data = bx_get("user.get.json", params)
        for u in data.get("result", []):
            full_name = f"{u.get('NAME', '')} {u.get('LAST_NAME', '')}".strip()
            user_map[str(u["ID"])] = full_name or str(u["ID"])
    return user_map


def debug_single_deal(deal_id):
    st.write(f"### 🔍 Debug Deal ID: {deal_id}")

    # Cek deal
    deal_data = bx_post("crm.deal.get", {"id": deal_id})
    deal = deal_data.get("result", {})
    st.write("**Deal info:**", {
        "ID": deal.get("ID"),
        "Title": deal.get("TITLE"),
        "Stage": deal.get("STAGE_ID"),
        "Amount": deal.get("OPPORTUNITY"),
    })

    # Cek invoice
    st.write("**Mencari invoice untuk deal ini...**")
    inv_data = bx_post("crm.invoice.list", {
        "filter": {"UF_DEAL_ID": deal_id},
        "select": ["ID", "ACCOUNT_NUMBER", "STATUS_ID", "DATE_BILL", "PRICE"]
    })
    invoices = inv_data.get("result", [])
    st.write(f"Invoice ditemukan: {len(invoices)}")
    for inv in invoices:
        st.write(f"  - Invoice {inv.get('ACCOUNT_NUMBER')} (ID:{inv.get('ID')}) | Status:{inv.get('STATUS_ID')} | Amount:{inv.get('PRICE')}")

        # Cek product rows invoice
        prod_data = bx_post("crm.productrow.list", {
            "filter": {"OWNER_TYPE": "I", "OWNER_ID": int(inv["ID"])},
            "select": ["OWNER_ID", "PRODUCT_ID", "PRODUCT_NAME", "QUANTITY"]
        })
        prods = prod_data.get("result", [])
        st.write(f"    Product rows: {len(prods)}")
        for p in prods:
            st.write(f"      • {p.get('PRODUCT_NAME')} — Qty: {p.get('QUANTITY')}")

    # Cek deal product rows
    st.write("**Deal product rows:**")
    deal_prod_data = bx_post("crm.deal.productrows.get", {"id": deal_id})
    deal_prods = deal_prod_data.get("result", [])
    st.write(f"Deal products ditemukan: {len(deal_prods)}")
    for p in deal_prods:
        st.write(f"  • {p.get('PRODUCT_NAME')} — Qty: {p.get('QUANTITY')} | Price: {p.get('PRICE')}")


def fetch_data():
    progress = st.progress(0)
    status = st.empty()

    # STEP 1 - Deals WON
    status.text("📋 Mengambil deals WON...")
    all_deals = bitrix_get_all(
        "crm.deal.list.json",
        {
            "filter[STAGE_SEMANTIC_ID]": "S",
            "select[]": ["ID", "TITLE", "STAGE_ID", "OPPORTUNITY",
                         "ASSIGNED_BY_ID", "DATE_CLOSED", "CURRENCY_ID"]
        }
    )
    progress.progress(15)
    status.text(f"✅ {len(all_deals)} deals WON ditemukan")

    # STEP 2 - Semua invoice
    status.text("📄 Mengambil data invoice...")
    all_invoices_raw = bitrix_get_all(
        "crm.invoice.list.json",
        {"select": ["ID", "UF_DEAL_ID", "ACCOUNT_NUMBER", "DATE_BILL", "STATUS_ID", "PRICE"]}
    )
    progress.progress(35)

    # Build invoice map
    invoice_map = defaultdict(list)
    invoice_amount_map = defaultdict(float)
    for inv in all_invoices_raw:
        deal_id = str(inv.get("UF_DEAL_ID", ""))
        if deal_id and deal_id != "0" and inv.get("STATUS_ID") != "D":
            invoice_map[deal_id].append({
                "id":     inv.get("ID"),
                "number": inv.get("ACCOUNT_NUMBER", inv.get("ID", "")),
                "date":   inv.get("DATE_BILL", "")[:10] if inv.get("DATE_BILL") else ""
            })
            invoice_amount_map[deal_id] += float(inv.get("PRICE", 0) or 0)

    # STEP 3 - Filter deals belum full invoice
    deals_to_process = []
    for d in all_deals:
        deal_id     = str(d["ID"])
        deal_amount = float(d.get("OPPORTUNITY", 0) or 0)
        inv_amount  = invoice_amount_map.get(deal_id, 0)
        if inv_amount < deal_amount:
            deals_to_process.append(d)

    status.text(f"📊 {len(deals_to_process)} deals perlu diproses")
    progress.progress(45)

    # STEP 4 - Invoice product rows per invoice
    status.text("📦 Mengambil product rows invoice...")
    inv_product_map = defaultdict(list)
    all_invoice_ids = list(set(
        str(inv["id"])
        for invs in invoice_map.values()
        for inv in invs
    ))
    for i, inv_id in enumerate(all_invoice_ids):
        data = bx_post("crm.productrow.list", {
            "filter": {"OWNER_TYPE": "I", "OWNER_ID": int(inv_id)},
            "select": ["OWNER_ID", "PRODUCT_ID", "PRODUCT_NAME", "QUANTITY"]
        })
        for p in (data.get("result", []) or []):
            inv_product_map[str(inv_id)].append(p)
        if (i + 1) % 50 == 0:
            pct = 45 + int((i + 1) / len(all_invoice_ids) * 15)
            progress.progress(min(pct, 60))

    progress.progress(60)

    # STEP 5 - Batch user
    status.text("👤 Mengambil info user...")
    all_user_ids = [d.get("ASSIGNED_BY_ID") for d in deals_to_process]
    user_map = get_users_batch(all_user_ids)
    progress.progress(65)

    # STEP 6 - Deal product rows
    status.text(f"📦 Mengambil product rows deals... (0/{len(deals_to_process)})")
    deal_product_map = defaultdict(list)
    for i, deal in enumerate(deals_to_process):
        deal_id = str(deal["ID"])
        data = bx_post("crm.deal.productrows.get", {"id": deal["ID"]})
        products = data.get("result", [])
        if isinstance(products, list):
            deal_product_map[deal_id] = products
        if (i + 1) % 10 == 0 or (i + 1) == len(deals_to_process):
            status.text(f"📦 Mengambil product rows deals... ({i+1}/{len(deals_to_process)})")
            pct = 65 + int((i + 1) / len(deals_to_process) * 25)
            progress.progress(min(pct, 90))

    progress.progress(90)

    # STEP 7 - Build rows
    status.text("🔨 Membangun data...")
    rows = []
    for deal in deals_to_process:
        deal_id     = str(deal["ID"])
        user_id     = str(deal.get("ASSIGNED_BY_ID", ""))
        date_closed = deal.get("DATE_CLOSED") or ""
        date_won    = date_closed[:10] if date_closed else ""
        responsible = user_map.get(user_id, user_id)

        inv_list = invoice_map.get(deal_id, [])
        invoice_label = ", ".join(
            f"{inv['number']} ({inv['date']})" if inv['date'] else inv['number']
            for inv in inv_list
        ) if inv_list else "-"

        invoiced_qty = defaultdict(float)
        for inv in inv_list:
            for p in inv_product_map.get(str(inv["id"]), []):
                pid = p.get("PRODUCT_ID") or p.get("PRODUCT_NAME", "UNKNOWN")
                invoiced_qty[pid] += float(p.get("QUANTITY", 0))

        deal_products = deal_product_map.get(deal_id, [])
        if not deal_products:
            continue

        for p in deal_products:
            pid               = p.get("PRODUCT_ID") or p.get("PRODUCT_NAME", "UNKNOWN")
            qty_ordered       = float(p.get("QUANTITY", 0))
            qty_invoiced      = invoiced_qty.get(pid, 0)
            outstanding       = qty_ordered - qty_invoiced

            if outstanding <= 0:
                continue

            unit_price        = float(p.get("PRICE", 0))
            outstanding_value = outstanding * unit_price

            rows.append({
                "Deal ID":           deal["ID"],
                "Deal Name":         deal.get("TITLE", ""),
                "Stage":             deal.get("STAGE_ID", ""),
                "Amount":            float(deal.get("OPPORTUNITY", 0) or 0),
                "Responsible":       responsible,
                "Deal Date (WON)":   date_won,
                "Product Name":      p.get("PRODUCT_NAME", ""),
                "Unit":              p.get("MEASURE_NAME", ""),
                "Unit Price":        unit_price,
                "Qty Ordered":       qty_ordered,
                "Qty Invoiced":      qty_invoiced,
                "Outstanding Qty":   outstanding,
                "Outstanding Value": outstanding_value,
                "Invoices":          invoice_label,
            })

    progress.progress(100)
    status.text(f"✅ Selesai! {len(rows)} baris data ditemukan.")
    time.sleep(0.5)
    status.empty()
    progress.empty()

    return pd.DataFrame(rows)


def build_excel(df):
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Outstanding Report")

        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter

        ws = writer.sheets["Outstanding Report"]

        header_fill = PatternFill("solid", start_color="1F4E79", end_color="1F4E79")
        header_font = Font(bold=True, color="FFFFFF", name="Arial", size=10)
        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        data_font = Font(name="Arial", size=10)
        for row_idx, row in enumerate(ws.iter_rows(min_row=2), start=2):
            fill_color = "FFFFFF" if row_idx % 2 == 0 else "EBF3FB"
            fill = PatternFill("solid", start_color=fill_color, end_color=fill_color)
            for cell in row:
                cell.font = data_font
                cell.fill = fill
                cell.alignment = Alignment(vertical="center")

        col_map = {cell.value: cell.column for cell in ws[1]}
        for col_name in ["Unit Price", "Outstanding Value", "Amount"]:
            if col_name in col_map:
                col_letter = get_column_letter(col_map[col_name])
                for cell in ws[f"{col_letter}2":f"{col_letter}{ws.max_row}"]:
                    for c in cell:
                        c.number_format = "#,##0.00"
        for col_name in ["Qty Ordered", "Qty Invoiced", "Outstanding Qty"]:
            if col_name in col_map:
                col_letter = get_column_letter(col_map[col_name])
                for cell in ws[f"{col_letter}2":f"{col_letter}{ws.max_row}"]:
                    for c in cell:
                        c.number_format = "#,##0"

        for col in ws.columns:
            max_len = max((len(str(c.value)) if c.value else 0) for c in col)
            ws.column_dimensions[get_column_letter(col[0].column)].width = min(max_len + 4, 40)
        ws.freeze_panes = "A2"

        if not df.empty:
            summary = {
                "Total Deals":             [df["Deal ID"].nunique()],
                "Total Outstanding Qty":   [df["Outstanding Qty"].sum()],
                "Total Outstanding Value": [df["Outstanding Value"].sum()],
            }
            pd.DataFrame(summary).to_excel(writer, index=False, sheet_name="Summary")

    buffer.seek(0)
    return buffer.read()


def send_email(to_email, excel_data, df):
    msg = MIMEMultipart("mixed")
    msg["Subject"] = "Laporan Outstanding Deals - Bitrix24"
    msg["From"]    = EMAIL_FROM
    msg["To"]      = to_email
    if CC_EMAILS:
        msg["Cc"] = ", ".join(CC_EMAILS)

    total_deals = df["Deal ID"].nunique() if not df.empty else 0
    total_value = df["Outstanding Value"].sum() if not df.empty else 0

    body = MIMEMultipart("alternative")
    html = f"""
    <html><body>
    <p>Halo,</p>
    <p>Berikut kami lampirkan laporan outstanding deals dari Bitrix24.</p>
    <ul>
        <li>Total Deals dengan Outstanding: <b>{total_deals} deals</b></li>
        <li>Total Outstanding Value: <b>{total_value:,.2f}</b></li>
    </ul>
    <p>Detail lengkap dapat dilihat pada file terlampir.</p>
    <br>
    <p>Terima kasih.</p>
    </body></html>
    """
    body.attach(MIMEText(html, "html"))
    msg.attach(body)

    part = MIMEBase("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    part.set_payload(excel_data)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", 'attachment; filename="outstanding_report.xlsx"')
    msg.attach(part)

    recipients = [to_email] + CC_EMAILS
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(EMAIL_FROM, recipients, msg.as_string())


# ==================== LOGIN ====================
def check_login(email, password):
    users = st.secrets.get("users", {})
    return users.get(email) == password

def login_page():
    st.set_page_config(page_title="Login - Bitrix24 Report", page_icon="🔐", layout="centered")
    st.title("🔐 Login")
    with st.form("form_login"):
        email    = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submit   = st.form_submit_button("Login", type="primary")
        if submit:
            if check_login(email, password):
                st.session_state["logged_in"] = True
                st.session_state["user_email"] = email
                st.rerun()
            else:
                st.error("Email atau password salah!")

if not st.session_state.get("logged_in"):
    login_page()
    st.stop()

# ==================== STREAMLIT UI ====================
st.set_page_config(page_title="Bitrix24 Outstanding Report", page_icon="📊", layout="wide")

col_title, col_logout = st.columns([4, 1])
with col_title:
    st.title("📊 Bitrix24 - Outstanding Deals Report")
    st.caption("Deals WON dengan qty yang belum sepenuhnya diinvoice")
with col_logout:
    st.write("")
    st.write("")
    if st.button("Logout"):
        st.session_state.clear()
        st.rerun()

# Debug single deal
with st.expander("🔍 Debug Single Deal"):
    debug_id = st.text_input("Deal ID", value="73015")
    if st.button("Cek Deal"):
        debug_single_deal(debug_id)

if st.button("🔄 Ambil Data", type="primary"):
    df = fetch_data()
    st.session_state["df"]         = df
    st.session_state["excel_data"] = build_excel(df)
    st.rerun()

if "df" in st.session_state:
    df         = st.session_state["df"]
    excel_data = st.session_state["excel_data"]

    if df.empty:
        st.info("Tidak ada data outstanding ditemukan.")
    else:
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Deals", df["Deal ID"].nunique())
        col2.metric("Total Outstanding Qty", f"{df['Outstanding Qty'].sum():,.0f}")
        col3.metric("Total Outstanding Value", f"{df['Outstanding Value'].sum():,.2f}")

        st.divider()
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.divider()

        col_dl, col_email = st.columns([1, 2])

        with col_dl:
            st.download_button(
                label="⬇️ Download Excel",
                data=excel_data,
                file_name="outstanding_report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        with col_email:
            with st.form("form_email"):
                to_email  = st.text_input("📧 Kirim ke (TO)", placeholder="email@domain.com")
                submitted = st.form_submit_button("📤 Kirim Email", type="primary")
                if submitted:
                    if not to_email:
                        st.error("Email tujuan tidak boleh kosong!")
                    else:
                        try:
                            with st.spinner("Mengirim email..."):
                                send_email(to_email, excel_data, df)
                            st.success(f"✅ Email berhasil dikirim ke {to_email}")
                        except Exception as e:
                            st.error(f"❌ Gagal kirim email: {e}")
