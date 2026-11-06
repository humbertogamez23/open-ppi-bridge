#!/bin/bash
set -e
echo "=========================================================="
echo "⚡ Flasheando Firmware ESP32-S3 (Dual-Baud 9.6k / 19.2k PPI)"
echo "=========================================================="
source /home/gus05/esp/esp-idf/export.sh
cd /home/gus05/esp/ppi_bridge

PORT="/dev/ttyACM0"
if [ ! -e "$PORT" ]; then
    PORT="/dev/ttyUSB0"
fi

echo "[*] Puerto serie detectado: $PORT"
idf.py -p "$PORT" flash

echo ""
echo "[✓] ¡Firmware cargado con éxito en el ESP32-S3!"
echo "[✓] Ahora soporta conmutación en caliente entre 9.600 y 19.200 baudios."
