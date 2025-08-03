#!/bin/bash
echo "$(date): AirPlay gestartet - stoppe Radio" >> /var/log/airplay-hooks.log
/usr/bin/python3 /home/masl/radio.py stop

# /usr/local/bin/
#sudo chmod +x /usr/local/bin/airplay-start-hook.sh
