#!/usr/bin/env python3
"""
verify_ble_write.py - Herramienta de Diagnóstico y Validación de Escritura S7comm / BLE
========================================================================================

Verifica a bajo nivel la comunicación y escritura sobre la memoria del PLC Siemens S7-200
(CPU 214) a través del puente ESP32-S3 BLE (Nordic UART Service).

Comprueba y demuestra experimentalmente:
  1. Direccionamiento de memoria V (0x84) mapeada como DB1 (dbNumber = 0x0001).
  2. Direccionamiento de memoria M (0x83) con dbNumber = 0x0000.
  3. Cabecera de datos S7comm (ReturnCode en solicitud = 0x00).
  4. Código de retorno del PLC (0xFF = Success, 0x03 = Object access fault).

Uso:
  python3 scripts/verify_ble_write.py [--mac 28:84:85:91:45:06]
"""

import asyncio
import sys
import argparse
from bleak import BleakClient, BleakScanner

NUS_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
NUS_RX_CHAR_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"  # Write
NUS_TX_CHAR_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"  # Notify

DEFAULT_MAC = "28:84:85:91:45:06"


def calc_fcs(payload: bytes) -> int:
    return sum(payload) & 0xFF


def build_sd2(pdu: bytes, plc_addr=2, pc_addr=0) -> bytes:
    payload = bytes([plc_addr, pc_addr, 0x4C]) + pdu
    fcs = calc_fcs(payload)
    return bytes([0x68, len(payload), len(payload), 0x68]) + payload + bytes([fcs, 0x16])


def build_sd1_poll(plc_addr=2, pc_addr=0) -> bytes:
    fcs = (plc_addr + pc_addr + 0x4C) & 0xFF
    return bytes([0x10, plc_addr, pc_addr, 0x4C, fcs, 0x16])


class PpiClient:
    def __init__(self, client):
        self.client = client
        self.rx_queue = asyncio.Queue()

    def notification_handler(self, sender, data):
        self.rx_queue.put_nowait(bytes(data))

    async def send_s7(self, pdu: bytes, timeout=2.0):
        sd2 = build_sd2(pdu)
        while not self.rx_queue.empty():
            self.rx_queue.get_nowait()

        await self.client.write_gatt_char(NUS_RX_CHAR_UUID, sd2, response=False)

        # Esperar ACK de enlace (0xE5)
        ack = False
        t_end = asyncio.get_event_loop().time() + 0.5
        while asyncio.get_event_loop().time() < t_end:
            try:
                chunk = await asyncio.wait_for(self.rx_queue.get(), timeout=0.2)
                if 0xE5 in chunk:
                    ack = True
                    break
            except asyncio.TimeoutError:
                pass

        if not ack:
            return None

        await asyncio.sleep(0.04)

        # Sondeo SD1 periódico hasta recibir SD2
        poll = build_sd1_poll()
        t_end = asyncio.get_event_loop().time() + timeout
        accum = bytearray()
        while asyncio.get_event_loop().time() < t_end:
            await self.client.write_gatt_char(NUS_RX_CHAR_UUID, poll, response=False)
            t_chunk = asyncio.get_event_loop().time() + 0.2
            while asyncio.get_event_loop().time() < t_chunk:
                try:
                    chunk = await asyncio.wait_for(self.rx_queue.get(), timeout=0.15)
                    for b in chunk:
                        if b == 0xE5 and len(accum) == 0:
                            continue
                        accum.append(b)
                    if len(accum) >= 6 and accum[0] == 0x68 and accum[-1] == 0x16 and len(accum) >= (accum[1] + 6):
                        return bytes(accum)
                except asyncio.TimeoutError:
                    pass
            await asyncio.sleep(0.04)
        return None


