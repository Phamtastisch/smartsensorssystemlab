# PPG Smart Sensor – Lab 1+2 Smart Sensor Systems (HAW Hamburg)

Pulsoximetrie-Sensor: PPG-Board RK-003 (ADS131M02 + SFH7050) mit Seeed XIAO ESP32C3.

- `firmware/` – PlatformIO-Projekt (Arduino): ADC per SPI, LED-Multiplexing Rot/IR/Dunkel, Ausgabe 133 Hz als CSV über USB
- `pc_software/ppg_viewer.py` – Live-Anzeige und Aufzeichnung (`python ppg_viewer.py COM5`)
- `pc_software/ppg_gui.py` – GUI zum Öffnen und Anzeigen gespeicherter Messungen

Abhängigkeiten PC: `pip install pyserial numpy scipy matplotlib openpyxl`

Hinweis: Teile des Codes wurden mit Unterstützung von KI (Claude, Anthropic) erstellt.
