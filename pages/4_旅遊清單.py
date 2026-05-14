import streamlit as st
import pandas as pd
import requests
import base64
import io
import re
from streamlit_gsheets import GSheetsConnection

st.set_page_config(page_title="旅遊清單與準備", page_icon="📝", layout="wide")

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
        file_name = uploaded_file.name if hasattr(uploaded_file, 'name') else f"file_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}"
        
        payload = {"folderId": DRIVE_FOLDER_ID, "fileName": file_name, "mimeType": mime_type, "fileBase64": b64_data}
        response = requests.post(GAS_WEB_APP_URL, json=payload)
        result = response.json()
        
        if result.get("status") == "success":
            return {"name": result.get("name"), "link": result.get("link"), "id": result.get("id")}
        else:
            st.toast(f"⚠️ Drive 上傳失敗: {result.get('message')}")
            return None
    except Exception as e:
        st.toast(f"⚠️ 檔案上傳失敗: {e}")
        return None

# --- 0. 旅程動態對接邏輯 ---
target_sheet = st.session_state.get('active_trip_sheet', 'Exp_Yunnan2026')
target_name = st.session_state.get('active_trip_name', '2026 雲南探索 (預設)')

with st.sidebar:
    st.header("🎯 存檔目標")
    st.success(f"目前連線旅程：\n\n**{target_name}**")
    st.caption(f"雲端寫入分頁：`{target_sheet}`")
    if st.button("🔄 手動從雲端重新整理"):
        st.session_state.has_synced = False
        st.cache_data.clear()
        st.rerun()
    st.divider()

# --- 1. 建立雲端連線與資料邏輯 ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error(f"❌ 連線初始化失敗: {e}"); st.stop()

EXPECTED_COLUMNS = ["日期", "分類", "項目", "金額", "付款方式", "支付人", "來源"]
CURR_OPTIONS = ["TWD", "JPY", "USD", "EUR", "CNY", "自行輸入"]
PLATFORMS = ["Booking", "Agoda", "Klook", "KKday", "Trip", "易遊網", "官方網站", "其他(可自行輸入)"]

def get_rate(curr):
    rates = {"JPY": st.session_state.get('jpy_rate', 0.215), "CNY": 4.5, "USD": 32.5, "EUR": 35.0, "TWD": 1.0}
    return rates.get(curr, 1.0)

# --- 🟢 核心升級：雲端記憶智慧追加同步機制 (Smart Sync) ---
def sync_from_cloud():
    try:
        df = conn.read(worksheet=target_sheet, ttl=0)
        if df.empty: return
        
        def extract_link(text):
            m = re.search(r"🔗\s*(https://[^\s]+)", str(text))
            return m.group(1) if m else None

        def extract_id(text):
            m = re.search(r"id=([a-zA-Z0-9_-]+)", str(text))
            return m.group(1) if m else None

        # 1. 同步保險
        if 'ins_records' not in st.session_state or not st.session_state.ins_records:
            sub_df = df[df['來源'] == '清單-保險']
            records = []
            for _, row in sub_df.iterrows():
                item = str(row.get('項目', ''))
                name = item.split("\n")[0].replace("保險：", "").strip()
                records.append({
                    "名稱": name, "編號": "雲端同步", "日期": str(row.get('日期','')), 
                    "金額": row.get('金額', 0), "付款方式": row.get('付款方式',''), "支付人": row.get('支付人',''),
                    "Drive連結": extract_link(item), "檔案名": "雲端憑證"
                })
            if records: st.session_state.ins_records = records

        # 2. 同步交通 (確保起訖點、公司等欄位精準還原)
        if 'trans_records' not in st.session_state or not st.session_state.trans_records:
            sub_df = df[df['來源'] == '清單-交通']
            records = []
            for _, row in sub_df.iterrows():
                item = str(row.get('項目', ''))
                first_line = item.split("\n")[0]
                # 嘗試解析: 飛機: [公司] 起點➔訖點 (來回)
                t_type, t_comp, t_st, t_ed = "交通", "雲端同步", first_line, ""
                m1 = re.search(r"^(.*?):\s*\[(.*?)\]\s*(.*?)➔(.*?)\s*(\(.*\))?$", first_line)
                if m1:
                    t_type, t_comp, t_st, t_ed = m1.group(1), m1.group(2), m1.group(3), m1.group(4)
                else:
                    t_st = first_line

                records.append({
                    "種類": t_type, "公司": t_comp, "平台": "", "訂單號": "", "來回": False,
                    "起點": t_st.strip(), "訖點": t_ed.strip(), "去程班次": "", "回程班次": "",
                    "金額": row.get('金額',0), "幣別": "TWD", "手續費": 0, "總台幣": row.get('金額',0),
                    "付款方式": row.get('付款方式',''), "支付人": row.get('支付人',''),
                    "Drive連結": extract_link(item), "檔案名": "雲端車票"
                })
            if records: st.session_state.trans_records = records

        # 3. 同步住宿 (確保飯店名稱精準還原)
        if 'hotel_records' not in st.session_state or not st.session_state.hotel_records:
            sub_df = df[df['來源'] == '清單-住宿']
            records = []
            for _, row in sub_df.iterrows():
                item = str(row.get('項目', ''))
                name = item.split("\n")[0].replace("飯店：", "").strip()
                records.append({
                    "飯店": name, "平台": "", "訂單號": "", "入住": str(row.get('日期','')), "晚數": 0,
                    "金額": row.get('金額',0), "幣別": "TWD", "手續費": 0, "總台幣": row.get('金額',0), "支付人": row.get('支付人',''),
                    "Drive連結": extract_link(item), "檔案名": "雲端憑證"
                })
            if records: st.session_state.hotel_records = records

        # 4. 同步票卷
        if 'ticket_records' not in st.session_state or not st.session_state.ticket_records:
            sub_df = df[df['來源'] == '清單-票卷']
            records = []
            for _, row in sub_df.iterrows():
                item = str(row.get('項目', ''))
                name = item.split("\n")[0].strip()
                t_type = "票卷"
                if "：" in name:
                    t_type, name = name.split("：", 1)
                records.append({
                    "種類": t_type.strip(), "名稱": name.strip(), "平台": "", "訂單號": "",
                    "金額": row.get('金額',0), "幣別": "TWD", "手續費": 0, "總台幣": row.get('金額',0),
                    "使用日": str(row.get('日期','')), "支付人": row.get('支付人',''),
                    "Drive連結": extract_link(item), "檔案名": "雲端票卷"
                })
            if records: st.session_state.ticket_records = records

        # 5. 同步裝備
        if 'packing_list' not in st.session_state or not st.session_state.packing_list:
            sub_df = df[df['來源'] == '清單-裝備']
            records = []
            for _, row in sub_df.iterrows():
                item = str(row.get('項目', ''))
                first_line = item.split("\n")[0]
                name = first_line.replace("裝備:", "").strip()
                m2 = re.search(r"^(.*?)(?:\(\d+個\))?(?:\s*@.*)?$", name)
                if m2: name = m2.group(1).strip()
                d_link = extract_link(item)
                
                records.append({
                    "名稱": name, "數量": 1, "商店": "", "位置": "", "狀態": False, "新購": True,
                    "金額": row.get('金額',0), "幣別": "TWD", "手續費": 0, "總台幣": row.get('金額',0), "支付人": row.get('支付人',''),
                    "Drive連結": d_link, "DriveID": extract_id(d_link)
                })
            if records: st.session_state.packing_list = records

        # 6. 同步伴手禮
        if 'gift_list' not in st.session_state or not st.session_state.gift_list:
            sub_df = df[df['來源'] == '清單-伴手禮']
            records = []
            for _, row in sub_df.iterrows():
                item = str(row.get('項目', ''))
                first_line = item.split("\n")[0]
                name = first_line.replace("禮物:", "").strip()
                target = "詳見雲端"
                m3 = re.search(r"^(.*?)\s*x\d+\s*\((?:給)?(.*?)\)(?:\s*@.*)?$", name)
                if m3:
                    name = m3.group(1).strip()
                    target = m3.group(2).strip()
                d_link = extract_link(item)
                
                records.append({
                    "名稱": name, "數量": 1, "對象": target, "商店": "", "位置": "",
                    "金額": row.get('金額',0), "幣別": "TWD", "手續費": 0, "總台幣": row.get('金額',0), "支付人": row.get('支付人',''),
                    "Drive連結": d_link, "DriveID": extract_id(d_link)
                })
            if records: st.session_state.gift_list = records

    except Exception as e:
        pass # 避免斷線或初期資料庫為空時引發崩潰

