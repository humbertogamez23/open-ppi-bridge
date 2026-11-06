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
    def __init__(self, target_address=DEFAULT_MAC, max_addr=31, src=0, timeout=0.18, baud="auto"):
        self.target_address = target_address
        self.max_addr = max_addr
        self.src = src
        self.timeout = timeout
        self.baud = str(baud).lower().strip()
        self.rx_buffer = bytearray()
        self.response_event = asyncio.Event()

    def notification_handler(self, sender, data: bytearray):
        self.rx_buffer.extend(data)
        self.response_event.set()

    async def _scan_pass(self, client, baud_rate: int) -> list:
        # Enviar comando de conmutación de velocidad al ESP32
        cmd = f"++BAUD:{baud_rate}".encode()
        await client.write_gatt_char(RX_UUID, cmd, response=False)
        await asyncio.sleep(0.08)

        print(f"\n[*] Barrido a {baud_rate} baudios (Rango 0..{self.max_addr}):")
        encontradas = []

        for addr in range(0, self.max_addr + 1):
            if addr == self.src:
                continue

            frame = build_sd1(dest=addr, src=self.src, fc=0x49)
            self.rx_buffer.clear()
            self.response_event.clear()

            await client.write_gatt_char(RX_UUID, frame, response=False)

            try:
                await asyncio.wait_for(self.response_event.wait(), timeout=self.timeout)
            except asyncio.TimeoutError:
                pass

            if len(self.rx_buffer) > 0:
                # Filtrar posibles respuestas de comando
                clean = bytes(b for b in self.rx_buffer if b not in b"+BAUDOK:")
                if clean:
                    encontradas.append(addr)
                    hex_resp = " ".join(f"{b:02X}" for b in self.rx_buffer)
                    print(f"  [+] ¡ESTACIÓN ENCONTRADA! Dirección: {addr:2d} | Respuesta: {hex_resp}")
                    await asyncio.sleep(0.03)
                    continue

            print(f"  [.] Estación {addr:2d}: Sin respuesta")
            await asyncio.sleep(0.03)

        return encontradas

    async def run(self):
        print("=" * 65)
        print(" ESCÁNER INALÁMBRICO DE ESTACIONES SIEMENS PPI (BLE)")
        print(f" Dispositivo : {DEFAULT_NAME} ({self.target_address})")
        print(f" Rango       : Dirección 0 a {self.max_addr} (PC en {self.src})")
        print(f" Velocidad   : {self.baud.upper()} (Auto-conmutación 21x/22x)")
        print("=" * 65)

        print(f"[*] Conectando vía Bluetooth LE...")
        try:
            async with BleakClient(self.target_address, timeout=12.0) as client:
                print(f"[✓] Conexión BLE establecida con éxito.")
                await client.start_notify(TX_UUID, self.notification_handler)

                encontradas_totales = []

                if self.baud in ("9600", "19200", "187500"):
                    encontradas = await self._scan_pass(client, int(self.baud))
                    if encontradas:
                        encontradas_totales.extend([(a, int(self.baud)) for a in encontradas])
                else:
                    # Modo Auto: Probar primero 9.600 baudios (Serie 21x / 22x default)
                    enc_96 = await self._scan_pass(client, 9600)
                    if enc_96:
                        encontradas_totales.extend([(a, 9600) for a in enc_96])
                    else:
                        print(f"\n[*] Sin respuesta a 9.600 baudios. Probando conmutación a 19.200 baudios (Serie 22x)...")
                        enc_19 = await self._scan_pass(client, 19200)
                        if enc_19:
                            encontradas_totales.extend([(a, 19200) for a in enc_19])

                print("\n" + "=" * 65)
                print(f" RESUMEN DEL ESCANEO INALÁMBRICO:")
                if encontradas_totales:
                    for addr, b in encontradas_totales:
                        serie = "Serie 21x / 22x" if b == 9600 else "Serie 22x Industrial"
                        print(f"  [✓] Estación {addr} detectada a {b} baudios ({serie})")
                else:
                    print(f"  [i] No se detectaron estaciones activas en 9.600 ni en 19.200 baudios.")
                    print(f"      - Verifique que la llave frontal del PLC esté en STOP (evita bloqueo por Freeport).")
                    print(f"      - Verifique la polaridad RS-485: Pin 3 es B(+) y Pin 8 es A(-).")
                print("=" * 65)

        except Exception as e:
            try:
                from bleak.exc import BleakDeviceNotFoundError
                if isinstance(e, BleakDeviceNotFoundError):
                    print(f"\n[X] Dispositivo no encontrado: No se localizó la pasarela ESP32 ({self.target_address}).")
                    print("    - Verifique que la placa ESP32-S3 esté conectada y encendida.")
                    print("    - Asegúrese de que el Bluetooth de su ordenador esté activado y dentro del alcance.")
                    return
            except Exception:
                pass
            print(f"[-] Error de conexión Bluetooth: {e}")

def main():
    parser = argparse.ArgumentParser(description="Escáner PPI vía Bluetooth LE")
    parser.add_argument("--address", default=DEFAULT_MAC, help="MAC del ESP32")
    parser.add_argument("--max-addr", type=int, default=15, help="Dirección máxima (default: 15)")
    parser.add_argument("--src", type=int, default=0, help="Dirección PC (default: 0)")
    parser.add_argument("--baud", default="auto", help="Velocidad: auto (prueba 9.6k y 19.2k), 9600 o 19200 (default: auto)")
    parser.add_argument("--timeout", type=float, default=0.18, help="Timeout respuesta (default: 0.18s)")
    args = parser.parse_args()

    scanner = BlePpiScanner(target_address=args.address, max_addr=args.max_addr, src=args.src, timeout=args.timeout, baud=args.baud)
    asyncio.run(scanner.run())

if __name__ == "__main__":
    main()
