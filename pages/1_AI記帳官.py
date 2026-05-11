import streamlit as st
import google.generativeai as genai
from PIL import Image, ImageOps
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import json
import requests
import base64
import io
import re

st.set_page_config(page_title="AI 記帳官", page_icon="🧾", layout="wide")

# 🚨 Google Drive 資料夾 ID 與 Apps Script 網址
DRIVE_FOLDER_ID = "1SefKSIJqll7JVM8aJiCFXglMc_Z9bZ7_"
GAS_WEB_APP_URL = "https://script.google.com/macros/s/AKfycbz6PW52sypsU2nW6XcXMqaCcp3tmWPtLPhzbW2s9O4ENFksxM2IjkjWIiYwfd6Cq7Z-/exec"

def upload_to_drive(uploaded_file):
    if uploaded_file is None: return None
    try:
        file_bytes = uploaded_file.getvalue()
        b64_data = base64.b64encode(file_bytes).decode('utf-8')
        mime_type = uploaded_file.type if hasattr(uploaded_file, 'type') else 'application/octet-stream'
        file_name = uploaded_file.name if hasattr(uploaded_file, 'name') else f"receipt_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        payload = {"folderId": DRIVE_FOLDER_ID, "fileName": file_name, "mimeType": mime_type, "fileBase64": b64_data}
        response = requests.post(GAS_WEB_APP_URL, json=payload)
        result = response.json()
        if result.get("status") == "success":
            return {"name": result.get("name"), "link": result.get("link"), "id": result.get("id")}
        else:
            st.toast(f"⚠️ Drive 上傳失敗: {result.get('message')}"); return None
    except Exception as e:
        st.toast(f"⚠️ 檔案上傳失敗: {e}"); return None

# 解析項目字串的輔助函數
def parse_item_string(item_str):
    item_str = str(item_str)
    name = item_str.split('\n')[0]
    qty = 1
    curr = "TWD"
    orig_amt = 0.0
    
    m_new = re.search(r"🛒\s*(.*?)\s*\(數量:(\d+)\)\s*\|\s*原幣:([A-Za-z]+)\s*([\d\.]+)", item_str)
    if m_new:
        name, qty, curr, orig_amt = m_new.groups()
        return name.strip(), int(qty), curr.strip(), float(orig_amt)
    
    m_old = re.search(r"🤖\[AI\]\s*(.*?)\s*\(([A-Za-z]+)\s*([\d\.]+)\)", item_str)
    if m_old:
        name, curr, orig_amt = m_old.groups()
        return name.strip(), 1, curr.strip(), float(orig_amt)
        
    return name, 1, "TWD", 0.0

# --- 職人風格 CSS ---
st.markdown("""<style>h1{border-bottom: 2px solid #b87333; padding-bottom: 10px;}</style>""", unsafe_allow_html=True)

st.title("🧾 AI 旅遊記帳助手 (表列明細與防呆版)")

# --- 0. 旅程動態對接邏輯 ---
target_sheet = st.session_state.get('active_trip_sheet', 'Exp_Yunnan2026')
target_name = st.session_state.get('active_trip_name', '2026 雲南探索 (預設)')

with st.sidebar:
    st.header("🎯 存檔目標")
    st.success(f"目前連線旅程：\n\n**{target_name}**")
    st.caption(f"雲端寫入分頁：`{target_sheet}`")
    st.divider()

# --- 1. 設定 API 與連線 ---
try:
    api_key = st.secrets["api"]["gemini_key"]
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.5-flash')
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error(f"初始化連線失敗: {e}"); st.stop()

EXPECTED_COLUMNS = ["日期", "分類", "項目", "金額", "付款方式", "支付人", "來源"]
CURR_OPTIONS = ["JPY", "TWD", "USD", "CNY", "EUR", "自行輸入"]

def fetch_cloud_data():
    try:
        df = conn.read(worksheet=target_sheet, ttl=0)
        return df if not df.empty else pd.DataFrame(columns=EXPECTED_COLUMNS)
    except: return pd.DataFrame(columns=EXPECTED_COLUMNS)

