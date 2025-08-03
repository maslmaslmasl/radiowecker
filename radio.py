#!/usr/bin/env python3
import subprocess
import threading
import json
import re
import time
import sys
import os
import signal
import socket
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import logging

# --- Konfiguration ---

STREAM_INFO_FILE = "/tmp/current_stream.json"
CONTROL_SOCKET = "/tmp/radio_control.sock"
PID_FILE = "/tmp/radio.pid"

# API-Konfiguration
API_PORT = 8080
API_HOST = "0.0.0.0"  # Auf allen Interfaces lauschen

# GPIO Pins
PIN_DT = 23
PIN_CLK = 24
PIN_SW = 22
PIN_ALARM = 27

# Playlist-Datei (m3u)
PLAYLIST_PATH = "/home/masl/radioliste.m3u"

# Lautstärke-Sprünge in Prozent (mpg123 nutzt 0..100)
VOLUME_STEP = 5

# --- Globale Variablen ---

encoder = None
encoder_button = None
alarm_button = None

playback_state = True
button_pressed = False
double_click_flag = False
last_press_time = 0

current_index = 0
mpg123_proc = None
current_volume = 50  # Start-Lautstärke 50%
current_info = {
    "stream_url": "",
    "title": "",
    "timestamp": ""
}

control_socket = None
api_server = None
running = True

# Logging konfigurieren
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- API Handler ---

class RadioAPIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Reduziere HTTP-Logging
        pass
    
    def do_GET(self):
        """Behandelt GET-Requests"""
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        params = parse_qs(parsed_url.query)
        
        try:
            if path == "/api/status":
                self.handle_status()
            elif path == "/api/info":
                self.handle_info()
            elif path == "/api/stations":
                self.handle_stations()
            elif path == "/api/play":
                self.handle_play()
            elif path == "/api/stop":
                self.handle_stop()
            elif path == "/api/pause":
                self.handle_pause()
            elif path == "/api/next":
                self.handle_next()
            elif path == "/api/prev":
                self.handle_prev()
            elif path == "/api/volume":
                volume = params.get('level', [None])[0]
                self.handle_volume(volume)
            elif path == "/api/station":
                station = params.get('id', [None])[0]
                self.handle_station(station)
            elif path == "/" or path == "/api":
                self.handle_help()
            else:
                self.send_error(404, "Endpoint not found")
        except Exception as e:
            logging.error(f"API Error: {e}")
            self.send_json_response({"error": str(e)}, 500)
    
    def do_POST(self):
        """Behandelt POST-Requests"""
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            
            if path == "/api/volume":
                data = json.loads(post_data) if post_data else {}
                volume = data.get('level')
                self.handle_volume(volume)
            elif path == "/api/station":
                data = json.loads(post_data) if post_data else {}
                station = data.get('id')
                self.handle_station(station)
            else:
                self.send_error(404, "Endpoint not found")
        except Exception as e:
            logging.error(f"API POST Error: {e}")
            self.send_json_response({"error": str(e)}, 500)
    
    def send_json_response(self, data, status_code=200):
        """Sendet JSON-Response"""
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())
    
    def do_OPTIONS(self):
        """Behandelt CORS Preflight-Requests"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    def handle_status(self):
        """GET /api/status - Radio-Status"""
        playlist = read_playlist()
        status = {
            "status": "playing" if playback_state else "stopped",
            "current_station": current_index + 1,
            "total_stations": len(playlist),
            "volume": current_volume,
            "station_url": current_info.get("stream_url", ""),
            "station_name": current_info.get("station_name", ""),
            "title": current_info.get("title", ""),
            "timestamp": datetime.now().isoformat()
        }
        self.send_json_response(status)
    
    def handle_info(self):
        """GET /api/info - Detaillierte Stream-Info"""
        self.send_json_response(current_info)
    
    def handle_stations(self):
        """GET /api/stations - Liste aller Stationen"""
        playlist = read_playlist()
        stations = []
        for i, url in enumerate(playlist):
            stations.append({
                "id": i + 1,
                "url": url,
                "active": i == current_index
            })
        self.send_json_response({"stations": stations})
    
    def handle_play(self):
        """GET /api/play - Wiedergabe starten"""
        result = process_command("play")
        self.send_json_response({"message": result})
    
    def handle_stop(self):
        """GET /api/stop - Wiedergabe stoppen"""
        result = process_command("stop")
        self.send_json_response({"message": result})
    
    def handle_pause(self):
        """GET /api/pause - Wiedergabe pausieren/fortsetzen"""
        result = process_command("pause")
        self.send_json_response({"message": result})
    
    def handle_next(self):
        """GET /api/next - Nächste Station"""
        result = process_command("next")
        self.send_json_response({"message": result})
    
    def handle_prev(self):
        """GET /api/prev - Vorherige Station"""
        result = process_command("prev")
        self.send_json_response({"message": result})
    
    def handle_volume(self, volume):
        """GET/POST /api/volume - Lautstärke setzen"""
        if volume is not None:
            result = process_command(f"volume {volume}")
            self.send_json_response({"message": result, "volume": current_volume})
        else:
            self.send_json_response({"volume": current_volume})
    
    def handle_station(self, station):
        """GET/POST /api/station - Station wechseln"""
        if station is not None:
            result = process_command(f"station {station}")
            self.send_json_response({"message": result, "current_station": current_index + 1})
        else:
            self.send_json_response({"current_station": current_index + 1})
    
    def handle_help(self):
        """GET / oder /api - API-Hilfe"""
        help_text = {
            "name": "Radio API",
            "version": "1.0",
            "endpoints": {
                "GET /api/status": "Radio-Status abrufen",
                "GET /api/info": "Detaillierte Stream-Informationen",
                "GET /api/stations": "Liste aller verfügbaren Stationen",
                "GET /api/play": "Wiedergabe starten",
                "GET /api/stop": "Wiedergabe stoppen",
                "GET /api/pause": "Wiedergabe pausieren/fortsetzen",
                "GET /api/next": "Nächste Station",
                "GET /api/prev": "Vorherige Station",
                "GET /api/volume?level=50": "Lautstärke setzen (0-100)",
                "GET /api/station?id=3": "Station wechseln (1-N)",
                "POST /api/volume": "Lautstärke setzen (JSON: {\"level\": 50})",
                "POST /api/station": "Station wechseln (JSON: {\"id\": 3})"
            },
            "examples": {
                "curl": [
                    "curl http://localhost:8080/api/status",
                    "curl http://localhost:8080/api/play",
                    "curl -X POST -H 'Content-Type: application/json' -d '{\"level\":75}' http://localhost:8080/api/volume"
                ]
            }
        }
        self.send_json_response(help_text)

def start_api_server():
    """Startet den HTTP-API-Server"""
    global api_server
    
    try:
        api_server = HTTPServer((API_HOST, API_PORT), RadioAPIHandler)
        logging.info(f"API-Server gestartet auf http://{API_HOST}:{API_PORT}")
        
        def serve_forever():
            try:
                api_server.serve_forever()
            except Exception as e:
                if running:
                    logging.error(f"API-Server Fehler: {e}")
        
        threading.Thread(target=serve_forever, daemon=True).start()
        return True
    except Exception as e:
        logging.error(f"API-Server Start fehlgeschlagen: {e}")
        return False

# --- Hilfsfunktionen ---

def create_pid_file():
    """Erstellt PID-Datei für Prozess-Management"""
    try:
        with open(PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
    except Exception as e:
        logging.error(f"PID-Datei erstellen: {e}")

def remove_pid_file():
    """Entfernt PID-Datei"""
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except Exception as e:
        logging.error(f"PID-Datei löschen: {e}")

def is_daemon_running():
    """Prüft ob der Daemon läuft"""
    if not os.path.exists(PID_FILE):
        return False
    
    try:
        with open(PID_FILE, 'r') as f:
            pid = int(f.read().strip())
        
        # Prüfe ob Prozess existiert
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        # PID existiert nicht mehr, entferne verwaiste PID-Datei
        remove_pid_file()
        return False

def send_command(command):
    """Sendet Kommando an laufenden Daemon"""
    if not is_daemon_running():
        print("[ERROR] Radio-Daemon läuft nicht. Starten Sie ihn zuerst.")
        return False
    
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(CONTROL_SOCKET)
        sock.send(command.encode())
        response = sock.recv(1024).decode()
        sock.close()
        print(response)
        return True
    except Exception as e:
        print(f"[ERROR] Kommando senden: {e}")
        return False

# --- Stream-Funktionen ---

def write_stream_info(info):
    info["timestamp"] = datetime.now().isoformat()
    try:
        with open(STREAM_INFO_FILE, "w") as f:
            json.dump(info, f, indent=2)
    except Exception as e:
        logging.error(f"Beim Schreiben der Stream-Info: {e}")

def metadata_updater():
    def update_loop():
        while running:
            write_stream_info(current_info)
            time.sleep(20)
    threading.Thread(target=update_loop, daemon=True).start()

def run_mpg123(url):
    global current_info
    current_info = {
        "stream_url": url,
        "title": "",
        "station_name": "",
        "station_url": "",
        "bitrate": "",
        "samplerate": "",
        "channels": "",
        "timestamp": ""
    }

    proc = subprocess.Popen(
        ["mpg123", "-v", url],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    def monitor_output():
        streamtitle_re = re.compile(r"StreamTitle='(.*?)'")
        icy_name_re = re.compile(r"ICY-NAME:\s*(.*)")
        icy_url_re = re.compile(r"ICY-URL:\s*(.*)")
        mpeg_info_re = re.compile(r"MPEG.*?(\d+\s*kbit/s),\s*(\d+\s*kHz)\s*(Mono|Stereo)")

        for line in proc.stdout:
            if not running:
                break
            line = line.strip()

            if match := streamtitle_re.search(line):
                current_info["title"] = match.group(1)

            elif match := icy_name_re.search(line):
                current_info["station_name"] = match.group(1)

            elif match := icy_url_re.search(line):
                current_info["station_url"] = match.group(1)

            elif match := mpeg_info_re.search(line):
                current_info["bitrate"] = match.group(1)
                current_info["samplerate"] = match.group(2)
                current_info["channels"] = match.group(3)

            write_stream_info(current_info)

    threading.Thread(target=monitor_output, daemon=True).start()
    return proc

def read_playlist():
    urls = []
    try:
        with open(PLAYLIST_PATH, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    urls.append(line)
    except Exception as e:
        logging.error(f"Playlist lesen: {e}")
    return urls

def set_volume(change):
    global current_volume
    current_volume = max(0, min(100, current_volume + change))
    try:
        subprocess.run(["amixer", "sset", "Master", f"{current_volume}%"], check=True, stdout=subprocess.DEVNULL)
        logging.info(f"Lautstärke auf {current_volume}% gesetzt")
    except Exception as e:
        logging.error(f"Lautstärke setzen: {e}")

def play_stream(index):
    global current_index, mpg123_proc

    playlist = read_playlist()
    if not playlist:
        logging.error("Playlist ist leer.")
        return

    current_index = index % len(playlist)
    url = playlist[current_index]

    if mpg123_proc:
        mpg123_proc.terminate()
        mpg123_proc.wait()

    logging.info(f"Starte Stream {current_index + 1}/{len(playlist)}: {url}")
    mpg123_proc = run_mpg123(url)

def toggle_play_pause():
    global playback_state, mpg123_proc
    if mpg123_proc is None:
        play_stream(current_index)
        playback_state = True
    else:
        if playback_state:
            mpg123_proc.terminate()
            playback_state = False
            logging.info("Wiedergabe pausiert")
        else:
            play_stream(current_index)
            playback_state = True
            logging.info("Wiedergabe gestartet")

# --- GPIO Handler ---

def init_gpio():
    """Initialisiert GPIO nur im Daemon-Modus"""
    global encoder, encoder_button, alarm_button
    
    try:
        from gpiozero import RotaryEncoder, Button
    except ImportError:
        logging.error("gpiozero nicht installiert. Installieren Sie es mit: pip3 install gpiozero")
        return False
    
    try:
        encoder = RotaryEncoder(PIN_DT, PIN_CLK, max_steps=100)
        encoder_button = Button(PIN_SW, pull_up=True, hold_time=0.2, bounce_time=0.05)
        alarm_button = Button(PIN_ALARM, pull_up=True)
    except Exception as e:
        logging.error(f"GPIO-Initialisierung fehlgeschlagen: {e}")
        logging.info("Möglicherweise wird GPIO bereits von einem anderen Prozess verwendet.")
        return False

    def on_rotate():
        global button_pressed
        if button_pressed:
            if encoder.steps > 0:
                play_stream(current_index + 1)
            elif encoder.steps < 0:
                play_stream(current_index - 1)
        else:
            if encoder.steps > 0:
                set_volume(VOLUME_STEP)
            elif encoder.steps < 0:
                set_volume(-VOLUME_STEP)
        encoder.steps = 0

    def on_button_pressed():
        global button_pressed, last_press_time, double_click_flag
        now = time.time()
        if now - last_press_time < 0.5:
            double_click_flag = True
            toggle_play_pause()
        else:
            button_pressed = True
        last_press_time = now

    def on_button_released():
        global button_pressed, double_click_flag
        if double_click_flag:
            double_click_flag = False
            return
        button_pressed = False

    def on_alarm_released():
        global playback_state
        if not playback_state:
            play_stream(current_index)
            playback_state = True

    encoder.when_rotated = on_rotate
    encoder_button.when_pressed = on_button_pressed
    encoder_button.when_released = on_button_released
    alarm_button.when_released = on_alarm_released
    
    return True

# --- Kommando-Verarbeitung ---

def process_command(command):
    """Verarbeitet empfangene Kommandos"""
    global current_volume, playback_state, running
    
    parts = command.strip().split()
    if not parts:
        return "ERROR: Leeres Kommando"
    
    cmd = parts[0].lower()
    
    if cmd == "play" or cmd == "p":
        if not playback_state:
            toggle_play_pause()
        return "OK: Wiedergabe gestartet"
    
    elif cmd == "stop" or cmd == "s":
        if playback_state:
            toggle_play_pause()
        return "OK: Wiedergabe gestoppt"
    
    elif cmd == "pause":
        toggle_play_pause()
        return f"OK: {'Pause' if not playback_state else 'Play'}"
    
    elif cmd == "next" or cmd == "n":
        play_stream(current_index + 1)
        return f"OK: Nächster Stream ({current_index + 1})"
    
    elif cmd == "prev" or cmd == "previous":
        play_stream(current_index - 1)
        return f"OK: Vorheriger Stream ({current_index + 1})"
    
    elif cmd == "station":
        if len(parts) > 1:
            try:
                index = int(parts[1]) - 1
                if index >= 0:
                    play_stream(index)
                    return f"OK: Station {index + 1} gestartet"
                else:
                    return "ERROR: Ungültige Stationsnummer"
            except ValueError:
                return "ERROR: Stationsnummer muss eine Zahl sein"
        else:
            return f"OK: Aktuelle Station: {current_index + 1}"
    
    elif cmd == "volume" or cmd == "v":
        if len(parts) > 1:
            try:
                if parts[1].startswith('+'):
                    change = int(parts[1][1:])
                    set_volume(change)
                elif parts[1].startswith('-'):
                    change = -int(parts[1][1:])
                    set_volume(change)
                else:
                    target = int(parts[1])
                    set_volume(target - current_volume)
                return f"OK: Lautstärke: {current_volume}%"
            except ValueError:
                return "ERROR: Ungültiger Lautstärke-Wert"
        else:
            return f"OK: Aktuelle Lautstärke: {current_volume}%"
    
    elif cmd == "status":
        playlist = read_playlist()
        return f"OK: Station {current_index + 1}/{len(playlist)}, " \
               f"Lautstärke: {current_volume}%, " \
               f"Status: {'Playing' if playback_state else 'Stopped'}"
    
    elif cmd == "info":
        return json.dumps(current_info, indent=2)
    
    elif cmd == "list":
        playlist = read_playlist()
        result = "Verfügbare Stationen:\n"
        for i, url in enumerate(playlist, 1):
            marker = " *" if i-1 == current_index else "  "
            result += f"{marker} {i}: {url}\n"
        return result.rstrip()
    
    elif cmd == "quit" or cmd == "exit":
        running = False
        return "OK: Beende Radio-Daemon"
    
    else:
        return f"ERROR: Unbekanntes Kommando '{cmd}'\n" \
               "Verfügbare Kommandos: play, stop, pause, next, prev, station [nr], " \
               "volume [+/-]wert, status, info, list, quit"

def setup_control_socket():
    """Erstellt Control Socket für CLI-Kommandos"""
    global control_socket
    
    # Entferne alten Socket falls vorhanden
    if os.path.exists(CONTROL_SOCKET):
        os.remove(CONTROL_SOCKET)
    
    control_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    control_socket.bind(CONTROL_SOCKET)
    control_socket.listen(1)
    
    def handle_connections():
        while running:
            try:
                conn, addr = control_socket.accept()
                command = conn.recv(1024).decode()
                response = process_command(command)
                conn.send(response.encode())
                conn.close()
            except Exception as e:
                if running:  # Nur loggen wenn wir nicht beim Beenden sind
                    logging.error(f"Socket-Verbindung: {e}")
                break
    
    threading.Thread(target=handle_connections, daemon=True).start()

def cleanup():
    """Cleanup-Funktion beim Beenden"""
    global running, mpg123_proc, control_socket, api_server
    
    logging.info("Beende Radiowecker...")
    running = False
    
    if mpg123_proc:
        mpg123_proc.terminate()
        mpg123_proc.wait()
    
    if control_socket:
        control_socket.close()
    
    if api_server:
        api_server.shutdown()
    
    if os.path.exists(CONTROL_SOCKET):
        os.remove(CONTROL_SOCKET)
    
    remove_pid_file()

def signal_handler(signum, frame):
    """Signal Handler für sauberes Beenden"""
    cleanup()
    sys.exit(0)

# --- CLI-Funktionen ---

def show_help():
    """Zeigt Hilfe für CLI-Kommandos"""
    print("Radio-Steuerung CLI mit REST-API")
    print("================================")
    print()
    print("Daemon-Kontrolle:")
    print("  python3 radio.py daemon    - Startet den Radio-Daemon mit API")
    print("  python3 radio.py status    - Zeigt Daemon-Status")
    print()
    print("CLI-Steuerung:")
    print("  python3 radio.py play      - Startet Wiedergabe")
    print("  python3 radio.py stop      - Stoppt Wiedergabe") 
    print("  python3 radio.py pause     - Play/Pause umschalten")
    print("  python3 radio.py next      - Nächste Station")
    print("  python3 radio.py prev      - Vorherige Station")
    print("  python3 radio.py station [nr] - Wechselt zu Station")
    print("  python3 radio.py volume [wert] - Setzt Lautstärke")
    print("  python3 radio.py info      - Stream-Informationen")
    print("  python3 radio.py list      - Liste aller Stationen")
    print("  python3 radio.py quit      - Beendet den Daemon")
    print()
    print("REST-API (wenn Daemon läuft):")
    print(f"  http://localhost:{API_PORT}/api/status")
    print(f"  http://localhost:{API_PORT}/api/play")
    print(f"  http://localhost:{API_PORT}/api/stop")
    print(f"  http://localhost:{API_PORT}/api/volume?level=75")

def main():
    global running
    
    # Signal Handler registrieren
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    if len(sys.argv) < 2:
        show_help()
        return
    
    command = sys.argv[1].lower()
    
    if command == "daemon":
        # Daemon-Modus: Hauptprogramm mit GPIO und API
        if is_daemon_running():
            print("[ERROR] Radio-Daemon läuft bereits.")
            return
        
        logging.info("Starte Radio-Daemon...")
        create_pid_file()
        
        try:
            if not init_gpio():
                logging.error("GPIO-Initialisierung fehlgeschlagen. Daemon wird beendet.")
                cleanup()
                return
            
            if not start_api_server():
                logging.error("API-Server Start fehlgeschlagen. Daemon wird beendet.")
                cleanup()
                return
                
            setup_control_socket()
            metadata_updater()
            play_stream(current_index)
            set_volume(current_volume)
            
            logging.info(f"Radiowecker gestartet (PID: {os.getpid()})")
            logging.info(f"Playlist: {PLAYLIST_PATH}")
            logging.info(f"GPIO Pins - DT: {PIN_DT}, CLK: {PIN_CLK}, SW: {PIN_SW}, ALARM: {PIN_ALARM}")
            logging.info(f"Control Socket: {CONTROL_SOCKET}")
            logging.info(f"REST-API: http://{API_HOST}:{API_PORT}")
            
            while running:
                time.sleep(0.1)
                
        except Exception as e:
            logging.error(f"Daemon-Fehler: {e}")
        finally:
            cleanup()
    
    elif command == "status":
        if is_daemon_running():
            print("Radio-Daemon läuft.")
            send_command("status")
        else:
            print("Radio-Daemon läuft nicht.")
    
    elif command in ["help", "-h", "--help"]:
        show_help()
    
    else:
        # Alle anderen Kommandos an Daemon weiterleiten
        cmd_str = " ".join(sys.argv[1:])
        send_command(cmd_str)

if __name__ == "__main__":
    main()