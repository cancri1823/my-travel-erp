import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection

st.set_page_config(page_title="旅程花費看板", page_icon="💰", layout="wide")

# --- 0. 旅程動態對接邏輯 ---
target_sheet = st.session_state.get('active_trip_sheet', 'Exp_Yunnan2026')
target_name = st.session_state.get('active_trip_name', '2026 雲南探索 (預設)')

with st.sidebar:
    st.header("🎯 核心戰情室")
    st.success(f"目前檢視旅程：\n\n**{target_name}**")
    st.caption(f"數據來源分頁：`{target_sheet}`")
    st.divider()
    # 預算設定 (存於 session_state)
    budget = st.number_input("💸 設定此旅程總預算 (TWD)", min_value=0, value=st.session_state.get('travel_budget', 50000))
    st.session_state['travel_budget'] = budget

# --- 1. 雲端連線與資料讀取 ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error(f"連線失敗: {e}"); st.stop()

EXPECTED_COLUMNS = ["日期", "分類", "項目", "金額", "付款方式", "支付人", "來源"]

def fetch_data():
    try:
        df = conn.read(worksheet=target_sheet, ttl=0)
        if df.empty: return pd.DataFrame(columns=EXPECTED_COLUMNS)
        
        # 確保金額是數字格式
        df["金額"] = pd.to_numeric(df["金額"], errors='coerce').fillna(0)
        
        # 🔴 核心修正：資料清洗，將 AI 產生的「門票娛樂」統一合併為「門票/娛樂」
        if "分類" in df.columns:
            df["分類"] = df["分類"].replace({"門票娛樂": "門票/娛樂", "門票": "門票/娛樂"})
            
        return df
    except:
        return pd.DataFrame(columns=EXPECTED_COLUMNS)

def save_to_cloud(new_row_df):
    try:
        existing_df = fetch_data()
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
        st.error(f"❌ 寫入失敗: {e}"); return False

# 雲端更新與刪除函數
def update_in_cloud(row_index, updated_dict):
    try:
        df = conn.read(worksheet=target_sheet, ttl=0) # 讀取最原始資料進行更新
        for key, value in updated_dict.items():
            df.at[row_index, key] = value
        conn.update(worksheet=target_sheet, data=df[EXPECTED_COLUMNS])
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"❌ 雲端更新失敗: {e}"); return False

def delete_from_cloud(row_index):
    try:
        df = conn.read(worksheet=target_sheet, ttl=0)
        df = df.drop(index=row_index)
        conn.update(worksheet=target_sheet, data=df[EXPECTED_COLUMNS])
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"❌ 雲端刪除失敗: {e}"); return False

# --- 2. 數據計算 ---
df_all = fetch_data()
total_spent = int(df_all["金額"].sum()) if not df_all.empty else 0
remaining = budget - total_spent
progress = min(total_spent / budget, 1.0) if budget > 0 else 0

