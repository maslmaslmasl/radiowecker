#!/bin/bash

# Radio-Wecker Setup Script
# Automatische Installation auf Raspberry Pi

set -e  # Bei Fehler abbrechen

# Konfiguration
INSTALL_USER="masl"
INSTALL_DIR="/home/$INSTALL_USER"
SERVICE_NAME="radiowecker"
SCRIPT_NAME="radio.py"
PLAYLIST_NAME="radioliste.m3u"

# Farben für Output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_header() {
    echo -e "${BLUE}"
    echo "=================================="
    echo "    Radio-Wecker Setup Script"
    echo "=================================="
    echo -e "${NC}"
}

print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_root() {
    if [[ $EUID -eq 0 ]]; then
        print_error "Dieses Script sollte NICHT als root ausgeführt werden!"
        echo "Führen Sie es als normaler Benutzer aus. sudo wird automatisch verwendet wo nötig."
        exit 1
    fi
}

check_user() {
    if [[ "$USER" != "$INSTALL_USER" ]]; then
        print_warning "Script läuft als '$USER', installiert aber für '$INSTALL_USER'"
        read -p "Fortfahren? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
}

install_dependencies() {
    print_status "Installiere System-Abhängigkeiten..."
    
    sudo apt update
    sudo apt install -y \
        python3 \
        python3-pip \
        mpg123 \
        alsa-utils \
        git \
        curl
    
    print_status "Installiere Python-Abhängigkeiten..."
    pip3 install --user gpiozero
    
    # GPIO-Gruppe hinzufügen
    sudo usermod -a -G gpio $INSTALL_USER || true
}

download_files() {
    print_status "Erstelle Arbeitsverzeichnis..."
    
    if [[ ! -d "$INSTALL_DIR" ]]; then
        sudo mkdir -p "$INSTALL_DIR"
        sudo chown $INSTALL_USER:$INSTALL_USER "$INSTALL_DIR"
    fi
    
    cd "$INSTALL_DIR"
    
    # Backup existierender Dateien
    if [[ -f "$SCRIPT_NAME" ]]; then
        print_warning "Erstelle Backup der existierenden Installation..."
        cp "$SCRIPT_NAME" "${SCRIPT_NAME}.backup.$(date +%Y%m%d_%H%M%S)"
    fi
    
    # Download via verschiedene Methoden
    if [[ -n "$1" && "$1" == "--from-git" ]]; then
        print_status "Lade Dateien von Git Repository..."
        # Hier würde der Git-Download stehen
        git clone https://github.com/maslmaslmasl/radiowecker.git .
        print_error "Git-URL noch nicht konfiguriert. Verwenden Sie --from-files"
        exit 1
    elif [[ -n "$1" && "$1" == "--from-files" ]]; then
        print_status "Kopiere Dateien vom aktuellen Verzeichnis..."
        if [[ -f "../$SCRIPT_NAME" ]]; then
            cp "../$SCRIPT_NAME" .
        else
            print_error "Quelldateien nicht gefunden. Stellen Sie sicher, dass $SCRIPT_NAME im übergeordneten Verzeichnis liegt."
            exit 1
        fi
    else
        print_status "Erstelle Standard-Dateien..."
        create_default_files
    fi
    
    chmod +x "$SCRIPT_NAME"
}

create_default_files() {
    print_status "Erstelle Standard-Playlist..."
    
    cat > "$PLAYLIST_NAME" << 'EOF'
# Radio-Playlist
# Eine URL pro Zeile, Kommentare mit #

# Beispiel-Stationen (anpassen nach Bedarf)
http://streams.br.de/bayern1_2.m3u
http://streams.br.de/bayern3_2.m3u
http://www.antenne.de/webradio/antenne.m3u
http://streams.ffn.de/ffnstream.mp3
EOF

    print_warning "Standard-Playlist erstellt. Bitte bearbeiten Sie $INSTALL_DIR/$PLAYLIST_NAME"
}

configure_gpio() {
    print_status "Konfiguriere GPIO-Einstellungen..."
    
    echo "Aktuelle GPIO-Konfiguration im Script:"
    echo "  PIN_DT = 23"
    echo "  PIN_CLK = 24" 
    echo "  PIN_SW = 22"
    echo "  PIN_ALARM = 27"
    echo
    
    read -p "GPIO-Pins anpassen? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        read -p "PIN_DT (aktuell 23): " pin_dt
        read -p "PIN_CLK (aktuell 24): " pin_clk  
        read -p "PIN_SW (aktuell 22): " pin_sw
        read -p "PIN_ALARM (aktuell 27): " pin_alarm
        
        # GPIO-Pins im Script ersetzen
        if [[ -n "$pin_dt" ]]; then
            sed -i "s/PIN_DT = 23/PIN_DT = $pin_dt/" "$SCRIPT_NAME"
        fi
        if [[ -n "$pin_clk" ]]; then
            sed -i "s/PIN_CLK = 24/PIN_CLK = $pin_clk/" "$SCRIPT_NAME"
        fi
        if [[ -n "$pin_sw" ]]; then
            sed -i "s/PIN_SW = 22/PIN_SW = $pin_sw/" "$SCRIPT_NAME"
        fi
        if [[ -n "$pin_alarm" ]]; then
            sed -i "s/PIN_ALARM = 27/PIN_ALARM = $pin_alarm/" "$SCRIPT_NAME"
        fi
    fi
}

