#!/usr/bin/env python3
"""
ble_scan_ppi.py
Escáner de Estaciones Siemens S7-200 directo por Bluetooth LE (BLE).
No requiere puerto serie virtual: se conecta directamente al ESP32-S3 vía BLE NUS
y envía las tramas de sondeo SD1 a través del aire hacia el bus RS485 del PLC.
"""

import sys
import time
import asyncio
import argparse
from bleak import BleakClient, BleakScanner

DEFAULT_NAME = "S7-200-PPI-BLE"
DEFAULT_MAC  = "28:84:85:91:45:06"
RX_UUID      = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # Laptop -> ESP32
TX_UUID      = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # ESP32 -> Laptop

def build_sd1(dest: int, src: int = 0, fc: int = 0x49) -> bytes:
    """Construye una trama SD1 de solicitud de estado."""
    fcs = (dest + src + fc) & 0xFF
    return bytes([0x10, dest, src, fc, fcs, 0x16])

class BlePpiScanner:
    def __init__(self, target_address=DEFAULT_MAC, max_addr=31, src=0, timeout=0.15):
        self.target_address = target_address
        self.max_addr = max_addr
        self.src = src
        self.timeout = timeout
        self.rx_buffer = bytearray()
        self.response_event = asyncio.Event()

    def notification_handler(self, sender, data: bytearray):
        self.rx_buffer.extend(data)
        self.response_event.set()

    async def run(self):
        print("=" * 65)
        print(" ESCÁNER INALÁMBRICO DE ESTACIONES SIEMENS PPI (BLE)")
        print(f" Dispositivo : {DEFAULT_NAME} ({self.target_address})")
        print(f" Rango       : Dirección 0 a {self.max_addr} (PC en {self.src})")
        print("=" * 65)

        print(f"[*] Conectando vía Bluetooth LE...")
        try:
            async with BleakClient(self.target_address, timeout=12.0) as client:
                print(f"[✓] Conexión BLE establecida con éxito.")
                await client.start_notify(TX_UUID, self.notification_handler)

                encontradas = []
                print(f"[*] Iniciando barrido de direcciones en el bus RS485...\n")

                for addr in range(0, self.max_addr + 1):
                    if addr == self.src:
                        continue

                    frame = build_sd1(dest=addr, src=self.src, fc=0x49)
                    self.rx_buffer.clear()
                    self.response_event.clear()

                    # Transmitir por BLE
                    await client.write_gatt_char(RX_UUID, frame, response=False)

                    # Esperar respuesta del PLC con timeout
                    try:
                        await asyncio.wait_for(self.response_event.wait(), timeout=self.timeout)
                    except asyncio.TimeoutError:
                        pass

                    if len(self.rx_buffer) > 0:
                        encontradas.append(addr)
                        hex_resp = " ".join(f"{b:02X}" for b in self.rx_buffer)
                        print(f"  [+] ¡ESTACIÓN ENCONTRADA! Dirección: {addr:2d} | Respuesta: {hex_resp}")
                    else:
                        print(f"  [.] Estación {addr:2d}: Sin respuesta")

                    await asyncio.sleep(0.04)

                print("\n" + "=" * 65)
                print(f" RESUMEN DEL ESCANEO INALÁMBRICO:")
                if encontradas:
                    print(f"  [✓] Estaciones activas detectadas: {encontradas}")
                else:
                    print(f"  [i] No se detectaron estaciones activas.")
                    print(f"      (Normal si el PLC no está físicamente conectado al FTDI en este momento).")
                print("=" * 65)

        except Exception as e:
            print(f"[-] Error de conexión Bluetooth: {e}")

def main():
    parser = argparse.ArgumentParser(description="Escáner PPI vía Bluetooth LE")
    parser.add_argument("--address", default=DEFAULT_MAC, help="MAC del ESP32")
    parser.add_argument("--max-addr", type=int, default=15, help="Dirección máxima (default: 15)")
    parser.add_argument("--src", type=int, default=0, help="Dirección PC (default: 0)")
    parser.add_argument("--timeout", type=float, default=0.15, help="Timeout respuesta (default: 0.15s)")
    args = parser.parse_args()

    scanner = BlePpiScanner(target_address=args.address, max_addr=args.max_addr, src=args.src, timeout=args.timeout)
    asyncio.run(scanner.run())

if __name__ == "__main__":
    main()
