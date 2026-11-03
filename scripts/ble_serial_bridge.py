#!/usr/bin/env python3
"""
ble_serial_bridge.py
Puente bidireccional transparente entre un puerto serie virtual (PTY) y el ESP32-S3 vía Bluetooth LE (Nordic UART Service).

Permite que cualquier software (scripts de Python como plc_control.py, scan_ppi.py,
o Micro/WIN en VM/Wine) interactúe con el PLC Siemens S7-200 de forma 100% inalámbrica.
"""

import os
import sys
import pty
import tty
import termios
import asyncio
import argparse
import signal
from bleak import BleakClient, BleakScanner

# UUIDs oficiales del Nordic UART Service (NUS)
NUS_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX_CHAR_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # Laptop -> ESP32 (Write)
NUS_TX_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # ESP32 -> Laptop (Notify)

DEFAULT_NAME = "S7-200-PPI-BLE"
DEFAULT_LINK = "/tmp/ttyPPI"

class BleSerialBridge:
    def __init__(self, target_address=None, target_name=DEFAULT_NAME, link_path=DEFAULT_LINK):
        self.target_address = target_address
        self.target_name = target_name
        self.link_path = link_path
        self.client = None
        self.master_fd = None
        self.slave_fd = None
        self.slave_name = None
        self.running = True

    def setup_pty(self):
        self.master_fd, self.slave_fd = pty.openpty()
        self.slave_name = os.ttyname(self.slave_fd)

        # Configurar modo raw (sin echo, sin buffer de línea)
        tty.setraw(self.master_fd)
        tty.setraw(self.slave_fd)

        # Enlace simbólico en link_path
        if os.path.islink(self.link_path) or os.path.exists(self.link_path):
            try:
                os.unlink(self.link_path)
            except OSError:
                pass
        try:
            os.symlink(self.slave_name, self.link_path)
            print(f"[+] Puerto serie virtual creado:")
            print(f"    - Dispositivo PTY : {self.slave_name}")
            print(f"    - Enlace simból.  : {self.link_path}")
        except Exception as e:
            print(f"[!] No se pudo crear enlace simbólico en {self.link_path}: {e}")
            print(f"    Usa directamente el dispositivo: {self.slave_name}")

    def notification_handler(self, sender, data: bytearray):
        """Callback cuando llegan datos del PLC vía ESP32 (TX Char Notify)"""
        try:
            if self.master_fd is not None:
                os.write(self.master_fd, data)
                hex_str = " ".join(f"{b:02X}" for b in data)
                print(f"[PLC -> PC] ({len(data)} B): {hex_str}")
        except Exception as e:
            print(f"[-] Error escribiendo en PTY: {e}")

    async def pty_reader_loop(self):
        """Lee datos que el software escribe en el puerto virtual y los reenvía por BLE"""
        loop = asyncio.get_running_loop()
        while self.running:
            try:
                data = await loop.run_in_executor(None, os.read, self.master_fd, 256)
                if not data:
                    await asyncio.sleep(0.01)
                    continue

                if self.client and self.client.is_connected:
                    hex_str = " ".join(f"{b:02X}" for b in data)
                    print(f"[PC -> PLC] ({len(data)} B): {hex_str}")
                    # Enviar por bloques si excede MTU o escribir directo
                    await self.client.write_gatt_char(NUS_RX_CHAR_UUID, data, response=False)
                else:
                    print(f"[!] Datos recibidos pero BLE desconectado ({len(data)} B)")
            except Exception as e:
                if self.running:
                    print(f"[-] Error en pty_reader: {e}")
                    await asyncio.sleep(0.1)

    async def run(self):
        self.setup_pty()
        pty_task = asyncio.create_task(self.pty_reader_loop())

        while self.running:
            address = self.target_address
            if not address:
                print(f"[*] Buscando dispositivo BLE '{self.target_name}'...")
                device = await BleakScanner.find_device_by_name(self.target_name, timeout=8.0)
                if not device:
                    print(f"[-] '{self.target_name}' no encontrado. Reintentando en 3s...")
                    await asyncio.sleep(3)
                    continue
                address = device.address

            print(f"[*] Conectando a {self.target_name} ({address})...")
            try:
                async with BleakClient(address, timeout=12.0) as client:
                    self.client = client
                    print(f"[✓] ¡Conexión BLE establecida con {self.target_name}!")
                    await client.start_notify(NUS_TX_CHAR_UUID, self.notification_handler)
                    print(f"[✓] Suscripción a notificaciones del PLC activa.")
                    print(f"[✓] Puente listo para operar en {self.link_path}")

                    # Mantener conexión viva mientras client.is_connected
                    while client.is_connected and self.running:
                        await asyncio.sleep(0.5)

            except Exception as e:
                print(f"[-] Desconexión o error en enlace BLE: {e}")

            self.client = None
            if self.running:
                print("[*] Reintentando conexión BLE en 3 segundos...")
                await asyncio.sleep(3)

        pty_task.cancel()
        if self.master_fd is not None:
            os.close(self.master_fd)
        if self.slave_fd is not None:
            os.close(self.slave_fd)
        if os.path.islink(self.link_path):
            try:
                os.unlink(self.link_path)
            except OSError:
                pass

def main():
    parser = argparse.ArgumentParser(description="Puente Serial Virtual BLE para S7-200 / ESP32-S3")
    parser.add_argument("--address", help="Dirección MAC Bluetooth del ESP32 (ej: 28:84:85:91:45:06)")
    parser.add_argument("--name", default=DEFAULT_NAME, help=f"Nombre publicitario BLE (default: {DEFAULT_NAME})")
    parser.add_argument("--link", default=DEFAULT_LINK, help=f"Ruta del enlace serie virtual (default: {DEFAULT_LINK})")
    args = parser.parse_args()

    bridge = BleSerialBridge(target_address=args.address, target_name=args.name, link_path=args.link)

    def signal_handler(sig, frame):
        print("\n[*] Cerrando puente serie BLE...")
        bridge.running = False
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        asyncio.run(bridge.run())
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
