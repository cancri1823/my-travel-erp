import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection

st.set_page_config(page_title="啟人的旅遊 ERP 戰情室", page_icon="🏠", layout="wide")

# --- 職人風格介面優化 ---
st.markdown("""
    <style>
    .status-future { color: #00ff00; font-weight: bold; }
    .status-past { color: #888; font-weight: bold; }
    h1 { border-bottom: 2px solid #b87333; padding-bottom: 10px; }
    .trip-card {
        background-color: #1a1a1a;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #333;
        margin-bottom: 15px;
    }
    </style>
""", unsafe_allow_html=True)

st.title("🏠 旅遊 ERP 旅程管理中心")

# --- 1. 連線至 Google Sheets 目錄 (Trip_Index) ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error(f"❌ 連線初始化失敗: {e}")
    st.stop()

EXPECTED_INDEX_COLS = ["年份", "日期", "旅程名稱", "對應分頁", "狀態"]

# --- 雲端操作函數群 ---
def update_trip_in_cloud(row_index, updated_dict):
    try:
        df = conn.read(worksheet="Trip_Index", ttl=0)
        for key, value in updated_dict.items():
            df.at[row_index, key] = value
        # 重新計算年份以防日期被修改
        if "日期" in updated_dict:
            df.at[row_index, "年份"] = pd.to_datetime(updated_dict["日期"]).year
            
        conn.update(worksheet="Trip_Index", data=df[EXPECTED_INDEX_COLS])
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"❌ 修改失敗: {e}")
        return False

def delete_trip_from_cloud(row_index):
    try:
        df = conn.read(worksheet="Trip_Index", ttl=0)
        df = df.drop(index=row_index)
        conn.update(worksheet="Trip_Index", data=df[EXPECTED_INDEX_COLS])
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"❌ 刪除失敗: {e}")
        return False

# 讀取旅程清單
try:
    df_trips = conn.read(worksheet="Trip_Index", ttl=0)
    if df_trips.empty:
        df_trips = pd.DataFrame(columns=EXPECTED_INDEX_COLS)
except:
    st.warning("⚠️ 系統尚未讀取到 `Trip_Index` 目錄分頁。請確認 Google Sheets 設定。")
    df_trips = pd.DataFrame(columns=EXPECTED_INDEX_COLS)

# --- 2. 側邊欄：當前啟動狀態 ---
with st.sidebar:
    st.header("🔑 系統核心狀態")
    if 'active_trip_name' in st.session_state:
        st.success(f"📍 目前連線旅程：\n\n**{st.session_state.active_trip_name}**")
        if st.button("🔌 登出目前的旅程", use_container_width=True):
            del st.session_state['active_trip_name']
            del st.session_state['active_trip_sheet']
            st.rerun()
    else:
        st.warning("⚠️ 請選擇一項旅程開始編輯。")
    st.divider()

# --- 3. 建立新旅程功能 ---
with st.expander("➕ 建立新的旅程專案", expanded=False):
    with st.form("new_trip_form", clear_on_submit=True):
        st.caption("填寫後將自動寫入雲端目錄 (`Trip_Index`)")
        c1, c2 = st.columns(2)
        n_date = c1.date_input("出發日期")
        n_name = c2.text_input("旅程名稱", placeholder="例如：2026 沖繩之旅")
        
        c3, c4 = st.columns(2)
        n_sheet = c3.text_input("雲端專屬分頁名稱", placeholder="例如：Exp_Okinawa2026")
        n_status = c4.selectbox("目前狀態", ["規劃中", "已結束"])
        
        if st.form_submit_button("🔨 建立旅程檔案", type="primary", use_container_width=True):
            if n_name and n_sheet:
                new_trip = pd.DataFrame([{
                    "年份": n_date.year, "日期": str(n_date), "旅程名稱": n_name,
                    "對應分頁": n_sheet, "狀態": n_status
                }])
                try:
                    updated_df = pd.concat([df_trips, new_trip], ignore_index=True)
                    conn.update(worksheet="Trip_Index", data=updated_df[EXPECTED_INDEX_COLS])
                    st.cache_data.clear()
                    st.success(f"✅ 成功建立：{n_name}！")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ 寫入失敗: {e}")
            else:
                st.error("⚠️ 請完整填寫！")

