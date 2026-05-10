import streamlit as st
import pandas as pd
from datetime import date, datetime, time
import folium
from folium.plugins import Geocoder
from streamlit_folium import st_folium
from streamlit_gsheets import GSheetsConnection

st.set_page_config(page_title="旅遊足跡與地圖", page_icon="🗺️", layout="wide")

# --- 0. 旅程動態對接邏輯 ---
target_sheet = st.session_state.get('active_trip_sheet', 'Exp_Yunnan2026')
target_name = st.session_state.get('active_trip_name', '2026 雲南探索 (預設)')

with st.sidebar:
    st.header("🎯 存檔目標")
    st.success(f"目前連線旅程：\n\n**{target_name}**")
    st.caption(f"雲端寫入分頁：`{target_sheet}`")
    st.divider()

# --- 1. 雲端連線與資料初始化 ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error(f"連線初始化失敗: {e}")
    st.stop()

# 🔴 擴充欄位：新增「支付人」
EXPECTED_COLUMNS = ["日期", "分類", "項目", "金額", "付款方式", "支付人", "來源"]
CURR_OPTIONS = ["TWD", "USD", "EUR", "JPY", "CNY", "自行輸入"]

@st.cache_data(ttl=5)
def fetch_cloud_expenses(sheet_name):
    """快取讀取雲端資料"""
    try:
        df = conn.read(worksheet=sheet_name, ttl=0)
        if df.empty: return pd.DataFrame(columns=EXPECTED_COLUMNS)
        return df
    except:
        return pd.DataFrame(columns=EXPECTED_COLUMNS)

def save_spot_exp_to_cloud(new_row_df):
    try:
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
        fetch_cloud_expenses.clear() 
        return True
    except Exception as e:
        st.error(f"❌ 同步失敗: {e}")
        return False

# --- 新增：更新與刪除函數 ---
def update_in_cloud(row_index, updated_dict):
    try:
        df = conn.read(worksheet=target_sheet, ttl=0)
        for key, value in updated_dict.items():
            df.at[row_index, key] = value
        conn.update(worksheet=target_sheet, data=df[EXPECTED_COLUMNS])
        st.cache_data.clear()
        fetch_cloud_expenses.clear()
        return True
    except Exception as e:
        st.error(f"❌ 雲端更新失敗: {e}")
        return False

def delete_from_cloud(row_index):
    try:
        df = conn.read(worksheet=target_sheet, ttl=0)
        df = df.drop(index=row_index)
        conn.update(worksheet=target_sheet, data=df[EXPECTED_COLUMNS])
        st.cache_data.clear()
        fetch_cloud_expenses.clear()
        return True
    except Exception as e:
        st.error(f"❌ 雲端刪除失敗: {e}")
        return False

# --- 職人風格 CSS ---
st.markdown("""
    <style>
    h1 { border-bottom: 2px solid #b87333; padding-bottom: 10px; }
    .simple-item { 
        padding: 8px 12px; 
        border-bottom: 1px solid #333; 
        display: flex; 
        justify-content: space-between; 
        align-items: center;
        background-color: #1e1e1e;
        border-left: 4px solid #b87333;
        margin-top: 5px;
    }
    .simple-title { font-weight: bold; color: #e0e0e0; font-size: 1.1em; }
    .simple-meta { font-size: 0.85em; color: #888; }
    .date-header { 
        color: #b87333; 
        margin-top: 20px; 
        margin-bottom: 5px; 
        font-weight: bold; 
        border-bottom: 1px solid #444; 
        padding-bottom: 3px;
    }
    .time-tag {
        color: #ffa500; font-weight: bold; background: rgba(255, 165, 0, 0.1);
        padding: 2px 6px; border-radius: 4px; margin-right: 5px;
    }
    /* 確保地圖搜尋框置頂顯示 */
    .leaflet-control-geocoder { 
        margin-top: 10px !important; 
        background: white !important; 
        border: 2px solid rgba(0,0,0,0.3) !important;
        z-index: 1000 !important;
        box-shadow: 0 2px 6px rgba(0,0,0,0.3) !important;
    }
    .leaflet-control-geocoder-icon { width: 30px !important; height: 30px !important; }
    </style>
""", unsafe_allow_html=True)

st.title("🗺️ 數位旅遊足跡與動線 (搜尋強化版)")