# 啟動時自動同步
if 'has_synced' not in st.session_state:
    sync_from_cloud()
    st.session_state.has_synced = True

def save_to_cloud(new_row_dict):
    try:
        new_row_df = pd.DataFrame([new_row_dict])
        existing_df = conn.read(worksheet=target_sheet, ttl=0)
        
        for col in EXPECTED_COLUMNS:
            if not existing_df.empty and col not in existing_df.columns:
                existing_df[col] = "未知"

        if existing_df.empty or len(existing_df.columns) < len(EXPECTED_COLUMNS):
            updated_df = new_row_df
        else:
            updated_df = pd.concat([existing_df, new_row_df], ignore_index=True)
            
        updated_df = updated_df[EXPECTED_COLUMNS]
        conn.update(worksheet=target_sheet, data=updated_df)
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"❌ 雲端同步失敗: {e}"); return False

# --- 職人風 CSS ---
st.markdown("""
    <style>
    .stTabs [data-baseweb="tab-list"] { gap: 15px; }
    .stTabs [data-baseweb="tab"] { height: 50px; white-space: pre-wrap; font-weight: 600; font-size: 16px; color: #888; }
    .stTabs [aria-selected="true"] { color: #b87333; border-bottom-color: #b87333; }
    .calc-box { background-color: #1e1e1e; padding: 10px; border-radius: 5px; border-left: 4px solid #b87333; margin-top: 5px; margin-bottom: 15px;}
    </style>
""", unsafe_allow_html=True)

st.title("💼 旅程全紀錄與清單管理")

tab_ins, tab_flight, tab_hotel, tab_ticket, tab_cash, tab_pack, tab_gift = st.tabs([
    "🛡️ 保險", "✈️ 交通", "🏨 飯店", "🎟️ 票卷", "💰 換匯", "🎒 行李", "🎁 伴手禮"
])

# ==========================================
# 1. 保險資訊
# ==========================================
with tab_ins:
    st.header("🛡️ 保險憑證管理")
    with st.container():
        col1, col2 = st.columns(2)
        with col1:
            ins_name = st.text_input("保險公司 / 產品名稱", placeholder="例如：安達產險", key="ins_n_in")
            ins_no = st.text_input("保單編號", placeholder="POL12345678", key="ins_no_in")
            ins_date = st.date_input("購買日期", key="ins_d")
        with col2:
            ins_amount = st.number_input("保險金額 (TWD)", min_value=0.0, key="ins_amt_in")
            ins_pay_m = st.selectbox("付款方式", ["信用卡", "現金", "電子支付"], key="ins_pm")
            ins_payer = st.text_input("支付人", value="自己", key="ins_py")
            ins_file = st.file_uploader("上傳保單憑證", type=['pdf', 'jpg', 'png'], key="ins_f")

    if st.button("✅ 儲存保險資訊並備份檔案", type="primary", use_container_width=True, key="btn_ins_save"):
        if ins_name and ins_amount >= 0:
            with st.spinner("檔案上傳中..."):
                d_file = upload_to_drive(ins_file)
                
            if 'ins_records' not in st.session_state: st.session_state.ins_records = []
            st.session_state.ins_records.append({
                "名稱": ins_name, "編號": ins_no, "日期": str(ins_date), 
                "金額": ins_amount, "付款方式": ins_pay_m, "支付人": ins_payer, 
                "Drive連結": d_file['link'] if d_file else None, "檔案名": d_file['name'] if d_file else "無"
            })
            item_desc = f"保險：{ins_name}"
            if d_file: item_desc += f"\n🔗 {d_file['link']}"
            save_to_cloud({"日期": str(ins_date), "分類": "其他", "項目": item_desc, "金額": int(ins_amount), "付款方式": ins_pay_m, "支付人": ins_payer, "來源": "清單-保險"})
            st.success("保險與檔案已同步！"); st.rerun()

    if 'ins_records' in st.session_state and st.session_state.ins_records:
        st.divider()
        st.subheader("📋 已記錄保險")
        for i, item in enumerate(st.session_state.ins_records):
            with st.expander(f"🛡️ {item['名稱']} - NT$ {item['金額']} ({item['支付人']} 支付)"):
                if item.get('Drive連結'): st.markdown(f"📎 **[📥 點擊檢視/下載憑證]({item['Drive連結']})**")
                
                if st.button("🗑️ 刪除此紀錄", key=f"ins_del_{i}"):
                    st.session_state.ins_records.pop(i); st.rerun()
                
                with st.form(key=f"ei_f_{i}"):
                    st.caption("✏️ 修改資料")
                    c_e1, c_e2 = st.columns(2)
                    e_n = c_e1.text_input("名稱", value=item.get('名稱',''))
                    e_no = c_e2.text_input("編號", value=item.get('編號',''))
                    e_a = c_e1.number_input("金額", value=float(item.get('金額',0)))
                    e_py = c_e2.text_input("支付人", value=item.get('支付人',''))
                    e_file = st.file_uploader("補傳/更新憑證", type=['pdf', 'jpg', 'png'])
                    if st.form_submit_button("💾 儲存修改"):
                        item['名稱'] = e_n; item['編號'] = e_no; item['金額'] = e_a; item['支付人'] = e_py
                        if e_file:
                            d = upload_to_drive(e_file)
                            if d: item['Drive連結'] = d['link']; item['檔案名'] = d['name']
                        st.rerun()

