#!/bin/bash
echo "$(date): AirPlay gestoppt - starte Radio" >> /var/log/airplay-hooks.log
/usr/bin/python3 /home/masl/radio.py play

# /usr/local/bin/
#sudo chmod +x /usr/local/bin/airplay-stop-hook.sh