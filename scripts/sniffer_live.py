#!/usr/bin/env python3
"""
sniffer_live.py
Sniffer de bajo nivel USB para el bus RS485 PPI (Siemens S7-200).
Captura el tráfico bidireccional exacto entre Windows 7 y el PLC Siemens S7-200
mediante usbmon a nivel de kernel, sin interferir con la máquina virtual.

Dispositivos soportados:
  - FTDI FT232RL (0403:6001)
  - ESP32 CH343 USB-Serial (1a86:55d3)
  *(El puerto nativo USB Serial/JTAG del ESP32 303a:* queda estrictamente excluido)*
"""

import sys
import os
import subprocess
import re
import datetime
import signal

LOG_FILE = "/home/gus05/rs485_ft232rl/sniffer.log"
MAX_LOG_BYTES = 5 * 1024 * 1024  # 5 MB por archivo

SUPPORTED_DEVICES = [
    {"vid_pid": "0403:6001", "name": "FTDI FT232RL", "type": "ftdi"},
    {"vid_pid": "1a86:55d3", "name": "ESP32 CH343 USB-Serial", "type": "ch343"},
]

class RotatingLogger:
    def __init__(self, log_path, max_bytes=MAX_LOG_BYTES):
        self.log_path = log_path
        self.max_bytes = max_bytes
        self.file = None
        self._ensure_open()

    def _rotate_if_needed(self):
        try:
            if os.path.exists(self.log_path) and os.path.getsize(self.log_path) >= self.max_bytes:
                backup = f"{self.log_path}.1"
                if os.path.exists(backup):
                    os.remove(backup)
                os.rename(self.log_path, backup)
        except Exception as e:
            sys.stderr.write(f"Error rotando log: {e}\n")

    def _ensure_open(self):
        if self.file is None:
            self._rotate_if_needed()
            self.file = open(self.log_path, "a", encoding="utf-8")

    def log(self, message):
        print(message, flush=True)
        try:
            self._ensure_open()
            self.file.write(message + "\n")
            self.file.flush()
            if self.file.tell() >= self.max_bytes:
                self.file.close()
                self.file = None
                self._ensure_open()
        except Exception as e:
            sys.stderr.write(f"Error escribiendo en log: {e}\n")

    def close(self):
        if self.file:
            try:
                self.file.close()
            except Exception:
                pass
            self.file = None

def detect_device():
    """Detecta si está conectado FTDI o CH343 (ignora Espressif JTAG 303a:*)."""
    for dev in SUPPORTED_DEVICES:
        res = subprocess.run(["lsusb", "-d", dev["vid_pid"]], capture_output=True, text=True)
        m = re.search(r"Bus\s+(\d+)\s+Device\s+(\d+)", res.stdout)
        if m:
            bus = int(m.group(1))
            device_num = int(m.group(2))
            return bus, device_num, dev
    return None, None, None

def parse_ppi(buffer: bytes):
    if not buffer:
        return ""
    if len(buffer) == 1 and buffer[0] == 0xE5:
        return " [PPI: SC (ACK / 0xE5)]"
    if buffer[0] == 0x10 and len(buffer) >= 6 and buffer[-1] == 0x16:
        # Check for known error frames (ej: 10 00 02 02 04 16)
        extra = ""
        if len(buffer) >= 4 and buffer[3] == 0x02:
            extra = " -> ¡ERROR 0x02: Recursos no disponibles / PDU excedida!"
        return f" [PPI: SD1 Solicitud corta | Dest: {buffer[1]}, Rem: {buffer[2]}, FC: 0x{buffer[3]:02X}]{extra}"
    if buffer[0] == 0x68 and len(buffer) >= 6 and buffer[-1] == 0x16:
        return f" [PPI: SD2 Trama variable (Len={buffer[1]}) | Dest: {buffer[4]}, Rem: {buffer[5]}, FC: 0x{buffer[6]:02X}]"
    if buffer[0] == 0xDC and len(buffer) == 4 and buffer[-1] == 0x16:
        return f" [PPI: SD4 Token | Dest: {buffer[1]}, Rem: {buffer[2]}]"
    return ""

