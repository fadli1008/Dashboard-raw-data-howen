import streamlit as st
import sqlite3
import pandas as pd
import json
import requests
import hashlib
import websocket
import threading
import time
import ssl
import urllib3
import os
from streamlit_autorefresh import st_autorefresh

# Mematikan peringatan SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# 0. KONFIGURASI HALAMAN UTAMA (Harus Paling Atas)
# ==========================================
st.set_page_config(page_title="Howen Fleet VSS", page_icon="🛰️", layout="wide")

# ==========================================
# 1. INISIALISASI SESSION STATE UNTUK LOGIN
# ==========================================
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

# Konfigurasi Akun Dummy untuk UI Login
USER_DUMMY = "admin"
PASS_DUMMY = "admin123"

# ==========================================
# 2. FUNGSI-FUNGSI BACKEND & WEBSOCKET
# ==========================================
DB_NAME = "vss_data.db"
HTTP_LOGIN_URL = "https://mdvr.mceasy.com/vss/user/apiLogin.action"
HTTP_FIND_ALL_URL = "https://mdvr.mceasy.com/vss/vehicle/findAll.action"
WS_URL = "ws://mdvr.mceasy.com:36300/ws"

USERNAME = "admin"
RAW_PASSWORD = "Fadli080597#" # Jangan lupa isi kembali password API aslimu
SESSION_FILE = "vss_session.json"
TARGET_FLEET_ID = "" 

session_token = ""
session_pid = ""
target_devices = []  

