import requests
import hashlib
import json
import websocket
import threading
import time
import ssl
import urllib3
import os
import sqlite3

# Mematikan peringatan SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DB_NAME = "vss_data.db"
HTTP_LOGIN_URL = "https://mdvr.mceasy.com/vss/user/apiLogin.action"
HTTP_FIND_ALL_URL = "https://mdvr.mceasy.com/vss/vehicle/findAll.action"
WS_URL = "ws://mdvr.mceasy.com:36300/ws" # Opsi 3 (Bypass)

USERNAME = "MEP-PROD"
RAW_PASSWORD = "Vss-Mep-2025!"
SESSION_FILE = "vss_session.json"
TARGET_FLEET_ID = "" 

session_token = ""
session_pid = ""
target_devices = []  

def init_db():
    try:
        conn = sqlite3.connect(DB_NAME)
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
        print(f"[DB] Database '{DB_NAME}' siap digunakan.")
    except Exception as e:
        print(f"[DB] Gagal inisialisasi database: {e}")

def save_to_db(device_id, action_type, payload):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        payload_json = json.dumps(payload)
        cursor.execute('''
            INSERT INTO realtime_data (device_id, action_type, payload_data)
            VALUES (?, ?, ?)
        ''', (str(device_id), str(action_type), payload_json))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DB] Gagal menyimpan baris data: {e}")

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
    print("[HTTP] Mencoba proses login API...")
    try:
        response = requests.post(HTTP_LOGIN_URL, json=payload, verify=False) 
        result = response.json()
        if result.get("status") == 10000:
            data = result.get("data", {})
            session_token = data.get("token")
            session_pid = data.get("pid")
            save_session_to_file(session_token, session_pid)
            print("[HTTP] Login Berhasil!")
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
            device_id = str(payload_data.get("deviceID", payload_data.get("deviceno", "")))
            
        if target_devices and device_id and device_id not in target_devices:
            return 

        # Simpan ke DB
        if action in ["80003", "80004", "80005"] and device_id:
            save_to_db(device_id, action, payload_data)

        # Log Terminal
        if action == "80003": print(f"[DATA] GPS/Status ({device_id}) -> DB.")
        elif action == "80004": print(f"[DATA] Alarm/Event ({device_id}) -> DB.")
        elif action == "80005": print(f"[DATA] Status ({device_id}) -> DB.")
            
    except:
        pass

def on_error(ws, error): print(f"[WS] Error: {error}")
def on_close(ws, close_status_code, close_msg): print("[WS] Ditutup.")
def on_open(ws):
    print(f"[WS] Terkoneksi ke: {WS_URL}")
    ws.send(json.dumps({"action": "80000", "payload": {"username": USERNAME, "pid": session_pid, "token": session_token}}))
    time.sleep(1) 
    ws.send(json.dumps({"action": "80001", "payload": ""}))
    threading.Thread(target=heartbeat, args=(ws,), daemon=True).start()

if __name__ == "__main__":
    init_db()
    if http_login():
        get_devices_by_fleet()
        ws = websocket.WebSocketApp(WS_URL, on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close)
        ws.run_forever()