configure_api() {
    print_status "Konfiguriere API-Einstellungen..."
    
    # IP-Adresse ermitteln
    LOCAL_IP=$(hostname -I | awk '{print $1}')
    
    echo "Aktuelle API-Konfiguration:"
    echo "  Port: 8080"
    echo "  Host: 0.0.0.0 (alle Interfaces)"
    echo "  URL: http://$LOCAL_IP:8080"
    echo
    
    read -p "API-Port ändern? (aktuell 8080): " api_port
    if [[ -n "$api_port" ]]; then
        sed -i "s/API_PORT = 8080/API_PORT = $api_port/" "$SCRIPT_NAME"
        print_status "API-Port geändert zu: $api_port"
    fi
}

create_service() {
    print_status "Erstelle systemd Service..."
    
    sudo tee "/etc/systemd/system/$SERVICE_NAME.service" > /dev/null << EOF
[Unit]
Description=Radiowecker Daemon mit API
After=network.target sound.target

[Service]
Type=simple
User=$INSTALL_USER
Group=$INSTALL_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 $INSTALL_DIR/$SCRIPT_NAME daemon
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

# GPIO-Zugriff ermöglichen
SupplementaryGroups=gpio

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable "$SERVICE_NAME.service"
    
    print_status "Service '$SERVICE_NAME' erstellt und aktiviert"
}

configure_firewall() {
    print_status "Konfiguriere Firewall für API..."
    
    # UFW installiert?
    if command -v ufw >/dev/null 2>&1; then
        sudo ufw allow 8080/tcp comment "Radio API"
        print_status "Firewall-Regel für Port 8080 hinzugefügt"
    else
        print_warning "UFW nicht installiert. API-Port 8080 manuell freigeben falls nötig."
    fi
}

test_installation() {
    print_status "Teste Installation..."
    
    # Service starten
    sudo systemctl start "$SERVICE_NAME.service"
    sleep 3
    
    # Status prüfen
    if sudo systemctl is-active --quiet "$SERVICE_NAME.service"; then
        print_status "Service läuft erfolgreich"
        
        # API testen
        sleep 2
        if curl -s http://localhost:8080/api/status >/dev/null; then
            print_status "API antwortet erfolgreich"
        else
            print_warning "API antwortet nicht. Prüfen Sie die Logs: sudo journalctl -u $SERVICE_NAME -f"
        fi
        
        # CLI testen
        cd "$INSTALL_DIR"
        if python3 "$SCRIPT_NAME" status >/dev/null 2>&1; then
            print_status "CLI funktioniert"
        else
            print_warning "CLI-Problem erkannt"
        fi
    else
        print_error "Service konnte nicht gestartet werden"
        print_error "Logs: sudo journalctl -u $SERVICE_NAME -f"
        return 1
    fi
}

show_summary() {
    LOCAL_IP=$(hostname -I | awk '{print $1}')
    API_PORT=$(grep "API_PORT = " "$INSTALL_DIR/$SCRIPT_NAME" | cut -d'=' -f2 | tr -d ' ')
    
    echo -e "${GREEN}"
    echo "=================================="
    echo "    Installation abgeschlossen!"
    echo "=================================="
    echo -e "${NC}"
    echo
    echo "📂 Installation: $INSTALL_DIR"
    echo "🔧 Service: $SERVICE_NAME"
    echo "🌐 API: http://$LOCAL_IP:$API_PORT"
    echo
    echo "Nützliche Befehle:"
    echo "  sudo systemctl status $SERVICE_NAME    # Service-Status"
    echo "  sudo journalctl -u $SERVICE_NAME -f   # Live-Logs"
    echo "  python3 $INSTALL_DIR/$SCRIPT_NAME status  # CLI-Status"
    echo "  curl http://localhost:$API_PORT/api/status # API-Test"
    echo
    echo "Konfiguration:"
    echo "  📻 Playlist: $INSTALL_DIR/$PLAYLIST_NAME"
    echo "  ⚙️  GPIO-Pins: siehe $INSTALL_DIR/$SCRIPT_NAME"
    echo
    echo "Home Assistant Integration:"
    echo "  REST-Sensor URL: http://$LOCAL_IP:$API_PORT/api/status"
    echo
}

main() {
    print_header
    
    check_root
    check_user
    
    print_status "Starte Installation für Benutzer: $INSTALL_USER"
    
    install_dependencies
    download_files "$@"
    configure_gpio
    configure_api
    create_service
    configure_firewall
    
    if test_installation; then
        show_summary
        print_status "🎉 Installation erfolgreich abgeschlossen!"
    else
        print_error "❌ Installation mit Fehlern abgeschlossen. Prüfen Sie die Logs."
        exit 1
    fi
}

# Script starten
main "$@"