# ==========================================
# 2. 交通銜接
# ==========================================
with tab_flight:
    st.header("✈️ 航班與交通銜接")
    c1, c2, c3 = st.columns([1, 1.5, 1.5])
    t_type = c1.selectbox("種類", ["飛機", "高鐵", "火車", "客運", "其他"], key="t_type_in")
    t_start = c2.text_input("起點", key="t_st_in")
    t_end = c3.text_input("訖點", key="t_end_in")
    
    c_comp, c_plat, c_ord, c_rt = st.columns([1.5, 1.5, 1.5, 1])
    t_company = c_comp.text_input("營運公司名稱", key="t_comp_in")
    t_plat_sel = c_plat.selectbox("交通訂購平台", PLATFORMS, key="t_plat_sel")
    t_plat = st.text_input("輸入自訂平台", key="t_plat_cust") if t_plat_sel == "其他(可自行輸入)" else t_plat_sel
    t_order_no = c_ord.text_input("交通訂單編號", key="t_ord_in")
    with c_rt:
        st.write(""); st.write("")
        t_is_roundtrip = st.checkbox("🔄 來回票", key="t_rt")
        
    c_f1, c_f2 = st.columns(2)
    t_flight_out = c_f1.text_input("去程 航班/車次", key="t_fout_in")
    t_flight_in = c_f2.text_input("回程 航班/車次", key="t_fin_in") if t_is_roundtrip else ""
    
    st.caption("🛫 去程時間")
    c_dep1, c_dep2, c_arr1, c_arr2 = st.columns(4)
    t_dep_d = c_dep1.date_input("去程 出發日期", key="t_dep_d")
    t_dep_t = c_dep2.text_input("去程 出發時間", placeholder="08:30", key="t_dep_t")
    t_arr_d = c_arr1.date_input("去程 抵達日期", key="t_arr_d")
    t_arr_t = c_arr2.text_input("去程 抵達時間", placeholder="12:00", key="t_arr_t")
    
    if t_is_roundtrip:
        st.caption("🛬 回程時間")
        cr_dep1, cr_dep2, cr_arr1, cr_arr2 = st.columns(4)
        t_rdep_d = cr_dep1.date_input("回程 出發日期", key="t_rdep_d")
        t_rdep_t = cr_dep2.text_input("回程 出發時間", placeholder="15:00", key="t_rdep_t")
        t_rarr_d = cr_arr1.date_input("回程 抵達日期", key="t_rarr_d")
        t_rarr_t = cr_arr2.text_input("回程 抵達時間", placeholder="18:30", key="t_rarr_t")
    else:
        t_rdep_d, t_rdep_t, t_rarr_d, t_rarr_t = None, "", None, ""

    st.write("---")
    c_amt1, c_amt2, c_amt3 = st.columns(3)
    t_amt = c_amt1.number_input("交通外幣/原幣金額", min_value=0.0, key="t_amt_in")
    t_curr_sel = c_amt2.selectbox("交通幣別", CURR_OPTIONS, key="t_c_sel")
    t_curr = c_amt3.text_input("交通自訂幣別", key="t_c_in") if t_curr_sel == "自行輸入" else t_curr_sel
    
    c_pay1, c_pay2, c_pay3 = st.columns(3)
    t_pay_m = c_pay1.selectbox("交通付款方式", ["信用卡", "現金", "電子支付"], key="t_pm")
    t_buy_date = c_pay2.date_input("購買日期", key="t_bd")
    t_payer = c_pay3.text_input("支付人", value="自己", key="t_py")

    t_foreign_fee = 0.0
    if t_curr != "TWD" and t_pay_m == "信用卡":
        t_foreign_fee = st.number_input("交通國外交易處理費 (TWD)", min_value=0.0, value=0.0, step=10.0, key="t_ff_in")
        
    rate = get_rate(t_curr)
    t_twd_total = int(t_amt * rate) + int(t_foreign_fee)
    st.markdown(f"<div class='calc-box'>💡 <b>自動計算總計 (TWD):</b> NT$ {t_twd_total:,} </div>", unsafe_allow_html=True)
    t_file = st.file_uploader("上傳票卷(機票/車票)", type=['pdf', 'jpg', 'png'], key="t_f")

    if st.button("➕ 加入交通清單並備份檔案", type="primary", use_container_width=True, key="btn_t_save"):
        if t_start and t_amt >= 0:
            with st.spinner("檔案上傳中..."): d_file = upload_to_drive(t_file)
            if 'trans_records' not in st.session_state: st.session_state.trans_records = []
            st.session_state.trans_records.append({
                "種類": t_type, "公司": t_company, "平台": t_plat, "訂單號": t_order_no, "來回": t_is_roundtrip, 
                "起點": t_start, "訖點": t_end, "去程班次": t_flight_out, "回程班次": t_flight_in,
                "去出發": f"{t_dep_d} {t_dep_t}", "去抵達": f"{t_arr_d} {t_arr_t}",
                "回出發": f"{t_rdep_d} {t_rdep_t}" if t_is_roundtrip else "", 
                "金額": t_amt, "幣別": t_curr, "手續費": t_foreign_fee, "總台幣": t_twd_total,
                "付款方式": t_pay_m, "支付人": t_payer,
                "Drive連結": d_file['link'] if d_file else None, "檔案名": d_file['name'] if d_file else "無"
            })
            
            trip_tag = "(來回)" if t_is_roundtrip else "(單程)"
            item_desc = f"{t_type}: [{t_company}] {t_start}➔{t_end} {trip_tag}\n📝平台: {t_plat} | 訂單: {t_order_no}"
            if d_file: item_desc += f"\n🔗 {d_file['link']}"
            
            save_to_cloud({"日期": str(t_buy_date), "分類": "交通", "項目": item_desc, "金額": t_twd_total, "付款方式": t_pay_m, "支付人": t_payer, "來源": "清單-交通"})
            st.success("✅ 交通支出已同步！"); st.rerun()

    if 'trans_records' in st.session_state and st.session_state.trans_records:
        st.divider()
        st.subheader("📋 已記錄交通")
        for i, item in enumerate(st.session_state.trans_records):
            rt_display = "🔄 來回" if item.get('來回') else "➡️ 單程"
            exp_title = f"✈️ {item.get('起點','')}➔{item.get('訖點','')} - NT$ {item.get('總台幣', 0)}"
            with st.expander(exp_title):
                if item.get('Drive連結'): st.markdown(f"📎 **[📥 點擊檢視車票憑證]({item['Drive連結']})**")
                plat_display = f" | 平台: {item.get('平台')}" if item.get('平台') else ""
                st.write(f"訂單號: {item.get('訂單號','')}{plat_display} | 支付人: {item.get('支付人')}")
                
                if st.button("🗑️ 刪除此紀錄", key=f"et_del_{i}"):
                    st.session_state.trans_records.pop(i); st.rerun()
                
                with st.form(key=f"et_f_{i}"):
                    st.caption("✏️ 修改資料")
                    e_c1, e_c2, e_c3 = st.columns(3)
                    e_type = e_c1.text_input("種類", value=item.get('種類',''))
                    e_comp = e_c2.text_input("公司", value=item.get('公司',''))
                    e_plat = e_c3.text_input("訂購平台", value=item.get('平台',''))
                    
                    e_f1, e_f2, e_f3 = st.columns(3)
                    e_ord = e_f1.text_input("訂單編號", value=item.get('訂單號',''))
                    e_out_f = e_f2.text_input("去程班次", value=item.get('去程班次',''))
                    e_in_f = e_f3.text_input("回程班次", value=item.get('回程班次',''))
                    
                    e_amt1, e_amt2, e_amt3 = st.columns(3)
                    e_amt = e_amt1.number_input("原幣金額", value=float(item.get('金額', 0.0)))
                    e_curr = e_amt2.text_input("幣別", value=item.get('幣別','TWD'))
                    e_fee = e_amt3.number_input("國外處理費", value=float(item.get('手續費', 0.0)))
                    
                    e_file = st.file_uploader("補傳/更新憑證", type=['pdf', 'jpg', 'png'])
                    if st.form_submit_button("💾 儲存修改 (將重算台幣)"):
                        item.update({'種類': e_type, '公司': e_comp, '平台': e_plat, '訂單號': e_ord, '去程班次': e_out_f, '回程班次': e_in_f, '金額': e_amt, '幣別': e_curr, '手續費': e_fee})
                        item['總台幣'] = int(e_amt * get_rate(e_curr)) + int(e_fee)
                        if e_file:
                            d = upload_to_drive(e_file)
                            if d: item['Drive連結'] = d['link']; item['檔案名'] = d['name']
                        st.rerun()