st.divider()

# --- 4. 主頁面：動態旅程列表 (新增修改與刪除) ---
if not df_trips.empty:
    # 依年份排序 (新到舊)
    df_trips["年份"] = pd.to_numeric(df_trips["年份"], errors='coerce').fillna(0).astype(int)
    all_years = sorted(df_trips['年份'].unique(), reverse=True)

    for year in all_years:
        if year == 0: continue
        st.subheader(f"📅 {year} 年份旅程")
        year_trips = df_trips[df_trips['年份'] == year]
        
        for idx, t in year_trips.iterrows():
            with st.container():
                # 排版：名稱資訊 | 狀態 | 操作按鈕
                c1, c2, c3, c4 = st.columns([2.5, 1, 1, 1])
                
                with c1:
                    st.markdown(f"#### {t.get('旅程名稱', '未命名')}")
                    st.caption(f"出發日：{t.get('日期', '未定')} | ☁️ 分頁：`{t.get('對應分頁', '')}`")
                
                with c2:
                    status_val = t.get('狀態', '未知')
                    if status_val == "規劃中":
                        st.markdown(f"<br><span class='status-future'>🚀 {status_val}</span>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<br><span class='status-past'>✅ {status_val}</span>", unsafe_allow_html=True)
                
                with c3:
                    st.write("") # 對齊用
                    is_active = st.session_state.get('active_trip_sheet') == t.get('對應分頁', '')
                    if st.button("📝 進入管理", key=f"edit_{idx}", disabled=is_active, use_container_width=True):
                        st.session_state['active_trip_name'] = t.get('旅程名稱', '未命名')
                        st.session_state['active_trip_sheet'] = t.get('對應分頁', '')
                        st.rerun()
                
                with c4:
                    st.write("") # 對齊用
                    if st.button("🗑️ 刪除", key=f"del_{idx}", use_container_width=True):
                        if delete_trip_from_cloud(idx):
                            if st.session_state.get('active_trip_sheet') == t.get('對應分頁', ''):
                                st.session_state.pop('active_trip_name', None)
                                st.session_state.pop('active_trip_sheet', None)
                            st.rerun()

                # ✏️ 修改區塊 (隱藏在摺疊選單中)
                with st.expander(f"✏️ 修改「{t.get('旅程名稱')}」的資訊"):
                    with st.form(key=f"mod_form_{idx}"):
                        m_name = st.text_input("修改旅程名稱", value=t.get('旅程名稱'))
                        col_m1, col_m2 = st.columns(2)
                        m_date = col_m1.date_input("修改日期", value=pd.to_datetime(t.get('日期')).date())
                        m_status = col_m2.selectbox("修改狀態", ["規劃中", "已結束"], index=0 if t.get('狀態')=="規劃中" else 1)
                        
                        st.caption("註：對應分頁名稱涉及資料結構，不建議隨意更動。")
                        
                        if st.form_submit_button("💾 儲存變更", use_container_width=True):
                            upd_data = {
                                "旅程名稱": m_name,
                                "日期": str(m_date),
                                "狀態": m_status
                            }
                            if update_trip_in_cloud(idx, upd_data):
                                st.success("資料已同步更新！")
                                # 如果剛好是正在編輯的專案，同步更新名稱
                                if st.session_state.get('active_trip_sheet') == t.get('對應分頁'):
                                    st.session_state['active_trip_name'] = m_name
                                st.rerun()
            st.divider()
else:
    st.info("目前沒有旅程紀錄，請從上方建立你的第一個專案！")