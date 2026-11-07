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


def is_valid_ppi_response(resp: bytes, expected_addr: int, expected_src: int = 0) -> bool:
    """Verifica rigurosamente si la respuesta es una trama PPI válida de la estación esperada."""
    if not resp:
        return False
    # Caso 1: Confirmación corta SC (0xE5)
    if resp == b"\xE5":
        return True
    # Caso 2: Trama corta SD1 (6 bytes: 10 DA SA FC FCS 16)
    if len(resp) >= 6 and resp[0] == 0x10 and resp[-1] == 0x16:
        da, sa, fc, fcs = resp[1], resp[2], resp[3], resp[4]
        if da == expected_src and sa == expected_addr and fcs == ((da + sa + fc) & 0xFF):
            return True
    # Caso 3: Trama de datos SD2 (68 LE LE 68 DA SA ... FCS 16)
    if len(resp) >= 6 and resp[0] == 0x68 and resp[-1] == 0x16:
        length = resp[1]
        if resp[2] == length and len(resp) == length + 6:
            da, sa = resp[4], resp[5]
            if da == expected_src and sa == expected_addr:
                calc_fcs = sum(resp[4:-2]) & 0xFF
                if resp[-2] == calc_fcs:
                    return True
    return False


class BlePpiScanner:
    def __init__(self, target_address=DEFAULT_MAC, max_addr=31, src=0, timeout=0.22, baud="auto"):
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

    async def _set_baud(self, client, baud_rate: int):
        """Envía comando de conmutación de baudios y drena la respuesta del ESP32 (++BAUD:OK)."""
        self.rx_buffer.clear()
        self.response_event.clear()
        cmd = f"++BAUD:{baud_rate}".encode()
        await client.write_gatt_char(RX_UUID, cmd, response=False)

        # Esperar a que el firmware del ESP32 confirme con ++BAUD:OK
        deadline = time.time() + 0.35
        while time.time() < deadline:
            if b"++BAUD:" in self.rx_buffer:
                break
            try:
                await asyncio.wait_for(self.response_event.wait(), timeout=max(0.02, deadline - time.time()))
                self.response_event.clear()
            except asyncio.TimeoutError:
                pass

        await asyncio.sleep(0.06)
        self.rx_buffer.clear()
        self.response_event.clear()

    async def _scan_pass(self, client, baud_rate: int) -> list:
        await self._set_baud(client, baud_rate)

        print(f"\n[*] Barrido a {baud_rate} baudios (Rango 0..{self.max_addr}):")
        encontradas = []

        for addr in range(0, self.max_addr + 1):
            if addr == self.src:
                continue

            self.rx_buffer.clear()
            self.response_event.clear()

            frame = build_sd1(dest=addr, src=self.src, fc=0x49)
            await client.write_gatt_char(RX_UUID, frame, response=False)

            deadline = time.time() + self.timeout
            found = False
            valid_frame = None

            while time.time() < deadline:
                curr = bytes(self.rx_buffer)
                if is_valid_ppi_response(curr, expected_addr=addr, expected_src=self.src):
                    found = True
                    valid_frame = curr
                    break
                try:
                    await asyncio.wait_for(self.response_event.wait(), timeout=max(0.02, deadline - time.time()))
                    self.response_event.clear()
                except asyncio.TimeoutError:
                    pass

            # Purgar el búfer tras cada dirección para evitar fugas de bytes a la siguiente
            self.rx_buffer.clear()
            self.response_event.clear()

            if found and valid_frame:
                encontradas.append(addr)
                hex_resp = " ".join(f"{b:02X}" for b in valid_frame)
                print(f"  [+] ¡ESTACIÓN ENCONTRADA! Dirección: {addr:2d} | Respuesta: {hex_resp}")
            else:
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
