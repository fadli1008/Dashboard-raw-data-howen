import requests
import hashlib
import json
import websocket
import threading
import time
import ssl
import urllib3
import os

# ==========================================
# PENGATURAN SISTEM
# ==========================================
# Mematikan peringatan SSL agar terminal tetap bersih
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# KONFIGURASI ENDPOINT & KREDENSIAL
# ==========================================
HTTP_LOGIN_URL = "https://mdvr.mceasy.com/vss/user/apiLogin.action"
HTTP_FIND_ALL_URL = "https://mdvr.mceasy.com/vss/vehicle/findAll.action"

# Karena Opsi 1 sebelumnya 404 Not Found, kita gunakan Opsi 2 sebagai default sekarang:
WS_URL = "ws://mdvr.mceasy.com:36300/ws"
# Jika Opsi 2 masih gagal, aktifkan baris di bawah ini untuk Opsi 3 (bypass port):
# WS_URL = "ws://mdvr.mceasy.com:36300/ws" 

USERNAME = "MEP-PROD"
RAW_PASSWORD = "Vss-Mep-2025!"
SESSION_FILE = "vss_session.json"

# ==========================================
# KONFIGURASI FILTER FLEET
# ==========================================
# MASUKKAN FLEET ID ANDA DI SINI (Contoh: "8a8a8c1f7a...")
# Jika dikosongkan (""), program otomatis akan menampilkan SEMUA perangkat.
TARGET_FLEET_ID = "" 

# Variabel Global
session_token = ""
session_pid = ""
target_devices = []  # List untuk menyimpan ID perangkat dari fleet target

def get_md5_password(password):
    return hashlib.md5(password.encode()).hexdigest()

def save_session_to_file(token, pid):
    try:
        with open(SESSION_FILE, 'w') as f:
            json.dump({"token": token, "pid": pid}, f)
        print(f"[CACHE] Sesi berhasil disimpan ke file '{SESSION_FILE}'.")
    except Exception as e:
        print(f"[CACHE] Gagal menyimpan sesi: {e}")

def load_session_from_file():
    global session_token, session_pid
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, 'r') as f:
                data = json.load(f)
                session_token = data.get("token", "")
                session_pid = data.get("pid", "")
            if session_token and session_pid:
                print(f"[CACHE] Berhasil memuat sesi lama dari file.")
                return True
        except Exception:
            pass
    return False

def http_login():
    """Proses HTTP Login dengan Fallback ke File Cache"""
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
            print(f"[HTTP] Login Berhasil!\nToken: {session_token}\nPID: {session_pid}\n")
            save_session_to_file(session_token, session_pid)
            return True
        else:
            print(f"[HTTP] Login Gagal: {result.get('msg')}")
            if load_session_from_file():
                return True
            return False
    except Exception as e:
        print(f"[HTTP] Terjadi kesalahan jaringan: {e}")
        if load_session_from_file():
            return True
        return False

def get_devices_by_fleet():
    """Mengambil daftar perangkat berdasarkan Fleet ID"""
    global target_devices
    
    if not TARGET_FLEET_ID:
        print("[INFO] TARGET_FLEET_ID kosong. Program akan mendengarkan SEMUA armada/perangkat.")
        return True
        
    payload = {
        "token": session_token,
        "fleetid": TARGET_FLEET_ID,
        "pageNum": 1,
        "pageCount": -1 # Tarik semua tanpa batasan halaman
    }
    print(f"[HTTP] Menarik daftar perangkat untuk Fleet ID: {TARGET_FLEET_ID}...")
    
    try:
        response = requests.post(HTTP_FIND_ALL_URL, json=payload, verify=False)
        result = response.json()
        if result.get("status") == 10000:
            data_list = result.get("data", {}).get("dataList", [])
            # Disimpan sebagai list string agar mudah dicocokkan saat data masuk
            target_devices = [str(device.get("deviceno")) for device in data_list]
            print(f"[HTTP] Berhasil! Ditemukan {len(target_devices)} perangkat di Fleet ini.\n")
            return True
        else:
            print(f"[HTTP] Gagal mengambil daftar fleet: {result.get('msg')}")
            return False
    except Exception as e:
        print(f"[HTTP] Error saat menarik data fleet: {e}")
        return False