def save_to_cloud(new_row_df):
    try:
        existing_df = fetch_cloud_data()
        for col in EXPECTED_COLUMNS:
            if col not in existing_df.columns: existing_df[col] = "未知"
        updated_df = pd.concat([existing_df, new_row_df], ignore_index=True)
        conn.update(worksheet=target_sheet, data=updated_df[EXPECTED_COLUMNS])
        st.cache_data.clear(); return True
    except Exception as e: st.error(f"❌ 寫入失敗: {e}"); return False

def update_in_cloud(row_index, updated_dict):
    try:
        df = fetch_cloud_data()
        for key, value in updated_dict.items(): df.at[row_index, key] = value
        conn.update(worksheet=target_sheet, data=df[EXPECTED_COLUMNS])
        st.cache_data.clear(); return True
    except: return False

def delete_from_cloud(row_index):
    try:
        df = fetch_cloud_data()
        df = df.drop(index=row_index)
        conn.update(worksheet=target_sheet, data=df[EXPECTED_COLUMNS])
        st.cache_data.clear(); return True
    except: return False

# --- 2. 圖片上傳區 ---
col_ai, col_list = st.columns([1.2, 1.8])

with col_ai:
    st.subheader("📸 收據掃描與辨識")
    
    st.markdown("##### 🌐 設定收據原始語言")
    c_lang1, c_lang2 = st.columns(2)
    sel_lang = c_lang1.selectbox("選擇收據上的語言", ["日文", "英文", "韓文", "越南文", "泰文", "其他 (自行輸入)"])
    orig_lang = c_lang2.text_input("輸入自訂語言", value="法文") if sel_lang == "其他 (自行輸入)" else sel_lang
        
    st.write("---")

    upload_mode = st.radio("選擇圖片來源", ["📷 開啟相機拍照", "📁 從相簿上傳"], horizontal=True)
    img_file = st.camera_input("拍下收據") if upload_mode == "📷 開啟相機拍照" else st.file_uploader("上傳收據圖片", type=["jpg", "jpeg", "png"])

    if img_file is not None:
        image = Image.open(img_file)
        image = ImageOps.exif_transpose(image)
        st.image(image, caption="已讀取的收據", width=300)
        
        if st.button(f"🚀 開始 AI 辨識 (從 {orig_lang} 轉譯為繁體中文)", use_container_width=True):
            with st.spinner('AI 正在拆解品項並轉譯中...'):
                prompt = f"""
                請分析這張收據，擷取資訊。
                收據上的原始語言為：【{orig_lang}】。
                請將擷取到的「店名」與每一個「品項」內容，準確翻譯為：【繁體中文】。
                如果收據有多個品項，請將所有品項個別列入「品項列表」中。
                請嚴格以 JSON 格式回傳，且 JSON 的「鍵值 (Keys)」必須維持繁體中文不變：
                {{
                  "日期": "YYYY-MM-DD",
                  "店名": "翻譯後的店名",
                  "分類": "餐飲/交通/住宿/購物/門票/其他",
                  "品項列表": [
                    {{"品名": "翻譯後的商品摘要1", "數量": 1, "單項金額": 100}},
                    {{"品名": "翻譯後的商品摘要2", "數量": 2, "單項金額": 200}}
                  ]
                }}
                """
                response = model.generate_content([prompt, image])
                try:
                    clean_text = response.text.replace('```json', '').replace('```', '').strip()
                    st.session_state['last_result'] = json.loads(clean_text)
                    st.success("辨識成功！請核對下方明細。")
                except: st.error("解析失敗，請重新拍照或檢查收據。")

    # --- 3. 確認與寫入區 (動態表格) ---
    if 'last_result' in st.session_state:
        st.divider()
        res = st.session_state['last_result']
        
        st.info("✏️ 請核對表列資訊並修正細節 (可在表格內直接點擊修改)")
        
        c_store1, c_store2, c_store3 = st.columns([2, 1.5, 1.5])
        c_store = c_store1.text_input("店鋪名稱", value=res.get("店名", "未知店鋪"))
        c_date = c_store2.date_input("日期", value=pd.to_datetime(res.get("日期", str(pd.Timestamp.now().date()))).date())
        
        cat_opts = ["餐飲", "交通", "住宿", "購物", "門票", "其他"]
        ai_cat = res.get("分類", "其他")
        c_cat = c_store3.selectbox("分類", cat_opts, index=cat_opts.index(ai_cat) if ai_cat in cat_opts else 5)
        
        raw_items = res.get("品項列表", [])
        if not isinstance(raw_items, list) or len(raw_items) == 0:
            raw_items = [{"品名": "未知名稱", "數量": 1, "單項金額": 0.0}]
            
        df_items = pd.DataFrame(raw_items)
        for col in ["品名", "數量", "單項金額"]:
            if col not in df_items.columns: df_items[col] = 1 if col == "數量" else (0.0 if col == "單項金額" else "未知名稱")
            
        df_items["數量"] = pd.to_numeric(df_items["數量"], errors='coerce').fillna(1).astype(int)
        df_items["單項金額"] = pd.to_numeric(df_items["單項金額"], errors='coerce').fillna(0.0).astype(float)
        
        # 互動式資料表
        edited_items = st.data_editor(df_items, num_rows="dynamic", use_container_width=True, key="item_editor")
        
        total_orig_amt = pd.to_numeric(edited_items["單項金額"], errors='coerce').sum()
        st.markdown(f"#### 💰 原幣總金額: **{total_orig_amt:,.2f}**")
        st.write("---")
        
        cc1, cc2 = st.columns(2)
        sel_curr = cc1.selectbox("幣別", CURR_OPTIONS)
        final_curr = cc2.text_input("輸入自訂幣別 (如: THB)", "THB") if sel_curr == "自行輸入" else sel_curr
        
        cc3, cc4 = st.columns(2)
        pay_method = cc3.selectbox("付款方式", ["現金", "信用卡", "電子支付", "公費扣款"])
        payer = cc4.text_input("支付人", value="自己")
        
        if st.button(f"✅ 確認無誤，將明細寫入『{target_name}』", type="primary", use_container_width=True):
            with st.spinner("🚀 收據備份至 Google Drive 中..."):
                drive_file = upload_to_drive(img_file)

            rates = {"JPY": st.session_state.get('jpy_rate', 0.215), "CNY": 4.5, "USD": 32.5, "EUR": 35.0, "TWD": 1.0}
            rate = rates.get(final_curr, 1.0) 
            
            # 🔴 資料防呆清洗：防止使用者在表格中留下空值導致報錯
            safe_items = edited_items.copy()
            safe_items["品名"] = safe_items["品名"].fillna("未填寫品名")
            safe_items["數量"] = pd.to_numeric(safe_items["數量"], errors='coerce').fillna(1).astype(int)
            safe_items["單項金額"] = pd.to_numeric(safe_items["單項金額"], errors='coerce').fillna(0.0).astype(float)
            
            new_entries = []
            for _, row in safe_items.iterrows():
                item_name = f"{c_store} - {row['品名']}"
                qty = int(row['數量'])
                orig_amt = float(row['單項金額'])
                twd_cost = int(orig_amt * rate)
                
                item_desc = f"🛒 {item_name} (數量:{qty}) | 原幣:{final_curr} {orig_amt}"
                if drive_file:
                    item_desc += f"\n🔗 收據: {drive_file['link']}\n🖼️ ID: {drive_file['id']}"
                    
                new_entries.append({
                    "日期": str(c_date), "分類": c_cat, "項目": item_desc,
                    "金額": twd_cost, "付款方式": pay_method, "支付人": payer, "來源": "AI 辨識"
                })
                
            if save_to_cloud(pd.DataFrame(new_entries)):
                st.success(f"🎉 寫入成功！共 {len(new_entries)} 筆明細，收據已安全備份。")
                del st.session_state['last_result']
                st.rerun()

