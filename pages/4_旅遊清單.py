import streamlit as st
import pandas as pd
from PIL import Image
import io
from streamlit_gsheets import GSheetsConnection

st.set_page_config(page_title="旅遊清單與準備", page_icon="📝", layout="wide")

# --- 0. 旅程動態對接邏輯 ---
target_sheet = st.session_state.get('active_trip_sheet', 'Exp_Yunnan2026')
target_name = st.session_state.get('active_trip_name', '2026 雲南探索 (預設)')

with st.sidebar:
    st.header("🎯 存檔目標")
    st.success(f"目前連線旅程：\n\n**{target_name}**")
    st.caption(f"雲端寫入分頁：`{target_sheet}`")
    st.divider()

# --- 1. 建立雲端連線與寫入邏輯 ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error(f"❌ 連線初始化失敗: {e}")
    st.stop()

EXPECTED_COLUMNS = ["日期", "分類", "項目", "金額", "付款方式", "支付人", "來源"]
CURR_OPTIONS = ["TWD", "USD", "EUR", "JPY", "CNY", "自行輸入"]

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
        st.error(f"❌ 雲端同步失敗 ({target_sheet}): {e}")
        return False

# --- 職人風 CSS ---
st.markdown("""
    <style>
    .stTabs [data-baseweb="tab-list"] { gap: 15px; }
    .stTabs [data-baseweb="tab"] {
        height: 50px; white-space: pre-wrap; 
        font-weight: 600; font-size: 16px; color: #888;
    }
    .stTabs [aria-selected="true"] { color: #b87333; border-bottom-color: #b87333; }
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
            ins_name = st.text_input("保險公司 / 產品名稱", placeholder="例如：安達產險")
            ins_no = st.text_input("保單編號", placeholder="POL12345678")
            ins_date = st.date_input("購買日期", key="ins_d")
        with col2:
            ins_amount = st.number_input("保險金額 (TWD)", min_value=0)
            ins_pay_m = st.selectbox("付款方式", ["信用卡", "現金", "電子支付"], key="ins_pm")
            ins_payer = st.text_input("支付人", value="自己", key="ins_py")
            ins_file = st.file_uploader("上傳保單憑證", type=['pdf', 'jpg', 'png'], key="ins_f")

    if st.button("✅ 儲存保險資訊並記錄支出", type="primary", use_container_width=True):
        if ins_name and ins_amount >= 0:
            if 'ins_records' not in st.session_state: st.session_state.ins_records = []
            st.session_state.ins_records.append({
                "名稱": ins_name, "編號": ins_no, "日期": str(ins_date), 
                "金額": ins_amount, "付款方式": ins_pay_m, "支付人": ins_payer, 
                "檔案名": ins_file.name if ins_file else "無"
            })
            save_to_cloud({
                "日期": str(ins_date), "分類": "其他", "項目": f"保險：{ins_name}",
                "金額": int(ins_amount), "付款方式": ins_pay_m, "支付人": ins_payer, "來源": "清單-保險"
            })
            st.success("保險已同步！")
            st.rerun()

    if 'ins_records' in st.session_state and st.session_state.ins_records:
        st.divider()
        st.subheader("📋 已記錄保險")
        for i, item in enumerate(st.session_state.ins_records):
            with st.expander(f"🛡️ {item['名稱']} - {item['金額']} TWD ({item['支付人']} 支付)"):
                new_n = st.text_input("修改名稱", value=item['名稱'], key=f"ei_n_{i}")
                new_a = st.number_input("修改金額", value=item['金額'], key=f"ei_a_{i}")
                st.write(f"附檔：{item.get('檔案名', '無')}")
                c1, c2 = st.columns(2)
                if c1.button("💾 儲存修改", key=f"ei_s_{i}"):
                    item['名稱'] = new_n; item['金額'] = new_a
                    st.rerun()
                if c2.button("🗑️ 刪除", key=f"ei_d_{i}"):
                    st.session_state.ins_records.pop(i)
                    st.rerun()

# ==========================================
# 2. 交通銜接 (已將時間改為自行輸入的文字框)
# ==========================================
with tab_flight:
    st.header("✈️ 航班與交通銜接")
    c1, c2, c3 = st.columns([1, 1.5, 1.5])
    t_type = c1.selectbox("種類", ["飛機", "高鐵", "火車", "客運", "其他"])
    t_start = c2.text_input("起點")
    t_end = c3.text_input("訖點")
    
    # 新增公司名稱與來回打勾選項的列
    c_comp, c_rt = st.columns([3, 1])
    t_company = c_comp.text_input("營運公司名稱", placeholder="例如：長榮航空、台灣高鐵、南海電鐵", key="t_comp")
    with c_rt:
        st.write("") # 加入空格協助按鈕對齊
        st.write("")
        t_is_roundtrip = st.checkbox("🔄 這是來回票", key="t_rt")
    
    c_dep1, c_dep2, c_arr1, c_arr2 = st.columns(4)
    t_dep_d = c_dep1.date_input("出發日期")
    # ✅ 修改為 st.text_input 讓您可以自由輸入時間
    t_dep_t = c_dep2.text_input("出發時間", placeholder="例如: 08:30")
    t_arr_d = c_arr1.date_input("抵達日期")
    # ✅ 修改為 st.text_input 讓您可以自由輸入時間
    t_arr_t = c_arr2.text_input("抵達時間", placeholder="例如: 15:45")
    
    c4, c5, c6 = st.columns(3)
    t_buy_date = c4.date_input("購買日期", key="t_bd")
    t_amt = c5.number_input("金額", min_value=0.0)
    
    t_curr_sel = c6.selectbox("幣別", CURR_OPTIONS, key="t_c_sel")
    t_curr = c6.text_input("輸入幣別", placeholder="例如: THB", key="t_c_in") if t_curr_sel == "自行輸入" else t_curr_sel
    
    c7, c8, c9 = st.columns(3)
    t_pay_m = c7.selectbox("付款方式", ["信用卡", "現金", "電子支付"], key="t_pm")
    t_payer = c8.text_input("支付人", value="自己", key="t_py")
    t_file = c9.file_uploader("上傳票卷(機票/車票)", type=['pdf', 'jpg', 'png'], key="t_f")

    if st.button("➕ 加入交通清單並記錄支出", type="primary", use_container_width=True):
        if t_start and t_amt >= 0:
            if 'trans_records' not in st.session_state: st.session_state.trans_records = []
            st.session_state.trans_records.append({
                "種類": t_type, "公司": t_company, "來回": t_is_roundtrip, "起點": t_start, "訖點": t_end,
                "出發": f"{t_dep_d} {t_dep_t}", "抵達": f"{t_arr_d} {t_arr_t}",
                "金額": t_amt, "幣別": t_curr, "付款方式": t_pay_m, "支付人": t_payer,
                "檔案名": t_file.name if t_file else "無"
            })
            rate = st.session_state.get('jpy_rate', 0.215) if t_curr == "JPY" else (4.5 if t_curr == "CNY" else 1.0)
            
            # 設定同步至記帳的標籤
            trip_tag = "(來回)" if t_is_roundtrip else "(單程)"
            comp_tag = f"[{t_company}] " if t_company else ""
            
            save_to_cloud({
                "日期": str(t_buy_date), "分類": "交通", "項目": f"{t_type}: {comp_tag}{t_start}➔{t_end} {trip_tag}",
                "金額": int(t_amt * rate), "付款方式": t_pay_m, "支付人": t_payer, "來源": "清單-交通"
            })
            st.success("✅ 交通支出已同步！")
            st.rerun()

    if 'trans_records' in st.session_state and st.session_state.trans_records:
        st.divider()
        st.subheader("📋 已記錄交通")
        for i, item in enumerate(st.session_state.trans_records):
            start_loc = item.get('起點', item.get('行程', '未知起點'))
            end_loc = item.get('訖點', '')
            
            # 組合列表標題顯示
            comp_display = f"[{item.get('公司')}] " if item.get('公司') else ""
            rt_display = "🔄 來回" if item.get('來回') else "➡️ 單程"
            
            exp_title = f"✈️ {item.get('種類', '交通')}: {comp_display}{start_loc}"
            if end_loc: exp_title += f"➔{end_loc}"
            exp_title += f" ({rt_display}) - {item.get('金額', 0)} {item.get('幣別', 'TWD')}"
            
            with st.expander(exp_title):
                st.write(f"出發: {item.get('出發', '未設定')} | 抵達: {item.get('抵達', '未設定')} | 支付人: {item.get('支付人', '未知')} | 檔案: {item.get('檔案名', '無')}")
                
                c_edit1, c_edit2 = st.columns([3, 1])
                new_comp = c_edit1.text_input("修改公司名稱", value=item.get('公司', ''), key=f"et_c_{i}")
                new_rt = c_edit2.checkbox("🔄 這是來回票", value=item.get('來回', False), key=f"et_rt_{i}")

                new_start = st.text_input("修改起點", value=start_loc, key=f"et_s_{i}")
                new_end = st.text_input("修改訖點", value=end_loc, key=f"et_e_{i}")
                new_amt = st.number_input("修改金額", value=item.get('金額', 0.0), key=f"et_a_{i}")
                
                c1, c2 = st.columns(2)
                if c1.button("💾 儲存修改", key=f"et_sv_{i}"):
                    item['公司'] = new_comp
                    item['來回'] = new_rt
                    item['起點'] = new_start
                    item['訖點'] = new_end
                    item['金額'] = new_amt
                    if '行程' in item: del item['行程']
                    st.rerun()
                if c2.button("🗑️ 刪除", key=f"et_d_{i}"):
                    st.session_state.trans_records.pop(i)
                    st.rerun()

# ==========================================
# 3. 飯店住宿 
# ==========================================
with tab_hotel:
    st.header("🏨 飯店住宿預約")
    h_name = st.text_input("飯店名稱")
    
    c1, c2, c3 = st.columns(3)
    h_in = c1.date_input("入住日期")
    h_out = c2.date_input("退房日期")
    nights = (h_out - h_in).days
    
    if nights < 0:
        c3.error("退房日期錯誤！")
    else:
        c3.metric("住宿天數", f"{nights} 晚")
    
    c4, c5, c6 = st.columns(3)
    h_amt = c4.number_input("住宿總金額", min_value=0.0)
    
    h_curr_sel = c5.selectbox("住宿幣別", CURR_OPTIONS, key="h_cur_sel")
    h_curr = c5.text_input("輸入幣別", placeholder="例如: THB", key="h_cur_in") if h_curr_sel == "自行輸入" else h_curr_sel
    
    h_pay_m = c6.selectbox("付款方式", ["信用卡", "現金", "現場支付"], key="h_pm")
    
    c7, c8 = st.columns(2)
    h_payer = c7.text_input("支付人", value="自己", key="h_py")
    h_file = c8.file_uploader("上傳訂房紀錄", type=['pdf', 'jpg', 'png'], key="h_f")

    if st.button("➕ 記錄住宿支出", type="primary", use_container_width=True):
        if h_name and h_amt >= 0 and nights >= 0:
            if 'hotel_records' not in st.session_state: st.session_state.hotel_records = []
            st.session_state.hotel_records.append({
                "飯店": h_name, "入住": str(h_in), "晚數": nights, "金額": h_amt, "幣別": h_curr,
                "支付人": h_payer, "檔案名": h_file.name if h_file else "無"
            })
            rate = st.session_state.get('jpy_rate', 0.215) if h_curr == "JPY" else (4.5 if h_curr == "CNY" else 1.0)
            save_to_cloud({
                "日期": str(h_in), "分類": "住宿", "項目": f"飯店：{h_name}",
                "金額": int(h_amt * rate), "付款方式": h_pay_m, "支付人": h_payer, "來源": "清單-住宿"
            })
            st.success("✅ 住宿費用已同步！")
            st.rerun()

    if 'hotel_records' in st.session_state and st.session_state.hotel_records:
        st.divider()
        st.subheader("📋 已記錄住宿")
        for i, item in enumerate(st.session_state.hotel_records):
            with st.expander(f"🏨 {item['飯店']} ({item['晚數']}晚) - {item['金額']} {item['幣別']}"):
                st.write(f"入住：{item['入住']} | 支付人：{item.get('支付人', '未知')} | 檔案：{item.get('檔案名', '無')}")
                new_h = st.text_input("修改飯店", value=item['飯店'], key=f"eh_n_{i}")
                new_a = st.number_input("修改金額", value=item['金額'], key=f"eh_a_{i}")
                
                c1, c2 = st.columns(2)
                if c1.button("💾 儲存修改", key=f"eh_s_{i}"):
                    item['飯店'] = new_h; item['金額'] = new_a
                    st.rerun()
                if c2.button("🗑️ 刪除", key=f"eh_d_{i}"):
                    st.session_state.hotel_records.pop(i)
                    st.rerun()

# ==========================================
# 4. 票卷 
# ==========================================
with tab_ticket:
    st.header("🎟️ 票卷管理")
    c1, c2 = st.columns(2)
    tk_type = c1.selectbox("票卷種類", ["門票", "餐卷", "交通", "遊樂票卷", "住宿卷"])
    tk_name = c2.text_input("項目名稱")
    
    c3, c4 = st.columns(2)
    tk_buy_date = c3.date_input("購買日期", key="tk_bd")
    tk_use_date = c4.date_input("預計使用日期", key="tk_ud")
    
    c5, c6, c7 = st.columns([1, 1, 1])
    tk_amt = c5.number_input("金額", min_value=0.0, key="tk_a")
    
    tk_curr_sel = c6.selectbox("幣別", CURR_OPTIONS, key="tk_c_sel")
    tk_curr = c6.text_input("輸入幣別", placeholder="例如: THB", key="tk_c_in") if tk_curr_sel == "自行輸入" else tk_curr_sel
    
    tk_pay_m = c7.selectbox("付款方式", ["信用卡", "現金", "電子支付"], key="tk_pm")
    
    c8, c9 = st.columns(2)
    tk_payer = c8.text_input("支付人", value="自己", key="tk_py")
    tk_file = c9.file_uploader("上傳票卷", type=['pdf', 'jpg', 'png'], key="tk_f")

    if st.button("➕ 加入票卷並記錄支出", type="primary", use_container_width=True):
        if tk_name and tk_amt >= 0:
            if 'ticket_records' not in st.session_state: st.session_state.ticket_records = []
            st.session_state.ticket_records.append({
                "種類": tk_type, "名稱": tk_name, "金額": tk_amt, "幣別": tk_curr,
                "使用日": str(tk_use_date), "支付人": tk_payer, "檔案名": tk_file.name if tk_file else "無"
            })
            rate = st.session_state.get('jpy_rate', 0.215) if tk_curr == "JPY" else (4.5 if tk_curr == "CNY" else 1.0)
            save_to_cloud({
                "日期": str(tk_buy_date), "分類": "門票/娛樂", "項目": f"{tk_type}：{tk_name}",
                "金額": int(tk_amt * rate), "付款方式": tk_pay_m, "支付人": tk_payer, "來源": "清單-票卷"
            })
            st.success("✅ 票卷支出已同步！")
            st.rerun()

    if 'ticket_records' in st.session_state and st.session_state.ticket_records:
        st.divider()
        st.subheader("📋 已記錄票卷")
        for i, item in enumerate(st.session_state.ticket_records):
            with st.expander(f"🎟️ [{item['種類']}] {item['名稱']} - {item['金額']} {item['幣別']}"):
                st.write(f"使用日：{item['使用日']} | 支付人：{item.get('支付人', '未知')} | 檔案：{item.get('檔案名', '無')}")
                new_n = st.text_input("修改名稱", value=item['名稱'], key=f"etk_n_{i}")
                new_a = st.number_input("修改金額", value=item['金額'], key=f"etk_a_{i}")
                
                c1, c2 = st.columns(2)
                if c1.button("💾 儲存修改", key=f"etk_s_{i}"):
                    item['名稱'] = new_n; item['金額'] = new_a
                    st.rerun()
                if c2.button("🗑️ 刪除", key=f"etk_d_{i}"):
                    st.session_state.ticket_records.pop(i)
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
            final_currency = st.text_input("自訂幣別", placeholder="例如: THB") if ex_curr_sel == "自行輸入" else ex_curr_sel
            
        with col2: ex_date = st.date_input("換匯日期", key="ex_date")
        with col3: ex_loc = st.text_input("地點", placeholder="例如：台灣銀行、成田機場 ATM")

        col4, col5, col6 = st.columns(3)
        with col4: ex_amount = st.number_input("金額 (外幣)", min_value=0.0, step=100.0, key="ex_amt")
        with col5: ex_rate = st.number_input("匯率", min_value=0.0, format="%.4f", step=0.0001, key="ex_rate_input", value=0.215)
        with col6:
            twd_cost = ex_amount * ex_rate
            st.metric("換匯成本 (TWD)", f"{int(twd_cost):,}")

    if st.button("➕ 記錄換匯", use_container_width=True):
        if ex_amount > 0 and ex_rate > 0:
            if 'exchange_records' not in st.session_state: st.session_state.exchange_records = []
            
            # 自動更新全局 JPY 匯率
            if final_currency == "JPY":
                st.session_state['jpy_rate'] = ex_rate
                st.toast(f"全系統日幣匯率已自動更新為: {st.session_state['jpy_rate']:.4f}")

            st.session_state.exchange_records.append({
                "日期": str(ex_date), "地點": ex_loc, "幣別": final_currency, 
                "金額": ex_amount, "匯率": ex_rate, "台幣成本": int(twd_cost)
            })
            st.success("換匯紀錄已儲存！")
            st.rerun()

    if 'exchange_records' in st.session_state and st.session_state.exchange_records:
        st.divider()
        st.subheader("📋 換匯明細")
        for i, item in enumerate(st.session_state.exchange_records):
            
            # 防呆機制
            old_from = item.get('從', '')  
            amt_val = item.get('金額', old_from)
            curr_val = item.get('幣別', '')
            rate_val = item.get('匯率', '未知')
            
            with st.expander(f"💱 {item.get('日期', '')} | {item.get('地點','')} - {amt_val} {curr_val} (匯率: {rate_val})"):
                
                try: default_date = pd.to_datetime(item.get('日期', pd.Timestamp.now().date())).date()
                except: default_date = pd.Timestamp.now().date()
                
                new_d = st.date_input("修改日期", value=default_date, key=f"ex_date_{i}")
                new_l = st.text_input("修改地點", value=item.get('地點',''), key=f"ex_loc_{i}")
                
                c1, c2, c3 = st.columns(3)
                new_c = c1.text_input("修改幣別", value=item.get('幣別', ''), key=f"ex_curr_{i}")
                
                try: default_amt = float(item.get('金額', 0.0))
                except: default_amt = 0.0
                new_a = c2.number_input("修改外幣金額", value=default_amt, key=f"ex_amt_edit_{i}")
                
                try: default_rate = float(item.get('匯率', 0.0))
                except: default_rate = 0.0
                new_r = c3.number_input("修改匯率", value=default_rate, format="%.4f", step=0.0001, key=f"ex_rate_edit_{i}")
                
                st.caption(f"重新計算成本 (TWD): {int(new_a * new_r):,}")
                
                c_btn1, c_btn2 = st.columns(2)
                if c_btn1.button("💾 儲存修改", key=f"ex_sv_{i}"):
                    item['日期'] = str(new_d)
                    item['地點'] = new_l
                    item['幣別'] = new_c
                    item['金額'] = new_a
                    item['匯率'] = new_r
                    item['台幣成本'] = int(new_a * new_r)
                    for old_k in ['從', '換成', '用途']:
                        if old_k in item: del item[old_k]
                    st.rerun()
                
                if c_btn2.button("🗑️ 刪除", key=f"ex_del_{i}"):
                    st.session_state.exchange_records.pop(i)
                    st.rerun()

# ==========================================
# 6. 行李裝備 
# ==========================================
with tab_pack:
    st.header("🎒 裝備清單")
    with st.expander("➕ 新增裝備 (若新購可同步記帳)", expanded=False):
        c_n, c_q = st.columns([3, 1])
        g_name = c_n.text_input("裝備名稱")
        g_qty = c_q.number_input("數量", min_value=1, value=1, key="g_q")
        
        is_new = st.checkbox("這是為此行新買的")
        
        c1, c2, c3 = st.columns(3)
        g_amt = c1.number_input("總金額 (TWD)", min_value=0, disabled=not is_new)
        g_pay_m = c2.selectbox("付款方式", ["現金", "信用卡"], disabled=not is_new)
        g_payer = c3.text_input("支付人", value="自己", disabled=not is_new)
        
        g_file = st.file_uploader("上傳裝備照片", type=['jpg', 'png', 'jpeg'], key="g_f")
        
        if st.button("📥 加入清單", type="primary", use_container_width=True):
            if 'packing_list' not in st.session_state: st.session_state.packing_list = []
            img_bytes = g_file.getvalue() if g_file is not None else None
            
            st.session_state.packing_list.append({
                "名稱": g_name, "數量": g_qty, "狀態": False, "新購": is_new, 
                "金額": g_amt if is_new else 0, "支付人": g_payer if is_new else "無", 
                "照片資料": img_bytes, "檔案名": g_file.name if g_file else "無"
            })
            
            if is_new and g_amt > 0:
                save_to_cloud({"日期": str(pd.Timestamp.now().date()), "分類": "購物", "項目": f"裝備:{g_name}({g_qty}個)", "金額": g_amt, "付款方式": g_pay_m, "支付人": g_payer, "來源": "清單-裝備"})
            st.toast(f"已加入：{g_name}")
            st.rerun()

    if 'packing_list' in st.session_state and st.session_state.packing_list:
        st.divider()
        st.subheader("📋 裝備明細 (點擊展開編輯或看照片)")
        
        checked_count = sum(1 for item in st.session_state.packing_list if item.get('狀態', False))
        st.progress(checked_count / len(st.session_state.packing_list) if len(st.session_state.packing_list) > 0 else 0)
        st.caption(f"打包進度: {checked_count} / {len(st.session_state.packing_list)}")

        for i, item in enumerate(st.session_state.packing_list):
            c_chk, c_exp = st.columns([0.1, 0.9])
            
            checked = c_chk.checkbox("", value=item.get('狀態', False), key=f"pk_chk_{i}")
            if checked != item.get('狀態', False):
                st.session_state.packing_list[i]['狀態'] = checked
                st.rerun()
            
            new_tag = "🆕" if item.get('新購', False) else ""
            with c_exp.expander(f"🎒 {item['名稱']} x {item.get('數量', 1)} {new_tag}"):
                if item.get('照片資料'):
                    try: st.image(item['照片資料'], width=200)
                    except: st.caption("無法載入圖片預覽")
                else:
                    st.caption(f"附件：{item.get('檔案名', '無')}")
                
                st.write(f"金額：{item.get('金額', 0)} | 支付人：{item.get('支付人', '未知')}")
                new_n = st.text_input("修改名稱", value=item['名稱'], key=f"epk_n_{i}")
                new_q = st.number_input("修改數量", min_value=1, value=item.get('數量', 1), key=f"epk_q_{i}")
                
                st.write("---")
                st.caption("🖼️ 照片管理")
                new_pic = st.file_uploader("更換照片 (若不上傳則保留原圖)", type=['jpg', 'png', 'jpeg'], key=f"epk_pic_{i}")
                del_pic = st.checkbox("刪除現有照片", key=f"epk_delpic_{i}")
                
                c1, c2 = st.columns(2)
                if c1.button("💾 儲存修改", key=f"epk_s_{i}"):
                    item['名稱'] = new_n; item['數量'] = new_q
                    if del_pic:
                        item['照片資料'] = None
                        item['檔案名'] = "無"
                    elif new_pic:
                        item['照片資料'] = new_pic.getvalue()
                        item['檔案名'] = new_pic.name
                    st.rerun()
                if c2.button("🗑️ 刪除", key=f"epk_d_{i}"):
                    st.session_state.packing_list.pop(i)
                    st.rerun()

# ==========================================
# 7. 伴手禮清單 
# ==========================================
with tab_gift:
    st.header("🎁 伴手禮採購")
    with st.container():
        c_n, c_q = st.columns([3, 1])
        gift_n = c_n.text_input("品項名稱")
        gift_qty = c_q.number_input("數量", min_value=1, value=1, key="gf_q")
        
        gift_target = st.text_input("送給誰")
        
        c1, c2 = st.columns(2)
        gift_amt = c1.number_input("預估/實際 總金額", min_value=0)
        
        gift_curr_sel = c2.selectbox("幣別", CURR_OPTIONS, key="gf_c_sel")
        gift_curr = c2.text_input("輸入幣別", placeholder="例如: THB", key="gf_c_in") if gift_curr_sel == "自行輸入" else gift_curr_sel
        
        c3, c4 = st.columns(2)
        gift_payer = c3.text_input("支付人", value="自己", key="gf_py")
        gift_file = c4.file_uploader("上傳禮物照片 (給代購看或記錄)", type=['jpg', 'png', 'jpeg'], key="gf_f")

        if st.button("➕ 加入伴手禮並同步至總帳", type="primary", use_container_width=True):
            if gift_n:
                if 'gift_list' not in st.session_state: st.session_state.gift_list = []
                img_bytes = gift_file.getvalue() if gift_file is not None else None
                
                st.session_state.gift_list.append({
                    "名稱": gift_n, "數量": gift_qty, "對象": gift_target, "金額": gift_amt, "幣別": gift_curr,
                    "支付人": gift_payer, "照片資料": img_bytes, "檔案名": gift_file.name if gift_file else "無"
                })
                
                rate = st.session_state.get('jpy_rate', 0.215) if gift_curr == "JPY" else (4.5 if gift_curr == "CNY" else 1.0)
                save_to_cloud({"日期": str(pd.Timestamp.now().date()), "分類": "購物", "項目": f"禮物:{gift_n} x{gift_qty} (給{gift_target})", "金額": int(gift_amt * rate), "付款方式": "現金", "支付人": gift_payer, "來源": "清單-伴手禮"})
                st.success(f"✅ {gift_n} 已入帳！")
                st.rerun()

    if 'gift_list' in st.session_state and st.session_state.gift_list:
        st.divider()
        st.subheader("📋 已記錄伴手禮")
        for i, item in enumerate(st.session_state.gift_list):
            with st.expander(f"🎁 {item['名稱']} x {item.get('數量', 1)} (給 {item['對象']}) - {item['金額']} {item['幣別']}"):
                if item.get('照片資料'):
                    try: st.image(item['照片資料'], width=200)
                    except: st.caption("無法載入圖片預覽")
                else:
                    st.caption(f"附件：{item.get('檔案名', '無')}")
                
                st.write(f"支付人：{item.get('支付人', '未知')}")    
                new_n = st.text_input("修改名稱", value=item['名稱'], key=f"egf_n_{i}")
                new_q = st.number_input("修改數量", min_value=1, value=item.get('數量', 1), key=f"egf_q_{i}")
                
                st.write("---")
                st.caption("🖼️ 照片管理")
                new_pic = st.file_uploader("更換照片 (若不上傳則保留原圖)", type=['jpg', 'png', 'jpeg'], key=f"egf_pic_{i}")
                del_pic = st.checkbox("刪除現有照片", key=f"egf_delpic_{i}")
                
                c1, c2 = st.columns(2)
                if c1.button("💾 儲存修改", key=f"egf_s_{i}"):
                    item['名稱'] = new_n; item['數量'] = new_q
                    if del_pic:
                        item['照片資料'] = None
                        item['檔案名'] = "無"
                    elif new_pic:
                        item['照片資料'] = new_pic.getvalue()
                        item['檔案名'] = new_pic.name
                    st.rerun()
                if c2.button("🗑️ 刪除", key=f"egf_d_{i}"):
                    st.session_state.gift_list.pop(i)
                    st.rerun()