async def run_diagnostics(target_mac: str):
    print("=" * 70)
    print("  AUDITORÍA Y VALIDACIÓN DE ESCRITURA S7COMM / BLE (SIEMENS S7-200)")
    print(f"  Objetivo BLE: {target_mac}")
    print("=" * 70)

    print(f"[*] Conectando con el puente ESP32-S3 ({target_mac})...")
    async with BleakClient(target_mac, timeout=12.0) as client:
        print("[✓] Conectado exitosamente por BLE.")
        ppi = PpiClient(client)
        await client.start_notify(NUS_TX_CHAR_UUID, ppi.notification_handler)
        await asyncio.sleep(0.4)

        # 1. Verificar lectura de entradas físicas IB0
        read_ib0 = bytes([
            0x32, 0x01, 0x00, 0x00, 0x00, 0x01, 0x00, 0x0E, 0x00, 0x00,
            0x04, 0x01, 0x12, 0x0A, 0x10, 0x02, 0x00, 0x01, 0x00, 0x00,
            0x81, 0x00, 0x00, 0x00
        ])
        resp_ib0 = await ppi.send_s7(read_ib0)
        if resp_ib0:
            val_ib0 = resp_ib0[-3]
            print(f"[✓] Enlace RS-485 activo: IB0 = 0x{val_ib0:02X} (I0.1={1 if val_ib0 & 0x02 else 0})")
        else:
            print("[-] Error: El PLC no respondió a la lectura de IB0.")
            return

        # 2. Batería de pruebas de escritura
        tests = [
            ("Escritura VB200=1 (DB1, retReq=0x00)", bytes([
                0x32, 0x01, 0x00, 0x00, 0x00, 0x02, 0x00, 0x0E, 0x00, 0x05,
                0x05, 0x01, 0x12, 0x0A, 0x10, 0x02, 0x00, 0x01, 0x00, 0x01,  # DB1
                0x84, 0x00, 0x06, 0x40,  # bit = 200 * 8 = 1600 = 0x000640
                0x00, 0x04, 0x00, 0x08, 0x01
            ])),
            ("Escritura VB200=1 (DB0, retReq=0x00) [Inválido S7-200]", bytes([
                0x32, 0x01, 0x00, 0x00, 0x00, 0x03, 0x00, 0x0E, 0x00, 0x05,
                0x05, 0x01, 0x12, 0x0A, 0x10, 0x02, 0x00, 0x01, 0x00, 0x00,  # DB0
                0x84, 0x00, 0x06, 0x40,
                0x00, 0x04, 0x00, 0x08, 0x01
            ])),
            ("Escritura Bit V200.0=1 (DB1)", bytes([
                0x32, 0x01, 0x00, 0x00, 0x00, 0x04, 0x00, 0x0E, 0x00, 0x05,
                0x05, 0x01, 0x12, 0x0A, 0x10, 0x01, 0x00, 0x01, 0x00, 0x01,  # DB1
                0x84, 0x00, 0x06, 0x40,
                0x00, 0x03, 0x00, 0x01, 0x01
            ])),
            ("Escritura MB10=1 (Marcas M, DB0)", bytes([
                0x32, 0x01, 0x00, 0x00, 0x00, 0x05, 0x00, 0x0E, 0x00, 0x05,
                0x05, 0x01, 0x12, 0x0A, 0x10, 0x02, 0x00, 0x01, 0x00, 0x00,  # DB0
                0x83, 0x00, 0x00, 0x50,  # bit = 10 * 8 = 80 = 0x50
                0x00, 0x04, 0x00, 0x08, 0x01
            ])),
        ]

        print("\n" + "-" * 70)
        print("  EJECUTANDO TESTS COMPARATIVOS DE ESCRITURA")
        print("-" * 70)

        for desc, pdu in tests:
            await asyncio.sleep(0.08)
            resp = await ppi.send_s7(pdu)
            if resp:
                ret_code = resp[-3]
                status_str = "EXITO (0xFF)" if ret_code == 0xFF else f"FALLO (0x{ret_code:02X})"
                print(f"  • {desc:<48} -> {status_str}")
            else:
                print(f"  • {desc:<48} -> SIN RESPUESTA")

        print("=" * 70)
        print("  [✓] Diagnóstico finalizado.")
        print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Verificador de escritura S7comm sobre BLE.")
    parser.add_argument("--mac", default=DEFAULT_MAC, help=f"Dirección MAC del ESP32 BLE (default: {DEFAULT_MAC})")
    args = parser.parse_args()

    try:
        asyncio.run(run_diagnostics(args.mac))
    except KeyboardInterrupt:
        print("\nCancelado por el usuario.")
    except Exception as e:
        print(f"\n[-] Error: {e}")


if __name__ == "__main__":
    main()
