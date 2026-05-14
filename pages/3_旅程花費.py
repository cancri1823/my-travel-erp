import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
import requests
import base64
import io
import re

st.set_page_config(page_title="旅程花費看板", page_icon="💰", layout="wide")

# 🚨 你的專屬 Google Drive 資料夾 ID 與 Apps Script 網址
DRIVE_FOLDER_ID = "1SefKSIJqll7JVM8aJiCFXglMc_Z9bZ7_"
GAS_WEB_APP_URL = "https://script.google.com/macros/s/AKfycbz6PW52sypsU2nW6XcXMqaCcp3tmWPtLPhzbW2s9O4ENFksxM2IjkjWIiYwfd6Cq7Z-/exec"

def upload_to_drive(uploaded_file):
    """透過 Google Apps Script 中繼站上傳檔案"""
    if uploaded_file is None: return None
    try:
        file_bytes = uploaded_file.getvalue()
        b64_data = base64.b64encode(file_bytes).decode('utf-8')
        mime_type = uploaded_file.type if hasattr(uploaded_file, 'type') else 'application/octet-stream'
        file_name = uploaded_file.name if hasattr(uploaded_file, 'name') else f"receipt_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}"
        
        payload = {"folderId": DRIVE_FOLDER_ID, "fileName": file_name, "mimeType": mime_type, "fileBase64": b64_data}
        response = requests.post(GAS_WEB_APP_URL, json=payload)
        result = response.json()
        
        if result.get("status") == "success":
            return {"name": result.get("name"), "link": result.get("link"), "id": result.get("id")}
        else:
            st.toast(f"⚠️ Drive 上傳失敗: {result.get('message')}"); return None
    except Exception as e:
        st.toast(f"⚠️ 檔案上傳失敗: {e}"); return None

# --- 輔助函數：解析字串中的細節 ---
def parse_expense_item(item_str):
    item_str = str(item_str)
    name = item_str.split('\n')[0]
    store, loc, curr, orig_amt, fee = "", "", "TWD", 0.0, 0.0
    
    # 解析新版格式: 🛒 品名 @商店(位置) | 原幣:JPY 1500 | 手續費:23
    m_new = re.search(r"🛒\s*(.*?)(?:\s*@(.*?)(\((.*?)\))?)?\s*\|\s*原幣:([A-Za-z]+)\s*([\d\.]+)(?:\s*\|\s*手續費:([\d\.]+))?", item_str)
    if m_new:
        name = m_new.group(1).strip()
        store = m_new.group(2).strip() if m_new.group(2) else ""
        loc = m_new.group(4).strip() if m_new.group(4) else ""
        curr = m_new.group(5).strip()
        orig_amt = float(m_new.group(6))
        fee = float(m_new.group(7)) if m_new.group(7) else 0.0
        return name, store, loc, curr, orig_amt, fee
        
    # 兼容舊版格式: 品名 (JPY 1500) 或 🤖[AI] 品名 (JPY 1500)
    m_old = re.search(r"(?:🤖\[AI\]\s*)?(.*?)\s*\(([A-Za-z]+)\s*([\d\.]+)\)", item_str)
    if m_old:
        name = m_old.group(1).strip()
        curr = m_old.group(2).strip()
        orig_amt = float(m_old.group(3))
        return name, store, loc, curr, orig_amt, fee
        
    return name, store, loc, "TWD", 0.0, 0.0

# --- 0. 旅程動態對接邏輯 ---
target_sheet = st.session_state.get('active_trip_sheet', 'Exp_Yunnan2026')
target_name = st.session_state.get('active_trip_name', '2026 雲南探索 (預設)')

# --- 1. 雲端連線與資料讀取 ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error(f"連線失敗: {e}"); st.stop()

EXPECTED_COLUMNS = ["日期", "分類", "項目", "金額", "付款方式", "支付人", "來源"]

# 讀取「雲端預算」的專屬功能
def get_cloud_budget():
    try:
        df = conn.read(worksheet=target_sheet, ttl=0)
        if not df.empty and '分類' in df.columns:
            budget_row = df[df['分類'] == '系統設定']
            if not budget_row.empty:
                return int(budget_row['金額'].values[0])
        return 50000 
    except:
        return 50000