def main():
    bus, dev, dev_info = detect_device()
    if not bus:
        sys.stderr.write("[-] Error: No se detectó ningún convertidor soportado (FTDI 0403:6001 o CH343 1a86:55d3).\n")
        sys.stderr.write("    (El puerto USB JTAG 303a:* del ESP32 está excluido por diseño).\n")
        sys.exit(1)

    logger = RotatingLogger(LOG_FILE, MAX_LOG_BYTES)

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header_banner = (
        "=" * 70 + "\n"
        f" SNIFFER RS485 / PPI EN VIVO (Captura de bajo nivel USB)\n"
        f" Dispositivo: {dev_info['name']} ({dev_info['vid_pid']})\n"
        f" Ubicación:   Bus {bus:03d}, Dispositivo {dev:03d} (usbmon{bus})\n"
        f" Inicio:      {now_str}\n"
        f" Archivo log: {LOG_FILE} (Límite: 5 MB con rotación a .1)\n"
        + "=" * 70
    )
    logger.log(header_banner)

    # Iniciar captura con tcpdump sobre la interfaz usbmon correspondiente
    cmd = ["sudo", "tcpdump", "-i", f"usbmon{bus}", "-XX", "-s", "0", "-l", "-nn"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)

    is_shutting_down = False

    def shutdown(signum, frame):
        nonlocal is_shutting_down
        if is_shutting_down:
            return
        is_shutting_down = True
        logger.log(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] [*] Sniffer finalizado limpiamente.")
        logger.close()
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    current_header = None
    current_bytes = []
    dev_str = f":{dev}:"

    try:
        for line in proc.stdout:
            line = line.rstrip()
            if not line.startswith("\t"):
                if current_header and current_bytes:
                    process_packet(current_header, current_bytes, dev, dev_info, logger)
                current_header = None
                current_bytes = []
                if "USB BULK" in line and dev_str in line:
                    current_header = line
            elif current_header and (
                line.startswith("\t0x004")
                or line.startswith("\t0x005")
                or line.startswith("\t0x006")
                or line.startswith("\t0x007")
            ):
                # Extraer bytes hexadecimales de los datos útiles a partir del offset 0x0040
                parts = line.split(":")
                if len(parts) >= 2:
                    hex_part = parts[1][:37].strip()
                    tokens = hex_part.split()
                    for t in tokens:
                        if len(t) == 4:
                            current_bytes.append(int(t[0:2], 16))
                            current_bytes.append(int(t[2:4], 16))
                        elif len(t) == 2:
                            current_bytes.append(int(t, 16))

        if current_header and current_bytes:
            process_packet(current_header, current_bytes, dev, dev_info, logger)

    except KeyboardInterrupt:
        shutdown(None, None)
    finally:
        shutdown(None, None)

def process_packet(header, raw_bytes, dev, dev_info, logger):
    ts = header.split()[0]
    dev_type = dev_info.get("type", "ftdi")

    # Identificar dirección del paquete USB:
    # "from Bus:Dev:Endpoint" -> IN (PLC hacia PC)
    # "to Bus:Dev:Endpoint"   -> OUT (PC hacia PLC)
    is_rx = f"from {header.split('from ')[-1]}" if "from " in header else ""
    is_tx = f"to {header.split('to ')[-1]}" if "to " in header else ""

    if f"from " in header and f":{dev}:" in header:
        # RX (desde PLC hacia PC)
        if dev_type == "ftdi":
            # En chips FTDI los primeros 2 bytes corresponden a Modem Status (01 60)
            data = bytes(raw_bytes[2:]) if len(raw_bytes) >= 2 else b""
        else:
            # En CH343 no hay bytes de estado de módem en el payload
            data = bytes(raw_bytes)

        if data:
            hex_str = " ".join(f"{b:02X}" for b in data)
            info = parse_ppi(data)
            logger.log(f"[{ts}]  <-- [RX desde PLC] ({len(data)} bytes): {hex_str}{info}")

    elif f"to " in header and f":{dev}:" in header:
        # TX (desde PC hacia PLC)
        data = bytes(raw_bytes)
        if data:
            hex_str = " ".join(f"{b:02X}" for b in data)
            info = parse_ppi(data)
            logger.log(f"[{ts}]  --> [TX hacia PLC] ({len(data)} bytes): {hex_str}{info}")

if __name__ == "__main__":
    main()