# --- 職人風格 CSS ---
st.markdown("""
    <style>
    h1 { border-bottom: 2px solid #b87333; padding-bottom: 10px; }
    .stMetric { background-color: #1e1e1e; padding: 15px; border-radius: 10px; border-left: 5px solid #b87333; }
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
col_form, col_list = st.columns([1, 1.8])

with col_form:
    st.subheader("➕ 新增手動支出")
    with st.form("manual_exp_form", clear_on_submit=True):
        e_date = st.date_input("日期")
        e_cat = st.selectbox("分類", ["餐飲", "交通", "購物", "門票/娛樂", "住宿", "其他"])
        e_item = st.text_input("項目名稱", placeholder="例如：藥妝店採買")
        
        # 自訂幣別輸入
        c_amt, c_curr, c_cust = st.columns([1.5, 1.2, 1.3])
        e_amt = c_amt.number_input("金額", min_value=0.0)
        e_curr_sel = c_curr.selectbox("幣別", ["TWD", "USD", "EUR", "JPY", "CNY", "自行輸入"])
        e_curr_cust = c_cust.text_input("自訂幣別", placeholder="如: THB")
        
        # 支付人與付款方式
        c_payer, c_pay_m = st.columns(2)
        e_payer = c_payer.text_input("支付人", value="自己")
        e_pay_m = c_pay_m.selectbox("付款方式", ["現金", "信用卡", "電子支付", "公費扣款"])
        
        if st.form_submit_button("🚀 記錄支出至雲端", type="primary", use_container_width=True):
            if e_item and e_amt > 0:
                final_curr = e_curr_cust if e_curr_sel == "自行輸入" and e_curr_cust else e_curr_sel
                rates = {"JPY": st.session_state.get('jpy_rate', 0.215), "CNY": 4.5, "USD": 32.5, "EUR": 35.0, "TWD": 1.0}
                rate = rates.get(final_curr, 1.0)
                
                twd_val = int(e_amt * rate)
                
                new_row = pd.DataFrame([{
                    "日期": str(e_date),
                    "分類": e_cat,
                    "項目": f"{e_item} ({final_curr} {e_amt})",
                    "金額": twd_val,
                    "付款方式": e_pay_m,
                    "支付人": e_payer,
                    "來源": "手動輸入"
                }])
                
                with st.spinner("同步中..."):
                    if save_to_cloud(new_row):
                        st.success("✅ 已同步至雲端帳本！")
                        st.rerun()
            else:
                st.error("請完整填寫項目與金額")

with col_list:
    st.subheader("📜 總花費明細 (雲端即時連動)")
    if not df_all.empty:
        # 依日期降序排列
        df_display = df_all.sort_values(by="日期", ascending=False)
        
        # 可展開編輯的列表
        for idx, row in df_display.iterrows():
            with st.expander(f"🧾 {row.get('日期', '')} | [{row.get('分類', '其他')}] {row.get('項目', '')} - NT$ {row.get('金額', 0):,} ({row.get('支付人', '未知')})"):
                
                try: def_date = pd.to_datetime(row.get('日期')).date()
                except: def_date = pd.Timestamp.now().date()
                new_date = st.date_input("修改日期", value=def_date, key=f"ex_d_{idx}")
                
                cat_opts = ["餐飲", "交通", "購物", "門票/娛樂", "住宿", "其他"]
                cat_val = row.get('分類', '其他')
                cat_idx = cat_opts.index(cat_val) if cat_val in cat_opts else 5
                new_cat = st.selectbox("修改分類", cat_opts, index=cat_idx, key=f"ex_c_{idx}")
                
                new_item = st.text_input("修改項目明細", value=row.get('項目', ''), key=f"ex_i_{idx}")
                
                c1, c2, c3 = st.columns([1, 1, 1])
                try: def_amt = float(row.get('金額', 0))
                except: def_amt = 0.0
                new_amt = c1.number_input("修改金額 (TWD)", value=def_amt, key=f"ex_a_{idx}")
                
                pm_opts = ["現金", "信用卡", "電子支付", "公費扣款"]
                pm_val = row.get('付款方式', '現金')
                pm_idx = pm_opts.index(pm_val) if pm_val in pm_opts else 0
                new_pay_m = c2.selectbox("修改付款方式", pm_opts, index=pm_idx, key=f"ex_pm_{idx}")
                
                new_payer = c3.text_input("修改支付人", value=row.get('支付人', '自己'), key=f"ex_py_{idx}")
                
                st.write("")
                btn_col1, btn_col2 = st.columns(2)
                if btn_col1.button("💾 儲存修改", key=f"ex_sv_{idx}"):
                    updated_data = {
                        "日期": str(new_date),
                        "分類": new_cat,
                        "項目": new_item,
                        "金額": int(new_amt),
                        "付款方式": new_pay_m,
                        "支付人": new_payer
                    }
                    with st.spinner("更新雲端資料中..."):
                        if update_in_cloud(idx, updated_data):
                            st.success("✅ 雲端資料已更新！")
                            st.rerun()
                            
                if btn_col2.button("🗑️ 刪除", key=f"ex_del_{idx}"):
                    with st.spinner("刪除雲端資料中..."):
                        if delete_from_cloud(idx):
                            st.success("✅ 該筆紀錄已從 Google Sheets 刪除！")
                            st.rerun()
        
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