# 寫入「雲端預算」的專屬功能
def save_budget_to_cloud(new_budget):
    try:
        df = conn.read(worksheet=target_sheet, ttl=0)
        for col in EXPECTED_COLUMNS:
            if not df.empty and col not in df.columns: df[col] = "未知"
            
        if not df.empty and '分類' in df.columns:
            budget_idx = df[df['分類'] == '系統設定'].index
            if not budget_idx.empty:
                df.at[budget_idx[0], '金額'] = new_budget
            else:
                new_row = pd.DataFrame([{"日期": str(pd.Timestamp.now().date()), "分類": "系統設定", "項目": "總預算", "金額": new_budget, "付款方式": "-", "支付人": "-", "來源": "系統"}])
                df = pd.concat([df, new_row], ignore_index=True)
        else:
            df = pd.DataFrame([{"日期": str(pd.Timestamp.now().date()), "分類": "系統設定", "項目": "總預算", "金額": new_budget, "付款方式": "-", "支付人": "-", "來源": "系統"}])
            
        conn.update(worksheet=target_sheet, data=df[EXPECTED_COLUMNS])
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"❌ 預算更新失敗: {e}")
        return False

def fetch_data():
    try:
        df = conn.read(worksheet=target_sheet, ttl=0)
        if df.empty: return pd.DataFrame(columns=EXPECTED_COLUMNS)
        
        # 過濾掉預算設定的資料行
        df = df[df['分類'] != '系統設定'].copy()
        
        df["金額"] = pd.to_numeric(df["金額"], errors='coerce').fillna(0)
        if "分類" in df.columns:
            df["分類"] = df["分類"].replace({"門票娛樂": "門票/娛樂", "門票": "門票/娛樂"})
        return df
    except: return pd.DataFrame(columns=EXPECTED_COLUMNS)

def save_to_cloud(new_row_df):
    try:
        existing_df = conn.read(worksheet=target_sheet, ttl=0)
        for col in EXPECTED_COLUMNS:
            if not existing_df.empty and col not in existing_df.columns: existing_df[col] = "未知"
        updated_df = new_row_df if existing_df.empty else pd.concat([existing_df, new_row_df], ignore_index=True)
        conn.update(worksheet=target_sheet, data=updated_df[EXPECTED_COLUMNS])
        st.cache_data.clear(); return True
    except Exception as e: st.error(f"❌ 寫入失敗: {e}"); return False

def update_in_cloud(row_index, updated_dict):
    try:
        df = conn.read(worksheet=target_sheet, ttl=0)
        for key, value in updated_dict.items(): df.at[row_index, key] = value
        conn.update(worksheet=target_sheet, data=df[EXPECTED_COLUMNS])
        st.cache_data.clear(); return True
    except Exception as e: st.error(f"❌ 雲端更新失敗: {e}"); return False

def delete_from_cloud(row_index):
    try:
        df = conn.read(worksheet=target_sheet, ttl=0)
        df = df.drop(index=row_index)
        conn.update(worksheet=target_sheet, data=df[EXPECTED_COLUMNS])
        st.cache_data.clear(); return True
    except Exception as e: st.error(f"❌ 雲端刪除失敗: {e}"); return False

# --- 側邊欄與預算設定 ---
cloud_budget = get_cloud_budget()

with st.sidebar:
    st.header("🎯 核心戰情室")
    st.success(f"目前檢視旅程：\n\n**{target_name}**")
    st.caption(f"數據來源分頁：`{target_sheet}`")
    st.divider()
    
    budget_input = st.number_input("💸 設定此旅程總預算 (TWD)", min_value=0, value=cloud_budget)
    if st.button("💾 儲存總預算", type="primary", use_container_width=True):
        with st.spinner("同步預算至雲端..."):
            if save_budget_to_cloud(budget_input):
                st.success("✅ 預算已永久保存！")
                st.rerun()

