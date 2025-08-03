Ein kleiner Radiowecker für den Raspberry Pi basierend auf python und mpeg123.

Zusätzliche dateien (wer mag): 
  - configfile für shairport



REST-API Endpoints:
Status & Information:

  - GET /api/status - Aktueller Radio-Status
  - GET /api/info - Detaillierte Stream-Informationen
  - GET /api/stations - Liste aller verfügbaren Stationen

Steuerung:

  - GET /api/play - Wiedergabe starten
  - GET /api/stop - Wiedergabe stoppen
  - GET /api/pause - Play/Pause umschalten
  - GET /api/next - Nächste Station
  - GET /api/prev - Vorherige Station

Parameter-Steuerung:

  - GET /api/volume?level=75 - Lautstärke setzen
  - GET /api/station?id=3 - Station wechseln
  - POST /api/volume mit JSON {"level": 75}
  - POST /api/station mit JSON {"id": 3}


Danke an Claude