# ==========================================
# 3. 飯店住宿 
# ==========================================
with tab_hotel:
    st.header("🏨 飯店住宿預約")
    c_hn, c_plat, c_ho = st.columns([1.5, 1.5, 1.5])
    h_name = c_hn.text_input("飯店名稱", key="h_name_in")
    h_plat_sel = c_plat.selectbox("住宿訂購平台", PLATFORMS, key="h_plat_sel")
    h_plat = st.text_input("輸入自訂平台", key="h_plat_in") if h_plat_sel == "其他(可自行輸入)" else h_plat_sel
    h_order_no = c_ho.text_input("住宿訂單編號", key="h_ord")
    
    c1, c2, c3 = st.columns(3)
    h_in = c1.date_input("入住日期", key="h_in_d")
    h_out = c2.date_input("退房日期", key="h_out_d")
    nights = (h_out - h_in).days
    
    if nights < 0: c3.error("退房日期錯誤！")
    else: c3.metric("住宿天數", f"{nights} 晚")
    
    st.write("---")
    c4, c5, c6 = st.columns(3)
    h_amt = c4.number_input("外幣/原幣住宿金額", min_value=0.0, key="h_amt_in")
    h_curr_sel = c5.selectbox("住宿幣別", CURR_OPTIONS, key="h_cur_sel")
    h_curr = c6.text_input("輸入幣別", key="h_cur_in2") if h_curr_sel == "自行輸入" else h_curr_sel
    
    c7, c8 = st.columns(2)
    h_pay_m = c7.selectbox("住宿付款方式", ["信用卡", "現金", "現場支付", "電子支付"], key="h_pm")
    h_payer = c8.text_input("支付人", value="自己", key="h_py")
    
    h_foreign_fee = 0.0
    if h_curr != "TWD" and h_pay_m == "信用卡":
        h_foreign_fee = st.number_input("住宿國外交易處理費 (TWD)", min_value=0.0, value=0.0, step=10.0, key="h_ff")
        
    rate = get_rate(h_curr)
    h_twd_total = int(h_amt * rate) + int(h_foreign_fee)
    st.markdown(f"<div class='calc-box'>💡 <b>自動計算總計 (TWD):</b> NT$ {h_twd_total:,} </div>", unsafe_allow_html=True)
    h_file = st.file_uploader("上傳訂房紀錄", type=['pdf', 'jpg', 'png'], key="h_f")

    if st.button("➕ 記錄住宿並備份檔案", type="primary", use_container_width=True, key="btn_h_save"):
        if h_name and h_amt >= 0 and nights >= 0:
            with st.spinner("檔案上傳中..."): d_file = upload_to_drive(h_file)
            if 'hotel_records' not in st.session_state: st.session_state.hotel_records = []
            st.session_state.hotel_records.append({
                "飯店": h_name, "平台": h_plat, "訂單號": h_order_no, "入住": str(h_in), "晚數": nights, 
                "金額": h_amt, "幣別": h_curr, "手續費": h_foreign_fee, "總台幣": h_twd_total, "支付人": h_payer, 
                "Drive連結": d_file['link'] if d_file else None, "檔案名": d_file['name'] if d_file else "無"
            })
            item_desc = f"飯店：{h_name}\n📝平台: {h_plat} | 訂單: {h_order_no}"
            if d_file: item_desc += f"\n🔗 {d_file['link']}"
            save_to_cloud({"日期": str(h_in), "分類": "住宿", "項目": item_desc, "金額": h_twd_total, "付款方式": h_pay_m, "支付人": h_payer, "來源": "清單-住宿"})
            st.success("✅ 住宿費用已同步！"); st.rerun()

    if 'hotel_records' in st.session_state and st.session_state.hotel_records:
        st.divider()
        st.subheader("📋 已記錄住宿")
        for i, item in enumerate(st.session_state.hotel_records):
            with st.expander(f"🏨 {item.get('飯店')} - NT$ {item.get('總台幣',0)}"):
                if item.get('Drive連結'): st.markdown(f"📎 **[📥 點擊檢視訂房憑證]({item['Drive連結']})**")
                plat_display = f" | 平台: {item.get('平台')}" if item.get('平台') else ""
                st.write(f"入住：{item.get('入住')} | 訂單號: {item.get('訂單號','')}{plat_display} | 支付人：{item.get('支付人')}")
                
                if st.button("🗑️ 刪除此紀錄", key=f"eh_del_{i}"): st.session_state.hotel_records.pop(i); st.rerun()
                
                with st.form(key=f"eh_f_{i}"):
                    st.caption("✏️ 修改資料")
                    e_n = st.text_input("飯店", value=item.get('飯店',''))
                    e_p = st.text_input("訂購平台", value=item.get('平台',''))
                    e_o = st.text_input("訂單編號", value=item.get('訂單號',''))
                    
                    e_a1, e_a2, e_a3 = st.columns(3)
                    e_amt = e_a1.number_input("金額", value=float(item.get('金額',0.0)))
                    e_curr = e_a2.text_input("幣別", value=item.get('幣別','TWD'))
                    e_fee = e_a3.number_input("國外處理費", value=float(item.get('手續費', 0.0)))
                    e_pyr = st.text_input("支付人", value=item.get('支付人','自己'))
                    e_file = st.file_uploader("補傳/更新憑證", type=['pdf', 'jpg', 'png'])
                    if st.form_submit_button("💾 儲存修改"):
                        item.update({'飯店': e_n, '平台': e_p, '訂單號': e_o, '金額': e_amt, '幣別': e_curr, '手續費': e_fee, '支付人': e_pyr})
                        item['總台幣'] = int(e_amt * get_rate(e_curr)) + int(e_fee)
                        if e_file:
                            d = upload_to_drive(e_file)
                            if d: item['Drive連結'] = d['link']; item['檔案名'] = d['name']
                        st.rerun()