# --- 4. 下方列表管理區 ---
with col_list:
    st.subheader("📋 已記錄之 AI 帳單明細")
    df_all = fetch_cloud_data()
    
    if not df_all.empty and "來源" in df_all.columns:
        ai_records = df_all[df_all["來源"] == "AI 辨識"]
        if not ai_records.empty:
            sorted_ai = ai_records.sort_values(by="日期", ascending=False)
            for idx, row in sorted_ai.iterrows():
                item_text = str(row.get('項目'))
                
                name_val, qty_val, curr_val, orig_amt_val = parse_item_string(item_text)
                
                drive_id_match = re.search(r"🖼️ ID:\s+([a-zA-Z0-9_-]+)", item_text)
                drive_id = drive_id_match.group(1) if drive_id_match else None

                with st.expander(f"🧾 {row.get('日期')} | {name_val} (x{qty_val}) | NT$ {row.get('金額')} | {curr_val} {orig_amt_val}"):
                    
                    col_p1, col_p2 = st.columns([1, 1])
                    with col_p1:
                        if drive_id:
                            st.image(f"https://drive.google.com/thumbnail?id={drive_id}&sz=w800", use_container_width=True)
                            st.caption("☁️ 雲端收據預覽")
                        else:
                            st.info("目前無雲端收據照片")
                    
                    with col_p2:
                        st.markdown("##### 📁 檔案管理")
                        link_match = re.search(r"🔗 收據:\s+(https://[^\s]+)", item_text)
                        if link_match:
                            st.markdown(f"✅ **[📥 點擊檢視/下載原始收據]({link_match.group(1)})**")
                        
                        new_receipt = st.file_uploader("🆕 補傳/更換收據照片", type=['jpg','png','jpeg'], key=f"up_{idx}")
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
                                        st.success("收據已更新！")
                                        st.rerun()

                    st.divider()
                    st.markdown("##### ✏️ 修改單筆明細資料")
                    
                    e_date = st.date_input("日期", value=pd.to_datetime(row.get('日期')).date(), key=f"d_{idx}")
                    e_name = st.text_input("品名 (可自由修正)", value=name_val, key=f"n_{idx}")
                    
                    ec1, ec2, ec3 = st.columns(3)
                    e_qty = ec1.number_input("數量", value=qty_val, min_value=1, key=f"q_{idx}")
                    e_orig_amt = ec2.number_input("單項原始金額", value=orig_amt_val, key=f"oa_{idx}")
                    
                    e_curr_sel = ec3.selectbox("幣別", CURR_OPTIONS, index=CURR_OPTIONS.index(curr_val) if curr_val in CURR_OPTIONS else len(CURR_OPTIONS)-1, key=f"cs_{idx}")
                    e_curr = ec3.text_input("自訂幣別", value=curr_val, key=f"cc_{idx}") if e_curr_sel == "自行輸入" else e_curr_sel
                    
                    ec4, ec5, ec6 = st.columns(3)
                    e_twd = ec4.number_input("台幣金額 (TWD)", value=float(row.get('金額', 0)), key=f"ta_{idx}")
                    
                    pm_opts = ["現金", "信用卡", "電子支付", "公費扣款"]
                    pm_val = row.get('付款方式', '現金')
                    e_pm = ec5.selectbox("付款方式", pm_opts, index=pm_opts.index(pm_val) if pm_val in pm_opts else 0, key=f"p_{idx}")
                    
                    e_pyr = ec6.text_input("支付人", value=row.get('支付人'), key=f"y_{idx}")
                    
                    b1, b2 = st.columns(2)
                    if b1.button("💾 儲存明細修改", key=f"s_{idx}", use_container_width=True):
                        links = ""
                        link_match = re.search(r"(\n🔗 收據:.*)", item_text, re.DOTALL)
                        if link_match: links = link_match.group(1)
                        
                        new_item_desc = f"🛒 {e_name} (數量:{e_qty}) | 原幣:{e_curr} {e_orig_amt}{links}"
                        
                        update_in_cloud(idx, {
                            "日期": str(e_date), "項目": new_item_desc, "金額": int(e_twd), 
                            "付款方式": e_pm, "支付人": e_pyr
                        })
                        st.rerun()
                    if b2.button("🗑️ 刪除這筆明細", key=f"del_{idx}", use_container_width=True):
                        delete_from_cloud(idx)
                        st.rerun()
        else: st.info("目前尚無 AI 辨識紀錄。")