# --- 2. 足跡本地端狀態初始化 ---
if 'footprint_data' not in st.session_state: st.session_state.footprint_data = []
if 'clicked_lat' not in st.session_state: st.session_state.clicked_lat = 35.6895
if 'clicked_lng' not in st.session_state: st.session_state.clicked_lng = 139.6917

TYPE_OPTIONS = ["自然景觀", "歷史古蹟", "餐飲美食", "交通節點", "住宿", "購物", "門票/娛樂", "其他"]

# --- 列表操作函數 ---
def move_up(idx):
    if idx > 0:
        st.session_state.footprint_data[idx], st.session_state.footprint_data[idx-1] = \
        st.session_state.footprint_data[idx-1], st.session_state.footprint_data[idx]

def move_down(idx):
    if idx < len(st.session_state.footprint_data) - 1:
        st.session_state.footprint_data[idx], st.session_state.footprint_data[idx+1] = \
        st.session_state.footprint_data[idx+1], st.session_state.footprint_data[idx]

def delete_pt(idx):
    st.session_state.footprint_data.pop(idx)

# --- 3. 介面佈局 ---
col_form, col_map = st.columns([1.1, 2])

with col_form:
    st.header("📍 新增足跡點")
    with st.form("footprint_form", clear_on_submit=True):
        pt_name = st.text_input("景點名稱*", placeholder="例如：新倉淺間神社")
        c1, c2 = st.columns(2)
        with c1:
            pt_date = st.date_input("造訪日期", value=date.today())
            pt_lat = st.number_input("緯度", format="%.6f", value=st.session_state.clicked_lat)
        with c2:
            pt_type = st.selectbox("類型", TYPE_OPTIONS)
            pt_lng = st.number_input("經度", format="%.6f", value=st.session_state.clicked_lng)
        
        t1, t2, t3 = st.columns([1.2, 1, 1])
        with t1: pt_arrival = st.time_input("抵達時間", value=time(10, 0))
        with t2: pt_dur_val = st.number_input("停留時長", min_value=0, value=1)
        with t3: pt_dur_unit = st.selectbox("單位", ["小時", "分鐘"])
            
        pt_desc = st.text_area("筆記", placeholder="回憶內容...", height=80)
        uploaded_files = st.file_uploader("📷 照片 (最多20張)", type=["jpg", "jpeg", "png"], accept_multiple_files=True)
        
        if st.form_submit_button("💾 記錄空間足跡", type="primary", use_container_width=True):
            if not pt_name: 
                st.error("請填寫景點名稱")
            else:
                processed_photos = []
                if uploaded_files:
                    for f in uploaded_files[:20]:
                        processed_photos.append({"name": f.name, "data": f.read()})
                new_pt = {
                    "名稱": pt_name, "日期": str(pt_date), "類型": pt_type,
                    "緯度": pt_lat, "經度": pt_lng, 
                    "抵達時間": pt_arrival.strftime("%H:%M"),
                    "停留時間": f"{pt_dur_val} {pt_dur_unit}",
                    "描述": pt_desc, "照片": processed_photos
                }
                st.session_state.footprint_data.append(new_pt)
                st.rerun()
    st.info("💡 提示：地圖搜尋到位置後點擊，座標會自動填入上方。")

with col_map:
    # --- 地圖渲染 ---
    if st.session_state.footprint_data:
        center = [st.session_state.footprint_data[-1]["緯度"], st.session_state.footprint_data[-1]["經度"]]
    else: center = [st.session_state.clicked_lat, st.session_state.clicked_lng]

    m = folium.Map(location=center, zoom_start=15, tiles="CartoDB positron")
    
    Geocoder(position='topleft', collapsed=False, add_marker=True).add_to(m)
    
    route_coords = [[pt["緯度"], pt["經度"]] for pt in st.session_state.footprint_data]
    for pt in st.session_state.footprint_data:
        folium.Marker([pt["緯度"], pt["經度"]], tooltip=f"{pt['名稱']} ({pt.get('抵達時間','')})").add_to(m)
    if len(route_coords) > 1:
        folium.PolyLine(route_coords, color="#b87333", weight=4, opacity=0.8).add_to(m)
        
    map_data = st_folium(m, width=1000, height=600, returned_objects=["last_clicked"])
    
    if map_data and map_data["last_clicked"]:
        st.session_state.clicked_lat = map_data["last_clicked"]["lat"]
        st.session_state.clicked_lng = map_data["last_clicked"]["lng"]
        st.rerun()

st.divider()