# ==========================================
# 4. 票卷 
# ==========================================
with tab_ticket:
    st.header("🎟️ 票卷管理")
    c1, c2, c_plat, c_ord = st.columns([1, 1.5, 1.5, 1.5])
    tk_type = c1.selectbox("票卷種類", ["門票", "餐卷", "交通", "遊樂票卷", "住宿卷"], key="tk_type_in")
    tk_name = c2.text_input("項目名稱", key="tk_name_in")
    tk_plat_sel = c_plat.selectbox("票卷訂購平台", PLATFORMS, key="tk_plat_sel")
    tk_plat = st.text_input("輸入自訂平台", key="tk_plat_in") if tk_plat_sel == "其他(可自行輸入)" else tk_plat_sel
    tk_order_no = c_ord.text_input("票卷訂單編號", key="tk_ord")
    
    c3, c4 = st.columns(2)
    tk_buy_date = c3.date_input("購買日期", key="tk_bd")
    tk_use_date = c4.date_input("預計使用日期", key="tk_ud")
    
    st.write("---")
    c5, c6, c7 = st.columns(3)
    tk_amt = c5.number_input("外幣/原幣金額", min_value=0.0, key="tk_amt_in")
    tk_curr_sel = c6.selectbox("票卷幣別", CURR_OPTIONS, key="tk_c_sel")
    tk_curr = c7.text_input("輸入幣別", key="tk_c_in2") if tk_curr_sel == "自行輸入" else tk_curr_sel
    
    c8, c9 = st.columns(2)
    tk_pay_m = c8.selectbox("票卷付款方式", ["信用卡", "現金", "電子支付"], key="tk_pm")
    tk_payer = c9.text_input("支付人", value="自己", key="tk_py")
    
    tk_foreign_fee = 0.0
    if tk_curr != "TWD" and tk_pay_m == "信用卡":
        tk_foreign_fee = st.number_input("票卷國外交易處理費 (TWD)", min_value=0.0, value=0.0, step=10.0, key="tk_ff")
        
    rate = get_rate(tk_curr)
    tk_twd_total = int(tk_amt * rate) + int(tk_foreign_fee)
    st.markdown(f"<div class='calc-box'>💡 <b>自動計算總計 (TWD):</b> NT$ {tk_twd_total:,} </div>", unsafe_allow_html=True)
    tk_file = st.file_uploader("上傳票卷(PDF/圖片)", type=['pdf', 'jpg', 'png'], key="tk_f")

    if st.button("➕ 加入票卷並備份檔案", type="primary", use_container_width=True, key="btn_tk_save"):
        if tk_name and tk_amt >= 0:
            with st.spinner("檔案上傳中..."): d_file = upload_to_drive(tk_file)
            if 'ticket_records' not in st.session_state: st.session_state.ticket_records = []
            st.session_state.ticket_records.append({
                "種類": tk_type, "名稱": tk_name, "平台": tk_plat, "訂單號": tk_order_no, "金額": tk_amt, "幣別": tk_curr,
                "手續費": tk_foreign_fee, "總台幣": tk_twd_total, "使用日": str(tk_use_date), "支付人": tk_payer, 
                "Drive連結": d_file['link'] if d_file else None, "檔案名": d_file['name'] if d_file else "無"
            })
            item_desc = f"{tk_type}：{tk_name}\n📝平台: {tk_plat} | 訂單: {tk_order_no}"
            if d_file: item_desc += f"\n🔗 {d_file['link']}"
            save_to_cloud({"日期": str(tk_buy_date), "分類": "門票/娛樂", "項目": item_desc, "金額": tk_twd_total, "付款方式": tk_pay_m, "支付人": tk_payer, "來源": "清單-票卷"})
            st.success("✅ 票卷支出已同步！"); st.rerun()

    if 'ticket_records' in st.session_state and st.session_state.ticket_records:
        st.divider()
        st.subheader("📋 已記錄票卷")
        for i, item in enumerate(st.session_state.ticket_records):
            with st.expander(f"🎟️ [{item.get('種類', '票卷')}] {item.get('名稱')} - NT$ {item.get('總台幣',0)}"):
                if item.get('Drive連結'): st.markdown(f"📎 **[📥 點擊檢視票卷檔案]({item['Drive連結']})**")
                plat_display = f" | 平台: {item.get('平台')}" if item.get('平台') else ""
                st.write(f"使用日：{item.get('使用日')} | 訂單號: {item.get('訂單號','')}{plat_display} | 支付人：{item.get('支付人')}")
                if st.button("🗑️ 刪除此紀錄", key=f"etk_del_{i}"): st.session_state.ticket_records.pop(i); st.rerun()
                
                with st.form(key=f"etk_f_{i}"):
                    st.caption("✏️ 修改資料")
                    e_n = st.text_input("名稱", value=item.get('名稱',''))
                    e_p = st.text_input("訂購平台", value=item.get('平台',''))
                    e_o = st.text_input("訂單編號", value=item.get('訂單號',''))
                    
                    e_a1, e_a2, e_a3 = st.columns(3)
                    e_amt = e_a1.number_input("金額", value=float(item.get('金額',0.0)))
                    e_curr = e_a2.text_input("幣別", value=item.get('幣別','TWD'))
                    e_fee = e_a3.number_input("國外處理費", value=float(item.get('手續費', 0.0)))
                    e_pyr = st.text_input("支付人", value=item.get('支付人','自己'))
                    e_file = st.file_uploader("補傳/更新憑證", type=['pdf', 'jpg', 'png'])
                    if st.form_submit_button("💾 儲存修改"):
                        item.update({'名稱': e_n, '平台': e_p, '訂單號': e_o, '金額': e_amt, '幣別': e_curr, '手續費': e_fee, '支付人': e_pyr})
                        item['總台幣'] = int(e_amt * get_rate(e_curr)) + int(e_fee)
                        if e_file:
                            d = upload_to_drive(e_file)
                            if d: item['Drive連結'] = d['link']; item['檔案名'] = d['name']
                        st.rerun()

