import streamlit as st
import sqlite3
import pandas as pd
import json

# Konfigurasi Halaman Dashboard
st.set_page_config(page_title="Dashboard VSS Howen", layout="wide")
st.title("📡 Dashboard Pemantauan Fleet (MEP-PROD)")

# Fungsi menarik data dari SQLite
@st.cache_data(ttl=3) # Data di-refresh setiap 3 detik
def load_data():
    try:
        conn = sqlite3.connect("vss_data.db")
        df = pd.read_sql_query("SELECT * FROM realtime_data ORDER BY timestamp DESC LIMIT 500", conn) # Ambil 500 data terbaru agar ringan
        conn.close()
        return df
    except Exception as e:
        return pd.DataFrame()

df = load_data()

if not df.empty:
    st.sidebar.header("🔍 Filter Data")
    
    device_list = ["Semua"] + df['device_id'].dropna().unique().tolist()
    selected_device = st.sidebar.selectbox("Pilih Device ID:", device_list)
    
    action_list = ["Semua", "80003 (GPS/Status)", "80004 (Alarm)", "80005 (Online/Offline)"]
    selected_action = st.sidebar.selectbox("Pilih Tipe Event:", action_list)
    
    filtered_df = df.copy()
    if selected_device != "Semua":
        filtered_df = filtered_df[filtered_df['device_id'] == selected_device]
        
    if selected_action != "Semua":
        action_code = selected_action.split(" ")[0]
        filtered_df = filtered_df[filtered_df['action_type'] == action_code]
        
    col1, col2 = st.columns(2)
    with col1: st.metric("Total Data Terekam (Limit 500)", len(df))
    with col2: st.metric("Data Ditampilkan", len(filtered_df))

    # Menampilkan tabel interaktif (Error width sudah diperbaiki)
    st.dataframe(filtered_df, width=1500, hide_index=True)
    
    if st.button("🔄 Refresh Data Manual"):
        st.rerun()
        
    st.write("---")
    st.subheader("Bongkar Data Payload (JSON)")
    row_id = st.number_input("Masukkan ID Baris (kolom 'id' paling kiri):", min_value=1, step=1)
    
    if row_id:
        detail_data = df[df['id'] == row_id]
        if not detail_data.empty:
            try:
                st.json(json.loads(detail_data.iloc[0]['payload_data']))
            except:
                st.write(detail_data.iloc[0]['payload_data'])
else:
    st.warning("Belum ada data. Pastikan script main_ws.py sedang berjalan!")