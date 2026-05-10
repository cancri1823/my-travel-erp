import streamlit as st
import google.generativeai as genai
from PIL import Image, ImageOps
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import json

st.set_page_config(page_title="AI 記帳官", page_icon="🧾", layout="wide")

# --- 職人風格 CSS ---
st.markdown("""<style>h1{border-bottom: 2px solid #b87333; padding-bottom: 10px;}</style>""", unsafe_allow_html=True)

st.title("🧾 AI 旅遊記帳助手")

# --- 0. 旅程動態對接邏輯 ---
target_sheet = st.session_state.get('active_trip_sheet', 'Exp_Yunnan2026')
target_name = st.session_state.get('active_trip_name', '2026 雲南探索 (預設)')

with st.sidebar:
    st.header("🎯 存檔目標")
    st.success(f"目前連線旅程：\n\n**{target_name}**")
    st.caption(f"雲端寫入分頁：`{target_sheet}`")
    st.divider()

# --- 1. 設定 API 與 Google Sheets 連線 ---
try:
    api_key = st.secrets["api"]["gemini_key"]
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.5-flash')
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error(f"初始化連線失敗: {e}")
    st.stop()

EXPECTED_COLUMNS = ["日期", "分類", "項目", "金額", "付款方式", "支付人", "來源"]
CURR_OPTIONS = ["JPY", "TWD", "USD", "CNY", "EUR", "自行輸入"]

# --- 雲端操作函數群 ---
def fetch_cloud_data():
    try:
        df = conn.read(worksheet=target_sheet, ttl=0)
        if df.empty: return pd.DataFrame(columns=EXPECTED_COLUMNS)
        return df
    except:
        return pd.DataFrame(columns=EXPECTED_COLUMNS)

def save_to_cloud(new_row_df):
    try:
        existing_df = fetch_cloud_data()
        # 確保欄位一致性
        for col in EXPECTED_COLUMNS:
            if col not in existing_df.columns:
                existing_df[col] = "未知"
                
        updated_df = pd.concat([existing_df, new_row_df], ignore_index=True)
        updated_df = updated_df[EXPECTED_COLUMNS]
        conn.update(worksheet=target_sheet, data=updated_df)
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"❌ 雲端寫入失敗: {e}")
        return False

def update_in_cloud(row_index, updated_dict):
    try:
        df = fetch_cloud_data()
        for key, value in updated_dict.items():
            df.at[row_index, key] = value
        conn.update(worksheet=target_sheet, data=df[EXPECTED_COLUMNS])
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"❌ 雲端更新失敗: {e}"); return False

def delete_from_cloud(row_index):
    try:
        df = fetch_cloud_data()
        df = df.drop(index=row_index)
        conn.update(worksheet=target_sheet, data=df[EXPECTED_COLUMNS])
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"❌ 雲端刪除失敗: {e}"); return False

# --- 2. 圖片上傳區 ---
col_ai, col_list = st.columns([1.2, 1.8])

with col_ai:
    st.subheader("📸 收據掃描與辨識")
    upload_mode = st.radio("選擇圖片來源", ["📷 開啟相機拍照", "📁 從相簿上傳"], horizontal=True)
    img_file = st.camera_input("拍下收據") if upload_mode == "📷 開啟相機拍照" else st.file_uploader("上傳收據圖片", type=["jpg", "jpeg", "png"])

    if img_file is not None:
        image = Image.open(img_file)
        image = ImageOps.exif_transpose(image)
        st.image(image, caption="已讀取的收據", width=300)
        
        if st.button("🚀 開始 AI 辨識", use_container_width=True):
            with st.spinner('AI 正在判讀收據內容...'):
                prompt = """
                請分析這張收據，擷取資訊並翻譯為繁體中文。
                請嚴格以 JSON 格式回傳：
                {"日期": "YYYY-MM-DD", "店名": "店名", "總金額": 數字, "品項": "品項摘要", "分類": "餐飲/交通/住宿/購物/門票娛樂/其他"}
                """
                response = model.generate_content([prompt, image])
                try:
                    clean_text = response.text.replace('```json', '').replace('```', '').strip()
                    st.session_state['last_result'] = json.loads(clean_text)
                    st.success("辨識成功！")
                except: st.error("解析失敗，請重新拍照或檢查收據。")

    # --- 3. 確認與寫入區 (包含自定義幣別) ---
    if 'last_result' in st.session_state:
        st.divider()
        res = st.session_state['last_result']
        
        st.info("請核對資訊並設定幣別與支付方式")
        c1, c2 = st.columns(2)
        c1.metric("店鋪", res.get("店名", "未知"))
        c2.metric("辨識金額", f"{res.get('總金額', 0)}")
        
        st.write("---")
        
        # 🔴 核心改動：自定義幣別選擇
        cp1, cp2 = st.columns(2)
        sel_curr = cp1.selectbox("幣別", CURR_OPTIONS)
        final_curr = cp2.text_input("輸入自訂幣別 (如: THB)", "THB") if sel_curr == "自行輸入" else sel_curr
        
        # 支付資訊
        cp3, cp4 = st.columns(2)
        payer = cp3.text_input("支付人", value="自己")
        pay_method = cp4.selectbox("付款方式", ["現金", "信用卡", "電子支付", "公費扣款"])
        
        if st.button(f"✅ 確認無誤，寫入『{target_name}』", type="primary", use_container_width=True):
            # 簡單匯率換算邏輯
            rates = {"JPY": st.session_state.get('jpy_rate', 0.215), "CNY": 4.5, "USD": 32.5, "EUR": 35.0, "TWD": 1.0}
            rate = rates.get(final_curr, 1.0) # 非預設幣別暫時以 1.0 計，建議手動填寫總帳
            
            twd_cost = int(res.get("總金額", 0) * rate)
            
            new_entry = pd.DataFrame([{
                "日期": res.get("日期", str(pd.Timestamp.now().date())),
                "分類": res.get("分類", "其他"),
                "項目": f"🤖[AI] {res.get('店名')} ({final_curr} {res.get('總金額')})",
                "金額": twd_cost,
                "付款方式": pay_method,
                "支付人": payer,      
                "來源": "AI 辨識"
            }])
            
            if save_to_cloud(new_entry):
                st.success("🎉 寫入成功！")
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
                with st.expander(f"🧾 {row.get('日期')} | {row.get('項目')} - NT$ {row.get('金額')} ({row.get('支付人')})"):
                    # 編輯表單
                    new_date = st.date_input("日期", value=pd.to_datetime(row.get('日期')).date(), key=f"d_{idx}")
                    new_item = st.text_input("項目", value=row.get('項目'), key=f"i_{idx}")
                    c1, c2, c3 = st.columns(3)
                    new_amt = c1.number_input("金額 (TWD)", value=float(row.get('金額', 0)), key=f"a_{idx}")
                    new_pay = c2.selectbox("付款", ["現金", "信用卡", "電子支付", "公費扣款"], index=0, key=f"p_{idx}")
                    new_pyr = c3.text_input("支付人", value=row.get('支付人'), key=f"y_{idx}")
                    
                    b1, b2 = st.columns(2)
                    if b1.button("💾 儲存修改", key=f"s_{idx}", use_container_width=True):
                        update_in_cloud(idx, {"日期": str(new_date), "項目": new_item, "金額": int(new_amt), "付款方式": new_pay, "支付人": new_pyr})
                        st.rerun()
                    if b2.button("🗑️ 刪除", key=f"del_{idx}", use_container_width=True):
                        delete_from_cloud(idx)
                        st.rerun()
        else: st.info("目前尚無 AI 辨識紀錄。")