# ==========================================
# 5. 換匯紀錄 
# ==========================================
with tab_cash:
    st.header("💰 分批換匯與現金紀錄")
    with st.container():
        col1, col2, col3 = st.columns([1, 1, 2])
        with col1:
            ex_curr_sel = st.selectbox("換匯幣別", CURR_OPTIONS, key="cash_curr_base")
            final_currency = st.text_input("自訂幣別", key="cash_curr_in") if ex_curr_sel == "自行輸入" else ex_curr_sel
        with col2: ex_date = st.date_input("換匯日期", key="ex_date")
        with col3: ex_loc = st.text_input("地點", placeholder="例如：台灣銀行、成田機場 ATM", key="ex_loc_in")

        col4, col5, col6 = st.columns(3)
        with col4: ex_amount = st.number_input("換匯金額 (外幣)", min_value=0.0, step=100.0, key="ex_amt_in")
        with col5: ex_rate = st.number_input("匯率", min_value=0.0, format="%.4f", step=0.0001, key="ex_rate_in", value=0.215)
        with col6:
            twd_cost = ex_amount * ex_rate
            st.metric("換匯成本 (TWD)", f"{int(twd_cost):,}")
            
        ex_file = st.file_uploader("上傳水單/收據 (選填)", type=['pdf', 'jpg', 'png'], key="ex_f")

    if st.button("➕ 記錄換匯並上傳", use_container_width=True, key="btn_ex_save"):
        if ex_amount > 0 and ex_rate > 0:
            with st.spinner("檔案上傳中..."): d_file = upload_to_drive(ex_file)
            if 'exchange_records' not in st.session_state: st.session_state.exchange_records = []
            
            if final_currency == "JPY":
                st.session_state['jpy_rate'] = ex_rate
                st.toast(f"系統日幣匯率已自動更新為: {st.session_state['jpy_rate']:.4f}")

            st.session_state.exchange_records.append({
                "日期": str(ex_date), "地點": ex_loc, "幣別": final_currency, 
                "金額": ex_amount, "匯率": ex_rate, "台幣成本": int(twd_cost),
                "Drive連結": d_file['link'] if d_file else None
            })
            st.success("換匯紀錄已儲存！"); st.rerun()

    if 'exchange_records' in st.session_state and st.session_state.exchange_records:
        st.divider()
        st.subheader("📋 換匯明細")
        for i, item in enumerate(st.session_state.exchange_records):
            with st.expander(f"💱 {item.get('日期', '')} | {item.get('地點','')} - {item.get('金額')} {item.get('幣別')} (匯率: {item.get('匯率')})"):
                if item.get('Drive連結'): st.markdown(f"📎 **[📥 檢視水單/收據]({item['Drive連結']})**")
                
                if st.button("🗑️ 刪除紀錄", key=f"ex_del_{i}"): st.session_state.exchange_records.pop(i); st.rerun()
                
                with st.form(key=f"eex_f_{i}"):
                    st.caption("✏️ 修改資料")
                    e_loc = st.text_input("地點", value=item.get('地點',''))
                    e_a1, e_a2, e_a3 = st.columns(3)
                    e_amt = e_a1.number_input("外幣金額", value=float(item.get('金額',0.0)))
                    e_curr = e_a2.text_input("幣別", value=item.get('幣別',''))
                    e_rate = e_a3.number_input("匯率", value=float(item.get('匯率',0.0)), format="%.4f")
                    e_file = st.file_uploader("補傳/更新水單", type=['pdf', 'jpg', 'png'])
                    if st.form_submit_button("💾 儲存修改"):
                        item.update({'地點': e_loc, '金額': e_amt, '幣別': e_curr, '匯率': e_rate})
                        item['台幣成本'] = int(e_amt * e_rate)
                        if e_file:
                            d = upload_to_drive(e_file)
                            if d: item['Drive連結'] = d['link']
                        st.rerun()