# --- 2. 數據計算 ---
df_all = fetch_data()
total_spent = int(df_all["金額"].sum()) if not df_all.empty else 0
budget = get_cloud_budget() 
remaining = budget - total_spent
progress = min(total_spent / budget, 1.0) if budget > 0 else 0

# --- 職人風格 CSS ---
st.markdown("""
    <style>
    h1 { border-bottom: 2px solid #b87333; padding-bottom: 10px; }
    .stMetric { background-color: #1e1e1e; padding: 15px; border-radius: 10px; border-left: 5px solid #b87333; }
    .calc-box { background-color: #1e1e1e; padding: 10px; border-radius: 5px; border-left: 4px solid #b87333; margin-top: 5px; margin-bottom: 15px;}
    </style>
""", unsafe_allow_html=True)

st.title(f"💰 {target_name}：花費戰情室")

# --- 3. 頂部指標卡 ---
c1, c2, c3 = st.columns(3)
c1.metric("總預算", f"NT$ {budget:,}")
c2.metric("已支出", f"NT$ {total_spent:,}", delta=f"{(progress*100):.1f}%", delta_color="inverse")
c3.metric("剩餘金額", f"NT$ {remaining:,}")

st.write("")
if progress >= 0.8:
    st.warning(f"⚠️ 預算警報：已使用 {progress*100:.1f}%，請留意支出！")
st.progress(progress)

st.divider()

# --- 4. 中間佈局：新增花費與明細列表 ---
col_form, col_list = st.columns([1.1, 1.9])

with col_form:
    st.subheader("➕ 新增手動支出")
    with st.container():
        e_date = st.date_input("日期")
        c_cat, c_name = st.columns([1, 1.5])
        e_cat = c_cat.selectbox("分類", ["餐飲", "交通", "購物", "門票/娛樂", "住宿", "其他"])
        e_item = c_name.text_input("項目名稱", placeholder="例如：藥妝店採買")
        
        c_st, c_lc = st.columns(2)
        e_store = c_st.text_input("購買商店", placeholder="例如：大國藥妝")
        e_loc = c_lc.text_input("商店位置", placeholder="例如：心齋橋")
        
        st.write("---")
        c_amt, c_curr, c_cust = st.columns([1.2, 1, 1])
        e_amt = c_amt.number_input("原幣金額", min_value=0.0)
        e_curr_sel = c_curr.selectbox("幣別", ["TWD", "USD", "EUR", "JPY", "CNY", "自行輸入"])
        e_curr_cust = c_cust.text_input("自訂幣別", placeholder="如: THB") if e_curr_sel == "自行輸入" else e_curr_sel
        
        c_payer, c_pay_m = st.columns(2)
        e_pay_m = c_pay_m.selectbox("付款方式", ["現金", "信用卡", "電子支付", "公費扣款"])
        e_payer = c_payer.text_input("支付人", value="自己")
        
        e_fee = 0.0
        final_curr = e_curr_cust if e_curr_sel == "自行輸入" else e_curr_sel
        if final_curr != "TWD" and e_pay_m == "信用卡":
            e_fee = st.number_input("國外交易處理費 (TWD)", min_value=0.0, value=0.0, step=10.0)
            
        rates = {"JPY": st.session_state.get('jpy_rate', 0.215), "CNY": 4.5, "USD": 32.5, "EUR": 35.0, "TWD": 1.0}
        rate = rates.get(final_curr, 1.0)
        twd_val = int(e_amt * rate) + int(e_fee)
        
        st.markdown(f"<div class='calc-box'>💡 <b>自動計算總計 (TWD):</b> NT$ {twd_val:,} </div>", unsafe_allow_html=True)
        e_file = st.file_uploader("上傳收據/發票/照片", type=['jpg', 'png', 'jpeg', 'pdf'])
        
        if st.button("🚀 記錄支出至雲端", type="primary", use_container_width=True):
            if e_item and e_amt > 0:
                with st.spinner("檔案備份中..."):
                    d_file = upload_to_drive(e_file)
                
                store_tag = f" @{e_store}" if e_store else ""
                loc_tag = f"({e_loc})" if e_loc else ""
                fee_tag = f" | 手續費:{e_fee}" if e_fee > 0 else ""
                
                item_desc = f"🛒 {e_item}{store_tag}{loc_tag} | 原幣:{final_curr} {e_amt}{fee_tag}"
                if d_file:
                    item_desc += f"\n🔗 收據: {d_file['link']}\n🖼️ ID: {d_file['id']}"
                
                new_row = pd.DataFrame([{
                    "日期": str(e_date), "分類": e_cat, "項目": item_desc,
                    "金額": twd_val, "付款方式": e_pay_m, "支付人": e_payer, "來源": "手動輸入"
                }])
                
                with st.spinner("同步中..."):
                    if save_to_cloud(new_row):
                        st.success("✅ 已同步至雲端帳本！"); st.rerun()
            else: st.error("請完整填寫項目與金額")