# --- 4. 旅程足跡管理 ---
st.subheader("📜 旅程足跡管理")
if not st.session_state.footprint_data: 
    st.info("尚無足跡資料。")
else:
    current_date = None
    for i, pt in enumerate(st.session_state.footprint_data):
        if pt['日期'] != current_date:
            st.markdown(f"<div class='date-header'>📅 {pt['日期']}</div>", unsafe_allow_html=True)
            current_date = pt['日期']

        c_info, c_btns = st.columns([4, 1.2])
        with c_info:
            st.markdown(f"""<div class="simple-item"><div><span class="time-tag">🕒 {pt.get('抵達時間','--:--')}</span>
                <span class="simple-title">{pt['名稱']}</span><span class="simple-meta"> | 停留: {pt.get('停留時間','-')} | {pt.get('類型','其他')}</span></div></div>""", unsafe_allow_html=True)
        with c_btns:
            b1, b2, b3 = st.columns(3)
            b1.button("⬆️", key=f"u_{i}", on_click=move_up, args=(i,), disabled=(i==0))
            b2.button("⬇️", key=f"d_{i}", on_click=move_down, args=(i,), disabled=(i==len(st.session_state.footprint_data)-1))
            b3.button("❌", key=f"x_{i}", on_click=delete_pt, args=(i,))
        
        with st.expander(f"⚙️ 管理/編輯 {pt['名稱']} 的細節回憶"):
            tab_edit, tab_pic, tab_exp = st.tabs(["📝 修改基本資料", "📷 照片管理", "💸 景點花費 (連動雲端)"])
            
            # --- Tab 1: 修改基本資料 ---
            with tab_edit:
                with st.form(key=f"edit_form_{i}"):
                    new_n = st.text_input("景點名稱", value=pt['名稱'])
                    ec1, ec2, ec3 = st.columns([1, 1, 1.5])
                    new_t = ec1.text_input("抵達時間 (HH:MM)", value=pt.get('抵達時間','10:00'))
                    new_d = ec2.text_input("停留時間", value=pt.get('停留時間','1 小時'))
                    saved_type = pt.get('類型', '其他')
                    try: type_idx = TYPE_OPTIONS.index(saved_type)
                    except ValueError: type_idx = 7
                    new_type = ec3.selectbox("類型", TYPE_OPTIONS, index=type_idx)
                    new_desc = st.text_area("筆記內容", value=pt.get('描述',''))
                    
                    st.markdown("---")
                    more_files = st.file_uploader("➕ 補傳照片", type=["jpg","png"], accept_multiple_files=True, key=f"more_{i}")
                    
                    if st.form_submit_button("✅ 儲存修改"):
                        pt['名稱'], pt['抵達時間'], pt['停留時間'], pt['描述'], pt['類型'] = new_n, new_t, new_d, new_desc, new_type
                        if more_files:
                            pt.setdefault('照片', [])
                            for f in more_files:
                                if len(pt['照片']) < 20:
                                    pt['照片'].append({"name": f.name, "data": f.read()})
                        st.success("資料已更新！")
                        st.rerun()

            # --- Tab 2: 照片管理 ---
            with tab_pic:
                photos = pt.get("照片", [])
                if photos:
                    st.caption(f"目前已有 {len(photos)} 張照片")
                    cols = st.columns(4)
                    for idx, img in enumerate(photos):
                        with cols[idx % 4]:
                            st.image(img["data"], use_container_width=True)
                            if st.button("🗑️ 刪除", key=f"del_img_{i}_{idx}"):
                                pt['照片'].pop(idx)
                                st.rerun()
                else: 
                    st.info("尚未上傳照片。")

            # --- Tab 3: 景點花費 (包含修改與刪除) ---
            with tab_exp:
                # 動態從雲端撈取屬於這個景點的消費紀錄來顯示與編輯
                cloud_df = fetch_cloud_expenses(target_sheet)
                if not cloud_df.empty and "來源" in cloud_df.columns:
                    pt_expenses = cloud_df[cloud_df["來源"] == f"📍 足跡: {pt['名稱']}"]
                    
                    if not pt_expenses.empty:
                        for idx, e in pt_expenses.iterrows():
                            with st.expander(f"✅ [{e.get('分類','其他')}] {e.get('項目','')} : NT$ {e.get('金額',0):,} (由 {e.get('支付人','未知')} 支付)"):
                                
                                cat_opts = ["餐飲", "門票/娛樂", "交通", "購物", "其他"]
                                cat_val = e.get('分類', '其他')
                                cat_idx = cat_opts.index(cat_val) if cat_val in cat_opts else 4
                                new_cat = st.selectbox("修改分類", cat_opts, index=cat_idx, key=f"ecat_{i}_{idx}")
                                
                                new_item = st.text_input("修改項目", value=e.get('項目', ''), key=f"eitem_{i}_{idx}")
                                
                                col_a, col_pm, col_py = st.columns(3)
                                try: default_amt = float(e.get('金額', 0))
                                except: default_amt = 0.0
                                new_amt = col_a.number_input("修改金額 (TWD)", value=default_amt, key=f"eamt_{i}_{idx}")
                                
                                pm_opts = ["現金", "信用卡", "電子支付", "公費扣款"]
                                pm_val = e.get('付款方式', '現金')
                                pm_idx = pm_opts.index(pm_val) if pm_val in pm_opts else 0
                                new_pm = col_pm.selectbox("修改付款方式", pm_opts, index=pm_idx, key=f"epm_{i}_{idx}")
                                
                                new_pyr = col_py.text_input("修改支付人", value=e.get('支付人', '自己'), key=f"epyr_{i}_{idx}")
                                
                                bc1, bc2 = st.columns(2)
                                if bc1.button("💾 儲存修改", key=f"esv_{i}_{idx}"):
                                    update_in_cloud(idx, {
                                        "分類": new_cat, "項目": new_item, "金額": int(new_amt), 
                                        "付款方式": new_pm, "支付人": new_pyr
                                    })
                                    st.success("已更新雲端資料！")
                                    st.rerun()
                                if bc2.button("🗑️ 刪除", key=f"edel_{i}_{idx}"):
                                    delete_from_cloud(idx)
                                    st.success("已從雲端刪除！")
                                    st.rerun()
                    else:
                        st.caption("目前此景點無花費紀錄。")
                
                st.write("---")
                
                # 新增消費的表單
                with st.form(key=f"exp_{i}", clear_on_submit=True):
                    st.caption("➕ 新增景點花費")
                    c1, c2 = st.columns([1, 1.5])
                    e_cat = c1.selectbox("分類", ["餐飲", "門票/娛樂", "交通", "購物", "其他"], key=f"ec_{i}")
                    e_item = c2.text_input("項目", value=pt['名稱'], key=f"ei_{i}")
                    
                    c3, c4, c4_extra = st.columns([1, 1, 1])
                    e_amt = c3.number_input("金額", min_value=0.0, key=f"ea_{i}")
                    
                    # 🔴 擴充：幣別選擇包含「自行輸入」
                    e_curr_sel = c4.selectbox("幣別", CURR_OPTIONS, key=f"ecu_{i}")
                    e_curr_cust = c4_extra.text_input("自訂幣別 (若選自行輸入)", placeholder="如: THB", key=f"ecucust_{i}")
                    
                    c5, c6 = st.columns(2)
                    e_payer = c5.text_input("支付人", value="自己", key=f"epayer_{i}")
                    e_pay_method = c6.selectbox("付款方式", ["現金", "信用卡", "電子支付", "公費扣款"], key=f"epm_{i}")
                    
                    if st.form_submit_button("➕ 寫入雲端總帳", type="primary", use_container_width=True):
                        if e_amt > 0:
                            # 判斷最終幣別
                            final_curr = e_curr_cust if e_curr_sel == "自行輸入" and e_curr_cust else e_curr_sel
                            
                            # 簡單匯率計算
                            rates = {"JPY": st.session_state.get('jpy_rate', 0.215), "CNY": 4.5, "USD": 32.5, "EUR": 35.0, "TWD": 1.0}
                            rate = rates.get(final_curr, 1.0)
                            
                            new_row = pd.DataFrame([{
                                "日期": pt['日期'], 
                                "分類": e_cat,
                                "項目": f"{e_item} ({final_curr} {e_amt})",
                                "金額": int(e_amt * rate), 
                                "付款方式": e_pay_method, 
                                "支付人": e_payer,
                                "來源": f"📍 足跡: {pt['名稱']}"
                            }])
                            
                            with st.spinner(f"🚀 正在同步至 {target_sheet}..."):
                                if save_spot_exp_to_cloud(new_row):
                                    st.success("✅ 景點花費已同步至總帳！")
                                    st.rerun()
                        else:
                            st.warning("請填寫大於 0 的金額")