# ==========================================
# 6. 行李裝備 (🟢 加入三欄式縮圖預覽)
# ==========================================
with tab_pack:
    st.header("🎒 裝備清單")
    with st.expander("➕ 新增裝備 (若新購可同步記帳)", expanded=False):
        c_n, c_q = st.columns([3, 1])
        g_name = c_n.text_input("裝備名稱", key="pk_name_in")
        g_qty = c_q.number_input("數量", min_value=1, value=1, key="g_q")
        
        c_store1, c_store2 = st.columns(2)
        p_store = c_store1.text_input("購買商店", placeholder="例如：百岳登山用品", key="pk_st_in")
        p_loc = c_store2.text_input("商店位置", placeholder="例如：台北市", key="pk_lc_in")
        
        is_new = st.checkbox("這是為此行新買的 (同步至雲端記帳)", key="pk_new_chk")
        
        c1, c2, c3 = st.columns(3)
        g_amt = c1.number_input("外幣/原幣總金額", min_value=0.0, disabled=not is_new, key="pk_amt_in")
        g_curr_sel = c2.selectbox("購買幣別", CURR_OPTIONS, key="p_c_sel", disabled=not is_new)
        g_curr = c3.text_input("輸入幣別", key="p_c_in") if g_curr_sel == "自行輸入" else g_curr_sel
        
        c4, c5 = st.columns(2)
        g_pay_m = c4.selectbox("付款方式", ["現金", "信用卡", "電子支付"], disabled=not is_new, key="p_pm")
        g_payer = c5.text_input("支付人", value="自己", disabled=not is_new, key="p_py")
        
        g_foreign_fee = 0.0
        if g_curr != "TWD" and g_pay_m == "信用卡" and is_new:
            g_foreign_fee = st.number_input("裝備國外交易處理費 (TWD)", min_value=0.0, value=0.0, step=10.0, key="p_ff_in")
            
        rate = get_rate(g_curr)
        g_twd_total = int(g_amt * rate) + int(g_foreign_fee) if is_new else 0
        if is_new:
            st.markdown(f"<div class='calc-box'>💡 <b>自動計算總計 (TWD):</b> NT$ {g_twd_total:,} </div>", unsafe_allow_html=True)
            
        g_file = st.file_uploader("上傳裝備照片/購買憑證", type=['jpg', 'png', 'jpeg', 'pdf'], key="g_f")
        
        if st.button("📥 加入清單並上傳檔案", type="primary", use_container_width=True, key="btn_pk_save"):
            with st.spinner("檔案上傳 Drive 中..."): d_file = upload_to_drive(g_file)
            if 'packing_list' not in st.session_state: st.session_state.packing_list = []
            
            st.session_state.packing_list.append({
                "名稱": g_name, "數量": g_qty, "商店": p_store, "位置": p_loc, "狀態": False, "新購": is_new, 
                "金額": g_amt if is_new else 0, "幣別": g_curr if is_new else "", "手續費": g_foreign_fee, "總台幣": g_twd_total,
                "支付人": g_payer if is_new else "無", 
                "DriveID": d_file['id'] if d_file else None, "Drive連結": d_file['link'] if d_file else None
            })
            
            if is_new and g_amt > 0:
                store_tag = f" @{p_store}" if p_store else ""
                item_desc = f"裝備:{g_name}({g_qty}個){store_tag}"
                if d_file: item_desc += f"\n🔗 {d_file['link']}"
                save_to_cloud({"日期": str(pd.Timestamp.now().date()), "分類": "購物", "項目": item_desc, "金額": g_twd_total, "付款方式": g_pay_m, "支付人": g_payer, "來源": "清單-裝備"})
            st.toast(f"已加入：{g_name}"); st.rerun()

    if 'packing_list' in st.session_state and st.session_state.packing_list:
        st.divider()
        st.subheader("📋 裝備明細 (打勾確認進度)")
        
        checked_count = sum(1 for item in st.session_state.packing_list if item.get('狀態', False))
        st.progress(checked_count / len(st.session_state.packing_list) if len(st.session_state.packing_list) > 0 else 0)
        
        for i, item in enumerate(st.session_state.packing_list):
            c_chk, c_img, c_exp = st.columns([0.05, 0.15, 0.8])
            
            with c_chk:
                checked = st.checkbox("", value=item.get('狀態', False), key=f"pk_chk_{i}")
                if checked != item.get('狀態', False):
                    st.session_state.packing_list[i]['狀態'] = checked; st.rerun()
            
            with c_img:
                if item.get('DriveID') and not (".pdf" in str(item.get('Drive連結', '')).lower()):
                    st.image(f"https://drive.google.com/thumbnail?id={item['DriveID']}&sz=200", use_container_width=True)

            with c_exp:
                new_tag = f" 🆕 (NT$ {item.get('總台幣',0)})" if item.get('新購', False) else ""
                with st.expander(f"🎒 {item.get('名稱')} x {item.get('數量', 1)}{new_tag}"):
                    if item.get('DriveID'):
                        if ".pdf" in item.get('Drive連結', '').lower():
                            st.markdown(f"📎 **[📥 檢視 PDF 憑證]({item['Drive連結']})**")
                        else:
                            st.image(f"https://drive.google.com/thumbnail?id={item['DriveID']}&sz=w800", width=200)
                            st.markdown(f"**[📥 下載大圖]({item['Drive連結']})**")
                    
                    store_disp = f" | 商店: {item.get('商店')}" if item.get('商店') else ""
                    loc_disp = f" | 位置: {item.get('位置')}" if item.get('位置') else ""
                    st.write(f"支付人：{item.get('支付人', '未知')}{store_disp}{loc_disp}")
                    
                    if st.button("🗑️ 刪除此紀錄", key=f"epk_del_{i}"): st.session_state.packing_list.pop(i); st.rerun()
                    
                    with st.form(key=f"epk_f_{i}"):
                        st.caption("✏️ 修改資料")
                        e_n = st.text_input("名稱", value=item.get('名稱',''))
                        e_q = st.number_input("數量", value=item.get('數量',1), min_value=1)
                        
                        e_s1, e_s2 = st.columns(2)
                        e_store = e_s1.text_input("購買商店", value=item.get('商店',''))
                        e_loc = e_s2.text_input("商店位置", value=item.get('位置',''))
                        
                        e_a1, e_a2, e_a3 = st.columns(3)
                        e_amt = e_a1.number_input("原幣金額", value=float(item.get('金額',0)))
                        e_curr = e_a2.text_input("幣別", value=item.get('幣別','TWD'))
                        e_fee = e_a3.number_input("國外處理費", value=float(item.get('手續費',0.0)))
                        
                        e_payer = st.text_input("支付人", value=item.get('支付人','自己'))
                        e_file = st.file_uploader("補傳/更新檔案", type=['jpg', 'png', 'jpeg', 'pdf'])
                        
                        if st.form_submit_button("💾 儲存修改"):
                            item.update({'名稱': e_n, '數量': e_q, '商店': e_store, '位置': e_loc, '金額': e_amt, '幣別': e_curr, '手續費': e_fee, '支付人': e_payer})
                            if item.get('新購'): item['總台幣'] = int(e_amt * get_rate(e_curr)) + int(e_fee)
                            if e_file:
                                d = upload_to_drive(e_file)
                                if d: item['Drive連結'] = d['link']; item['DriveID'] = d['id']
                            st.rerun()