with col_list:
    st.subheader("📜 總花費明細 (雲端即時連動)")
    
    # 🟢 核心新增：搜尋功能
    search_query = st.text_input("🔍 搜尋明細", placeholder="搜尋項目、分類、支付人或商店關鍵字...")
    
    if not df_all.empty:
        # 先進行排序
        df_display = df_all.sort_values(by="日期", ascending=False)
        
        # 執行過濾邏輯
        if search_query:
            # 搜尋項目、分類、支付人（忽略大小寫）
            df_display = df_display[
                df_display['項目'].str.contains(search_query, case=False, na=False) |
                df_display['分類'].str.contains(search_query, case=False, na=False) |
                df_display['支付人'].str.contains(search_query, case=False, na=False)
            ]
            st.caption(f"已顯示關於『{search_query}』的 {len(df_display)} 筆搜尋結果")

        for idx, row in df_display.iterrows():
            item_text = str(row.get('項目', ''))
            name_val, store_val, loc_val, curr_val, orig_amt_val, fee_val = parse_expense_item(item_text)
            
            drive_id_match = re.search(r"🖼️ ID:\s+([a-zA-Z0-9_-]+)", item_text)
            drive_id = drive_id_match.group(1) if drive_id_match else None
            
            exp_title = f"🧾 {row.get('日期', '')} | [{row.get('分類', '其他')}] {name_val} - NT$ {row.get('金額', 0):,} ({row.get('支付人', '未知')})"
            
            with st.expander(exp_title):
                # 收據預覽與下載區
                col_p1, col_p2 = st.columns([1, 1])
                with col_p1:
                    if drive_id:
                        if ".pdf" in item_text.lower():
                            st.info("📄 PDF 檔案憑證")
                        else:
                            st.image(f"https://drive.google.com/thumbnail?id={drive_id}&sz=w800", use_container_width=True)
                            st.caption("☁️ 雲端收據預覽")
                    else: st.info("目前無雲端收據照片")
                
                with col_p2:
                    st.markdown("##### 📁 檔案管理")
                    link_match = re.search(r"🔗 收據:\s+(https://[^\s]+)", item_text)
                    if link_match:
                        st.markdown(f"✅ **[📥 點擊檢視/下載原始收據]({link_match.group(1)})**")
                    
                    new_receipt = st.file_uploader("🆕 補傳/更換收據照片", type=['jpg','png','jpeg','pdf'], key=f"up_{idx}")
                    if st.button("🚀 上傳並更新連結", key=f"btn_up_{idx}"):
                        if new_receipt:
                            with st.spinner("上傳中..."):
                                new_drive = upload_to_drive(new_receipt)
                                if new_drive:
                                    updated_item = re.sub(r"🔗 收據: https://[^\s]+", f"🔗 收據: {new_drive['link']}", item_text)
                                    updated_item = re.sub(r"🖼️ ID: [a-zA-Z0-9_-]+", f"🖼️ ID: {new_drive['id']}", updated_item)
                                    if "🔗 收據:" not in updated_item:
                                        updated_item += f"\n🔗 收據: {new_drive['link']}\n🖼️ ID: {new_drive['id']}"
                                    update_in_cloud(idx, {"項目": updated_item})
                                    st.success("收據已更新！"); st.rerun()

                st.divider()
                st.markdown("##### ✏️ 修改單筆明細資料")
                
                try: def_date = pd.to_datetime(row.get('日期')).date()
                except: def_date = pd.Timestamp.now().date()
                
                c_ed1, c_ed2 = st.columns([1, 1.5])
                new_date = c_ed1.date_input("日期", value=def_date, key=f"ex_d_{idx}")
                cat_opts = ["餐飲", "交通", "購物", "門票/娛樂", "住宿", "其他"]
                cat_val = row.get('分類', '其他')
                cat_idx = cat_opts.index(cat_val) if cat_val in cat_opts else 5
                new_cat = c_ed2.selectbox("分類", cat_opts, index=cat_idx, key=f"ex_c_{idx}")
                
                new_item = st.text_input("項目名稱", value=name_val, key=f"ex_i_{idx}")
                
                ce_st, ce_lc = st.columns(2)
                new_store = ce_st.text_input("購買商店", value=store_val, key=f"ex_st_{idx}")
                new_loc = ce_lc.text_input("商店位置", value=loc_val, key=f"ex_lc_{idx}")
                
                ce1, ce2, ce3 = st.columns(3)
                new_orig_amt = ce1.number_input("原幣金額", value=float(orig_amt_val), key=f"ex_oa_{idx}")
                new_curr = ce2.text_input("幣別", value=curr_val, key=f"ex_curr_{idx}")
                new_fee = ce3.number_input("國外處理費", value=float(fee_val), key=f"ex_fee_{idx}")
                
                ce4, ce5, ce6 = st.columns(3)
                new_twd = ce4.number_input("台幣金額 (TWD)", value=float(row.get('金額', 0)), key=f"ex_a_{idx}")
                
                pm_opts = ["現金", "信用卡", "電子支付", "公費扣款"]
                pm_val = row.get('付款方式', '現金')
                pm_idx = pm_opts.index(pm_val) if pm_val in pm_opts else 0
                new_pay_m = ce5.selectbox("付款方式", pm_opts, index=pm_idx, key=f"ex_pm_{idx}")
                new_payer = ce6.text_input("支付人", value=row.get('支付人', '自己'), key=f"ex_py_{idx}")
                
                btn_col1, btn_col2 = st.columns(2)
                if btn_col1.button("💾 儲存明細修改", key=f"ex_sv_{idx}"):
                    links = ""
                    link_match = re.search(r"(\n🔗 收據:.*)", item_text, re.DOTALL)
                    if link_match: links = link_match.group(1)
                    
                    store_tag = f" @{new_store}" if new_store else ""
                    loc_tag = f"({new_loc})" if new_loc else ""
                    fee_tag = f" | 手續費:{new_fee}" if new_fee > 0 else ""
                    
                    new_item_desc = f"🛒 {new_item}{store_tag}{loc_tag} | 原幣:{new_curr} {new_orig_amt}{fee_tag}{links}"
                    
                    updated_data = {"日期": str(new_date), "分類": new_cat, "項目": new_item_desc, "金額": int(new_twd), "付款方式": new_pay_m, "支付人": new_payer}
                    with st.spinner("更新雲端資料中..."):
                        if update_in_cloud(idx, updated_data):
                            st.success("✅ 雲端資料已更新！"); st.rerun()
                            
                if btn_col2.button("🗑️ 刪除這筆明細", key=f"ex_del_{idx}"):
                    with st.spinner("刪除雲端資料中..."):
                        if delete_from_cloud(idx):
                            st.success("✅ 該筆紀錄已從 Google Sheets 刪除！"); st.rerun()
        
        # 分類統計區塊 
        st.write("---")
        st.caption("📂 分類支出統計 (TWD)")
        summary = df_all.groupby("分類")["金額"].sum().reset_index()
        if total_spent > 0:
            summary["比例"] = (summary["金額"] / total_spent * 100).map("{:.1f}%".format)
        else:
            summary["比例"] = "0.0%"
        st.table(summary)
    else:
        st.info("目前雲端帳本尚無紀錄，趕快記下第一筆花費吧！")