def heartbeat(ws):
    """Menjaga agar koneksi WebSocket tidak mati (Kirim Action 80009 tiap menit)"""
    while ws.keep_running:
        time.sleep(60)
        heartbeat_payload = {
            "action": "80009",
            "payload": {"username": USERNAME, "token": session_token}
        }
        try:
            ws.send(json.dumps(heartbeat_payload))
            # print("[WS] Heartbeat terkirim.") # Bisa di-uncomment jika ingin melihat log heartbeat
        except:
            break

def on_message(ws, message):
    """Menerima dan Menyaring Data WebSocket"""
    try:
        data = json.loads(message)
        action = str(data.get("action"))
        payload_data = data.get("payload", {})
        
        # ----------------------------------------------------
        # PROSES FILTERING (CLIENT-SIDE)
        # ----------------------------------------------------
        # Jika target_devices memiliki isi (Fleet ID di-set)
        if target_devices and isinstance(payload_data, dict):
            # Coba ambil ID perangkat (Howen kadang memakai 'deviceID' atau 'deviceno')
            device_id = str(payload_data.get("deviceID", payload_data.get("deviceno", "")))
            
            # Jika ada ID perangkat di payload, tapi TIDAK ADA di list armada kita, maka HENTIKAN (Abaikan pesan)
            if device_id and device_id not in target_devices:
                return 
        # ----------------------------------------------------

        # Tampilkan data yang lolos filter
        if action == "80000":
            print("[WS] Respons Login WS:", data)
        elif action == "80003":
            print(f"\n[DATA] GPS/Status Perangkat: {data}")
        elif action == "80004":
            print(f"\n[DATA] Alarm/Event: {data}")
        elif action == "80005":
            print(f"\n[DATA] Online/Offline Status: {data}")
        elif action == "80009":
            pass # Abaikan log heartbeat agar tidak spam
        else:
            print(f"\n[DATA] Pesan Lainnya (Action {action}):", data)
            
    except Exception as e:
        print(f"[WS] Gagal memproses pesan | Error: {e}")

def on_error(ws, error):
    print(f"[WS] Error: {error}")

def on_close(ws, close_status_code, close_msg):
    print(f"[WS] Koneksi WebSocket Ditutup. Code: {close_status_code}, Msg: {close_msg}")

def on_open(ws):
    print(f"[WS] Terkoneksi ke WebSocket Server: {WS_URL}")
    
    # 1. Login WebSocket
    ws_login_payload = {
        "action": "80000",
        "payload": {"username": USERNAME, "pid": session_pid, "token": session_token}
    }
    ws.send(json.dumps(ws_login_payload))
    print("[WS] Permintaan otentikasi WS (Action 80000) terkirim.")
    
    # 2. Subscribe Data
    time.sleep(1) 
    ws_subscribe_payload = {"action": "80001", "payload": ""}
    ws.send(json.dumps(ws_subscribe_payload))
    print("[WS] Permintaan berlangganan data (Action 80001) terkirim.")
    
    # 3. Jalankan Heartbeat
    threading.Thread(target=heartbeat, args=(ws,), daemon=True).start()

if __name__ == "__main__":
    # Langkah 1: HTTP Login / Load Cache
    if http_login():
        
        # Langkah 2: Tarik daftar fleet (Filter otomatis berjalan jika TARGET_FLEET_ID diisi)
        get_devices_by_fleet()
        
        # Langkah 3: Eksekusi WebSocket
        print(f"[WS] Membuka koneksi WebSocket ke {WS_URL} ...")
        ws = websocket.WebSocketApp(
            WS_URL,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )
        ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})