# ==========================================
# 7. 伴手禮清單 (🟢 加入預覽圖)
# ==========================================
with tab_gift:
    st.header("🎁 伴手禮採購")
    with st.container():
        c_n, c_q, c_t = st.columns([2, 1, 1.5])
        gift_n = c_n.text_input("品項名稱", key="gf_n_in")
        gift_qty = c_q.number_input("數量", min_value=1, value=1, key="gf_q")
        gift_target = c_t.text_input("送給誰", key="gf_t_in")
        
        c_store1, c_store2 = st.columns(2)
        gf_store = c_store1.text_input("購買商店", placeholder="例如：大國藥妝", key="gf_st")
        gf_loc = c_store2.text_input("商店位置", placeholder="例如：心齋橋", key="gf_lc")
        
        st.write("---")
        c1, c2, c3 = st.columns(3)
        gift_amt = c1.number_input("外幣/原幣總金額", min_value=0.0, key="gf_amt_in")
        gift_curr_sel = c2.selectbox("伴手禮幣別", CURR_OPTIONS, key="gf_c_sel")
        gift_curr = c3.text_input("輸入幣別", key="gf_c_in2") if gift_curr_sel == "自行輸入" else gift_curr_sel
        
        c4, c5 = st.columns(2)
        gift_pay_m = c4.selectbox("伴手禮付款方式", ["信用卡", "現金", "電子支付"], key="gf_pm")
        gift_payer = c5.text_input("支付人", value="自己", key="gf_py")
        
        gift_foreign_fee = 0.0
        if gift_curr != "TWD" and gift_pay_m == "信用卡":
            gift_foreign_fee = st.number_input("伴手禮國外交易處理費 (TWD)", min_value=0.0, value=0.0, step=10.0, key="gf_ff_in")
            
        rate = get_rate(gift_curr)
        gift_twd_total = int(gift_amt * rate) + int(gift_foreign_fee)
        st.markdown(f"<div class='calc-box'>💡 <b>自動計算總計 (TWD):</b> NT$ {gift_twd_total:,} </div>", unsafe_allow_html=True)
        
        gift_file = st.file_uploader("上傳禮物照片/收據", type=['jpg', 'png', 'jpeg', 'pdf'], key="gf_f")

        if st.button("➕ 加入伴手禮並同步至總帳", type="primary", use_container_width=True, key="btn_gf_save"):
            if gift_n:
                with st.spinner("檔案上傳 Drive 中..."): d_file = upload_to_drive(gift_file)
                if 'gift_list' not in st.session_state: st.session_state.gift_list = []
                
                st.session_state.gift_list.append({
                    "名稱": gift_n, "數量": gift_qty, "對象": gift_target, "商店": gf_store, "位置": gf_loc, 
                    "金額": gift_amt, "幣別": gift_curr, "手續費": gift_foreign_fee, "總台幣": gift_twd_total, "支付人": gift_payer, 
                    "DriveID": d_file['id'] if d_file else None, "Drive連結": d_file['link'] if d_file else None
                })
                
                store_tag = f" @{gf_store}" if gf_store else ""
                item_desc = f"禮物:{gift_n} x{gift_qty} (給{gift_target}){store_tag}"
                if d_file: item_desc += f"\n🔗 {d_file['link']}"
                
                save_to_cloud({"日期": str(pd.Timestamp.now().date()), "分類": "購物", "項目": item_desc, "金額": gift_twd_total, "付款方式": gift_pay_m, "支付人": gift_payer, "來源": "清單-伴手禮"})
                st.success(f"✅ {gift_n} 已入帳！"); st.rerun()

    if 'gift_list' in st.session_state and st.session_state.gift_list:
        st.divider()
        st.subheader("📋 已記錄伴手禮")
        for i, item in enumerate(st.session_state.gift_list):
            
            c_img, c_exp = st.columns([0.15, 0.85])
            with c_img:
                if item.get('DriveID') and not (".pdf" in str(item.get('Drive連結', '')).lower()):
                    st.image(f"https://drive.google.com/thumbnail?id={item['DriveID']}&sz=200", use_container_width=True)

            with c_exp:
                with st.expander(f"🎁 {item.get('名稱')} x {item.get('數量', 1)} (給 {item.get('對象')}) - NT$ {item.get('總台幣',0)}"):
                    if item.get('DriveID'):
                        if ".pdf" in item.get('Drive連結', '').lower():
                            st.markdown(f"📎 **[📥 檢視 PDF 收據]({item['Drive連結']})**")
                        else:
                            st.image(f"https://drive.google.com/thumbnail?id={item['DriveID']}&sz=w800", width=200)
                            st.markdown(f"**[📥 下載照片]({item['Drive連結']})**")
                    
                    store_disp = f" | 商店: {item.get('商店')}" if item.get('商店') else ""
                    loc_disp = f" | 位置: {item.get('位置')}" if item.get('位置') else ""
                    st.write(f"支付人：{item.get('支付人', '未知')}{store_disp}{loc_disp}")    
                    
                    if st.button("🗑️ 刪除此紀錄", key=f"egf_del_{i}"): st.session_state.gift_list.pop(i); st.rerun()
                    
                    with st.form(key=f"egf_f_{i}"):
                        st.caption("✏️ 修改資料")
                        e_n = st.text_input("名稱", value=item.get('名稱',''))
                        e_q = st.number_input("數量", value=item.get('數量',1), min_value=1)
                        e_t = st.text_input("對象", value=item.get('對象',''))
                        
                        e_s1, e_s2 = st.columns(2)
                        e_store = e_s1.text_input("購買商店", value=item.get('商店',''))
                        e_loc = e_s2.text_input("商店位置", value=item.get('位置',''))
                        
                        e_a1, e_a2, e_a3 = st.columns(3)
                        e_amt = e_a1.number_input("原幣金額", value=float(item.get('金額',0.0)))
                        e_curr = e_a2.text_input("幣別", value=item.get('幣別','TWD'))
                        e_fee = e_a3.number_input("國外處理費", value=float(item.get('手續費', 0.0)))
                        e_payer = st.text_input("支付人", value=item.get('支付人','自己'))
                        
                        e_file = st.file_uploader("補傳/更新檔案", type=['jpg', 'png', 'jpeg', 'pdf'])
                        if st.form_submit_button("💾 儲存修改"):
                            item.update({'名稱': e_n, '數量': e_q, '對象': e_t, '商店': e_store, '位置': e_loc, '金額': e_amt, '幣別': e_curr, '手續費': e_fee, '支付人': e_payer})
                            item['總台幣'] = int(e_amt * get_rate(e_curr)) + int(e_fee)
                            if e_file:
                                d = upload_to_drive(e_file)
                                if d: item['Drive連結'] = d['link']; item['DriveID'] = d['id']
                            st.rerun()
