import streamlit as st
from streamlit_gsheets import GSheetsConnection

st.set_page_config(page_title="雲端連線測試", page_icon="⚡")

st.title("⚡ 雲端資料庫通電測試")

# 建立連線
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
    st.success("✅ 成功讀取 secrets.toml 金鑰設定！")
    
    if st.button("讀取 Google Sheets 資料"):
        with st.spinner("正在連線至雲端..."):
            # 讀取剛才建立的 Expenses 工作表
            # ttl=0 代表不使用快取，強制抓取最新資料
            df = conn.read(ttl=0) 
            
            st.success("🎉 雲端連線大成功！成功讀取到以下資料：")
            st.dataframe(df)
            
except Exception as e:
    st.error("❌ 連線失敗，請檢查金鑰或權限設定。")
    st.code(str(e))