def init_db():
    try:
        conn = sqlite3.connect(DB_NAME)
        # Mengaktifkan WAL mode agar SQLite tidak terkunci saat read/write bersamaan
        conn.execute('PRAGMA journal_mode=WAL;') 
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS realtime_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                device_id TEXT,
                action_type TEXT,
                payload_data TEXT
            )
        ''')
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DB] Gagal inisialisasi database: {e}")

def save_to_db(device_id, action_type, payload):
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        cursor = conn.cursor()
        payload_json = json.dumps(payload)
        cursor.execute('''
            INSERT INTO realtime_data (device_id, action_type, payload_data)
            VALUES (?, ?, ?)
        ''', (str(device_id), str(action_type), payload_json))
        conn.commit()
        conn.close()
    except Exception as e:
        pass 

def get_total_devices_global():
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(DISTINCT device_id) FROM realtime_data")
        total = cursor.fetchone()[0]
        conn.close()
        return total
    except:
        return 0

def get_md5_password(password):
    return hashlib.md5(password.encode()).hexdigest()

def save_session_to_file(token, pid):
    try:
        with open(SESSION_FILE, 'w') as f:
            json.dump({"token": token, "pid": pid}, f)
    except:
        pass

def load_session_from_file():
    global session_token, session_pid
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, 'r') as f:
                data = json.load(f)
                session_token = data.get("token", "")
                session_pid = data.get("pid", "")
            if session_token and session_pid:
                return True
        except:
            pass
    return False

def http_login():
    global session_token, session_pid
    payload = {"username": USERNAME, "password": get_md5_password(RAW_PASSWORD)}
    try:
        response = requests.post(HTTP_LOGIN_URL, json=payload, verify=False) 
        result = response.json()
        if result.get("status") == 10000:
            data = result.get("data", {})
            session_token = data.get("token")
            session_pid = data.get("pid")
            save_session_to_file(session_token, session_pid)
            return True
        else:
            if load_session_from_file(): return True
            return False
    except:
        if load_session_from_file(): return True
        return False

def get_devices_by_fleet():
    global target_devices
    if not TARGET_FLEET_ID: return True
    payload = {"token": session_token, "fleetid": TARGET_FLEET_ID, "pageNum": 1, "pageCount": -1}
    try:
        response = requests.post(HTTP_FIND_ALL_URL, json=payload, verify=False)
        result = response.json()
        if result.get("status") == 10000:
            data_list = result.get("data", {}).get("dataList", [])
            target_devices = [str(device.get("deviceno")) for device in data_list]
            print(f"[API] Berhasil menarik {len(target_devices)} device target dari Fleet ID.") 
            return True
        return False
    except:
        return False

def heartbeat(ws):
    while ws.keep_running:
        time.sleep(60)
        ws.send(json.dumps({"action": "80009", "payload": {"username": USERNAME, "token": session_token}}))

def on_message(ws, message):
    try:
        data = json.loads(message)
        action = str(data.get("action"))
        payload_data = data.get("payload", {})
        
        device_id = ""
        if isinstance(payload_data, dict):
            # Validasi format key device id dari Howen
            device_id = str(payload_data.get("deviceID", payload_data.get("deviceno", payload_data.get("deviceNo", ""))))
            
        if target_devices and device_id and device_id not in target_devices:
            return 

        if action in ["80003", "80004", "80005"] and device_id:
            save_to_db(device_id, action, payload_data)
    except:
        pass

def on_error(ws, error): pass
def on_close(ws, close_status_code, close_msg): pass
def on_open(ws):
    ws.send(json.dumps({"action": "80000", "payload": {"username": USERNAME, "pid": session_pid, "token": session_token}}))
    time.sleep(1) 
    ws.send(json.dumps({"action": "80001", "payload": ""}))
    threading.Thread(target=heartbeat, args=(ws,), daemon=True).start()

@st.cache_resource
def start_background_worker():
    init_db()
    if http_login():
        get_devices_by_fleet()
        def run_ws():
            ws = websocket.WebSocketApp(WS_URL, on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close)
            ws.run_forever()
        thread = threading.Thread(target=run_ws, daemon=True)
        thread.start()
        return True
    return False

@st.cache_data(ttl=3) 
def load_data():
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10) 
        df = pd.read_sql_query("SELECT * FROM realtime_data ORDER BY timestamp DESC LIMIT 1000", conn)
        conn.close()
        return df
    except Exception as e:
        return pd.DataFrame()


# ==========================================
# 3. KONTROL TAMPILAN BERDASARKAN STATUS LOGIN
# ==========================================

if not st.session_state["logged_in"]:
    st.markdown("<h1 style='text-align: center;'>🔒 Dashboard Raw Data Howen</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center;'>Silakan login untuk mengakses dashboard.</p>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        with st.form("form_login"):
            input_user = st.text_input("Username")
            input_pass = st.text_input("Password", type="password")
            submit_btn = st.form_submit_button("Masuk", use_container_width=True)
            
            if submit_btn:
                if input_user == USER_DUMMY and input_pass == PASS_DUMMY:
                    st.session_state["logged_in"] = True
                    st.rerun() 
                else:
                    st.error("❌ Username atau Password salah!")

else:
    is_connected = start_background_worker()

    st.markdown("""
        <h1 style='text-align: center; color: #1E88E5;'>🛰️ Dashboard Pemantauan Fleet Howen</h1>
        <p style='text-align: center; color: gray;'>MEP-PROD Live Real-Time Data (WS Bypass)</p>
        <hr>
    """, unsafe_allow_html=True)

    if not is_connected:
        st.error("⚠️ Gagal melakukan autentikasi API atau WebSocket. Cek koneksi atau kredensial.")

    df = load_data()

    # --- SIDEBAR KONTROL & LOGOUT ---
    with st.sidebar:
        st.image("https://cdn-icons-png.flaticon.com/512/854/854878.png", width=80) 
        st.title("🎛️ Panel Kontrol")
        
        # --- FITUR BARU: AUTO REFRESH ---
        st.markdown("### ⏱️ Pengaturan Live Update")
        auto_refresh = st.checkbox("Aktifkan Auto-Refresh", value=True, help="Centang untuk refresh data otomatis")
        
        if auto_refresh:
            refresh_interval = st.slider("Interval Refresh (Detik)", min_value=2, max_value=60, value=5)
            # st_autorefresh membutuhkan input dalam milidetik (detik * 1000)
            st_autorefresh(interval=refresh_interval * 1000, key="data_refresher")
        else:
            st.info("Auto-Refresh nonaktif. Tekan tombol di bawah untuk refresh manual.")

        st.markdown("### 🔍 Filter Pencarian")
        if not df.empty:
            # Pembersihan data dari desimal/float dan spasi
            df['device_id'] = df['device_id'].astype(str).str.strip().str.replace('.0', '', regex=False)
            df['action_type'] = df['action_type'].astype(str).str.strip().str.replace('.0', '', regex=False)

            # Sorting list dropdown agar rapi
            device_list = ["Semua"] + sorted(df['device_id'].unique().tolist())
            selected_device = st.selectbox("Pilih Device ID:", device_list, key="filter_device")
            
            action_list = ["Semua", "80003 (GPS/Status)", "80004 (Alarm)", "80005 (Online/Offline)"]
            selected_action = st.selectbox("Pilih Tipe Event:", action_list, key="filter_action")
            
            st.markdown("---")
            # Tombol refresh manual tetap dipertahankan sebagai cadangan
            if st.button("🔄 Segarkan Manual", use_container_width=True):
                st.rerun()
        else:
            st.warning("Menunggu data masuk...")
            if st.button("🔄 Cek Data", use_container_width=True):
                st.rerun()

        st.markdown("<br><br>", unsafe_allow_html=True)
        if st.button("🚪 Keluar (Logout)", type="primary", use_container_width=True):
            st.session_state["logged_in"] = False
            st.rerun()

    # --- KONTEN UTAMA DASHBOARD ---
    if not df.empty:
        filtered_df = df.copy()
        
        # Terapkan filter berdasarkan input pengguna
        if selected_device != "Semua":
            filtered_df = filtered_df[filtered_df['device_id'] == selected_device]
        if selected_action != "Semua":
            action_code = selected_action.split(" ")[0]
            filtered_df = filtered_df[filtered_df['action_type'] == action_code]

        col1, col2, col3, col4 = st.columns(4)
        
        total_devices_all = get_total_devices_global() 
        total_events = len(filtered_df)
        
        col1.metric("📡 Total Device Aktif", f"{total_devices_all} Unit")
        col2.metric("💾 Data Top 1000 DB", f"{len(df)} Baris")
        col3.metric("📊 Data Sesuai Filter", f"{total_events} Baris")
        col4.metric("🟢 Status Koneksi", "Online", delta="Stabil", delta_color="normal")

        st.write("") 

        tab1, tab2, tab3 = st.tabs(["📈 Ringkasan Visual", "📋 Tabel Data Lengkap", "🛠️ Inspeksi JSON Payload"])

        with tab1:
            st.subheader("Distribusi Event per Device (Top 1000)")
            if not filtered_df.empty:
                chart_data = filtered_df['device_id'].value_counts().reset_index()
                chart_data.columns = ['Device ID', 'Jumlah Event']
                st.bar_chart(chart_data, x="Device ID", y="Jumlah Event", color="#1E88E5", use_container_width=True)
            else:
                st.info("Tidak ada data untuk ditampilkan pada grafik sesuai filter.")

        with tab2:
            st.subheader("Tabel Rekaman Real-Time")
            st.dataframe(
                filtered_df, 
                use_container_width=True, 
                hide_index=True,
                column_config={
                    "id": st.column_config.NumberColumn("ID DB", format="%d"),
                    "timestamp": st.column_config.DatetimeColumn("Waktu Terekam", format="DD MMM YYYY, HH:mm:ss"),
                    "device_id": "ID Perangkat",
                    "action_type": "Kode Aksi",
                    "payload_data": "Data Payload Mentah"
                }
            )

        with tab3:
            st.subheader("Bongkar Data Payload (Detail JSON)")
            col_input, col_space = st.columns([1, 3])
            with col_input:
                row_id = st.number_input("Masukkan ID Baris (ID DB):", min_value=1, step=1)
            
            if row_id:
                detail_data = df[df['id'].astype(str) == str(row_id)]
                if not detail_data.empty:
                    st.success(f"Data ditemukan (Device: {detail_data.iloc[0]['device_id']})")
                    raw_payload = detail_data.iloc[0]['payload_data']
                    try:
                        st.json(json.loads(raw_payload), expanded=True)
                    except:
                        st.code(raw_payload, language="text")
                else:
                    st.error(f"❌ Data dengan ID {row_id} tidak ditemukan dalam 1000 data terakhir.")
    else:
        st.info("⏳ Menunggu data masuk dari WebSocket...")