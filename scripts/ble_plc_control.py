#!/usr/bin/env python3
"""
ble_plc_control.py
Herramienta integral de Control, Diagnóstico y Monitor de E/S para Siemens S7-200 (CPU 214)
vía Bluetooth LE (BLE).

Comandos disponibles:
  status    - Estado operativo (RUN/STOP, llave) + Entradas (I) y Salidas (Q)
  io        - Lector específico de Entradas (I0.0..I1.5) y Salidas (Q0.0..Q1.1)
  run       - Pone la CPU en modo de marcha (RUN)
  stop      - Detiene la CPU (STOP)

Opciones:
  -w, --watch   Modo monitor continuo en tiempo real (para status o io)
"""

import sys
import time
import os
import asyncio
import argparse
from bleak import BleakClient

DEFAULT_NAME = "S7-200-PPI-BLE"
DEFAULT_MAC  = "28:84:85:91:45:06"
RX_UUID      = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # Laptop -> ESP32
TX_UUID      = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # ESP32 -> Laptop

PLC_ADDR     = 2
PC_ADDR      = 0

def calc_fcs(payload: bytes) -> int:
    return sum(payload) & 0xFF

def is_valid_sd1(frame: bytes) -> bool:
    if len(frame) != 6 or frame[0] != 0x10 or frame[5] != 0x16:
        return False
    return frame[4] == ((frame[1] + frame[2] + frame[3]) & 0xFF)

def is_valid_sd2(frame: bytes) -> bool:
    if len(frame) < 6 or frame[0] != 0x68 or frame[-1] != 0x16 or frame[1] != frame[2]:
        return False
    length = frame[1]
    if len(frame) != length + 6:
        return False
    return frame[-2] == (sum(frame[4:-2]) & 0xFF)

def format_io_bits(byte_val: int, prefix: str, max_bits: int = 8) -> str:
    parts = []
    for bit in range(max_bits):
        val = (byte_val >> bit) & 1
        lbl = f"{prefix}.{bit}"
        st = "\033[92m● 1\033[0m" if val else "\033[90m○ 0\033[0m"
        parts.append(f"{lbl}:{st}")
    return "  ".join(parts)

class BlePlcController:
    def __init__(self, target_address=DEFAULT_MAC, plc_addr=PLC_ADDR, pc_addr=PC_ADDR):
        self.target_address = target_address
        self.plc_addr = plc_addr
        self.pc_addr = pc_addr
        self.client = None
        self.rx_queue = asyncio.Queue()

    def notification_handler(self, sender, data: bytearray):
        self.rx_queue.put_nowait(bytes(data))

    async def connect(self):
        print(f"[*] Conectando vía Bluetooth LE a {DEFAULT_NAME} ({self.target_address})...")
        self.client = BleakClient(self.target_address, timeout=12.0)
        await self.client.connect()
        print(f"[✓] Enlace Bluetooth LE establecido con éxito.")
        await self.client.start_notify(TX_UUID, self.notification_handler)

    async def disconnect(self):
        if self.client and self.client.is_connected:
            await self.client.disconnect()
            print("[*] Desconectado de Bluetooth.")

    async def send_s7_request(self, pdu_body: bytes, timeout=2.0) -> bytes:
        """Transmite una solicitud S7comm SD2 y espera la respuesta completa."""
        payload = bytes([self.plc_addr, self.pc_addr, 0x4C]) + pdu_body
        fcs = calc_fcs(payload)
        frame = bytes([0x68, len(payload), len(payload), 0x68]) + payload + bytes([fcs, 0x16])

        # Enviar trama SD2 y esperar ACK (0xE5)
        ack_received = False
        for _ in range(3):
            while not self.rx_queue.empty():
                self.rx_queue.get_nowait()

            await self.client.write_gatt_char(RX_UUID, frame, response=False)
            
            t_wait = time.time() + 0.35
            while time.time() < t_wait:
                try:
                    resp = await asyncio.wait_for(self.rx_queue.get(), timeout=0.35)
                    if resp and (0xE5 in resp or resp == b"\xE5"):
                        ack_received = True
                        break
                except asyncio.TimeoutError:
                    pass
            if ack_received:
                break
            await asyncio.sleep(0.05)

        if not ack_received:
            return None

        # Sondeo periódico SD1 (0x4C) esperando respuesta de datos
        poll_frame = bytes([0x10, self.plc_addr, self.pc_addr, 0x4C, (self.plc_addr + self.pc_addr + 0x4C) & 0xFF, 0x16])
        
        deadline = time.time() + timeout
        accum = bytearray()
        while time.time() < deadline:
            await self.client.write_gatt_char(RX_UUID, poll_frame, response=False)
            try:
                chunk = await asyncio.wait_for(self.rx_queue.get(), timeout=0.20)
                if chunk:
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

    async def read_memory_area(self, area_code: int, start_byte: int, count: int, seq: int = 1) -> bytes:
        """Lee un bloque de memoria del PLC (I=0x81, Q=0x82, SM=0x05, V=0x84, M=0x83)."""
        start_bit = start_byte * 8
        pdu_read = bytes([
            0x32, 0x01, 0x00, 0x00, (seq >> 8) & 0xFF, seq & 0xFF, 0x00, 0x0E, 0x00, 0x00,
            0x04, 0x01, 0x12, 0x0A, 0x10, 0x02, (count >> 8) & 0xFF, count & 0xFF, 0x00, 0x00,
            area_code, (start_bit >> 16) & 0xFF, (start_bit >> 8) & 0xFF, start_bit & 0xFF
        ])
        res = await self.send_s7_request(pdu_read, timeout=1.5)
        if res and len(res) >= (21 + count) and res[0] == 0x68 and res[-1] == 0x16:
            return res[-(2 + count):-2]
        return None

    async def set_mode(self, mode: str) -> bool:
        """Pone la CPU en RUN o STOP."""
        mode = mode.upper()
        if mode == "RUN":
            fc = 0x28
            desc = "RUN (Poner CPU en Marcha)"
        elif mode == "STOP":
            fc = 0x29
            desc = "STOP (Detener CPU)"
        else:
            print(f"[-] Modo inválido: {mode}")
            return False

        p_prog = b"P_PROGRAM"
        if mode == "RUN":
            param = bytes([0x28, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xFD, 0x00, 0x00, len(p_prog)]) + p_prog
        else:
            param = bytes([0x29, 0x00, 0x00, 0x00, 0x00, 0x00, len(p_prog)]) + p_prog

        pdu = bytes([
            0x32, 0x01, 0x00, 0x00, 0x00, fc,
            (len(param) >> 8) & 0xFF, len(param) & 0xFF,
            0x00, 0x00
        ]) + param

        print(f"[*] Enviando orden {desc} a la CPU {self.plc_addr} vía Bluetooth...")
        resp = await self.send_s7_request(pdu, timeout=3.0)

        if resp and len(resp) >= 19 and resp[0] == 0x68 and resp[-1] == 0x16:
            s7 = resp[7:-2]
            err_cls = s7[10] if len(s7) >= 12 else 0
            err_cod = s7[11] if len(s7) >= 12 else 0
            if err_cls == 0 and err_cod == 0:
                print(f"\n============================================================")
                print(f"  [✓] ¡ÉXITO! La CPU {self.plc_addr} cambió a modo {mode}.")
                print(f"============================================================")
                return True
        else:
            print(f"\n[-] El PLC no confirmó el cambio a modo {mode}.")
            print(f"    (Comprueba que el switch físico de la CPU esté en posición 'TERM' o 'RUN').")
            return False

    async def get_status_data(self):
        """Obtiene una instantánea del estado, entradas y salidas."""
        # 1. Leer SMB0 (Modo operativo)
        smb0_data = await self.read_memory_area(area_code=0x05, start_byte=0, count=1, seq=1)
        if smb0_data is None:
            # Reintentar una vez por si hubo un paquete rezagado en el bus
            await asyncio.sleep(0.05)
            smb0_data = await self.read_memory_area(area_code=0x05, start_byte=0, count=1, seq=1)
            if smb0_data is None:
                return None

        await asyncio.sleep(0.04)

        # 2. Leer Entradas Digitales (IB0, IB1)
        inputs = await self.read_memory_area(area_code=0x81, start_byte=0, count=2, seq=2)
        await asyncio.sleep(0.04)

        # 3. Leer Salidas Digitales (QB0, QB1)
        outputs = await self.read_memory_area(area_code=0x82, start_byte=0, count=2, seq=3)
        await asyncio.sleep(0.04)

        # 4. Leer Potenciómetros Analógicos (SMB28, SMB29)
        pots = await self.read_memory_area(area_code=0x05, start_byte=28, count=2, seq=4)

        return {
            "smb0": smb0_data[0] if smb0_data else None,
            "inputs": inputs,
            "outputs": outputs,
            "pots": pots
        }

    async def display_status(self, data):
        print("\n" + "=" * 65)
        print("          ESTADO INTEGRAL SIEMENS S7-200 (CPU 214) [BLE]")
        print("=" * 65)
        print(f"  • Enlace Inalámbrico : \033[92mCONECTADO (Bluetooth LE OK)\033[0m")
        print(f"  • Dispositivo        : {DEFAULT_NAME} ({self.target_address})")
        print(f"  • Dirección CPU      : {self.plc_addr}")

        if data is None:
            print(f"  • Estado del PLC     : \033[93mSIN RESPUESTA EN BUS RS485\033[0m")
            print(f"                         (PLC apagado o desconectado del módulo FTDI)")
            print("=" * 65)
            return

        # Modo de la CPU
        if data["smb0"] is not None:
            smb0 = data["smb0"]
            is_run = bool(smb0 & 0x01)
            switch_run = bool(smb0 & 0x80)
            modo_str = "\033[92m● RUN (En Marcha)\033[0m" if is_run else "\033[91m■ STOP (Detenido)\033[0m"
            llave_str = "RUN" if switch_run else "TERM / STOP"
            print(f"  • Estado Operativo   : {modo_str}")
            print(f"  • Posición de Llave  : {llave_str}")
        else:
            print(f"  • Estado del PLC     : \033[92mONLINE\033[0m")

        print("-" * 65)
        print("  [ ENTRADAS DIGITALES (I) ]")
        if data["inputs"] and len(data["inputs"]) >= 2:
            print("    IB0: " + format_io_bits(data["inputs"][0], "I0", 8))
            print("    IB1: " + format_io_bits(data["inputs"][1], "I1", 6) + "  (I1.0 a I1.5)")
        else:
            print("    (No se pudieron consultar entradas)")

        print("-" * 65)
        print("  [ SALIDAS DIGITALES (Q) ]")
        if data["outputs"] and len(data["outputs"]) >= 2:
            print("    QB0: " + format_io_bits(data["outputs"][0], "Q0", 8))
            print("    QB1: " + format_io_bits(data["outputs"][1], "Q1", 2) + "  (Q1.0 a Q1.1)")
        else:
            print("    (No se pudieron consultar salidas)")

        print("-" * 65)
        print("  [ POTENCIÓMETROS ANALÓGICOS (SMB28 / SMB29) ]")
        if data.get("pots") and len(data["pots"]) >= 2:
            p0 = data["pots"][0]
            p1 = data["pots"][1]
            b0 = "█" * (p0 // 17) + "░" * (15 - (p0 // 17))
            b1 = "█" * (p1 // 17) + "░" * (15 - (p1 // 17))
            pct0 = p0 * 100 // 255
            pct1 = p1 * 100 // 255
            print(f"    Pot 0 (SMB28): {p0:3d}/255  [{b0}] {pct0:3d}%")
            print(f"    Pot 1 (SMB29): {p1:3d}/255  [{b1}] {pct1:3d}%")
        else:
            print("    (No se pudieron consultar potenciómetros)")
        print("=" * 65)

    async def read_variable(self, var_str: str):
        """Lee cualquier variable interna por nombre (ej: SMB28, SMB29, VW100, VB50, VD200, MB0, MW10)."""
        import re
        import struct
        var = var_str.upper().strip()
        m = re.match(r'^([A-Z]+)(\d+)$', var)
        if not m:
            print(f"[-] Formato no reconocido: '{var_str}'. Ejemplos: SMB28, VW100, VB50, VD200, MB0, MW10")
            return

        prefix, offset_str = m.group(1), m.group(2)
        offset = int(offset_str)

        area_map = {
            'SM': 0x05, 'SMB': 0x05, 'SMW': 0x05, 'SMD': 0x05,
            'V': 0x84, 'VB': 0x84, 'VW': 0x84, 'VD': 0x84,
            'M': 0x83, 'MB': 0x83, 'MW': 0x83, 'MD': 0x83,
            'I': 0x81, 'IB': 0x81, 'IW': 0x81,
            'Q': 0x82, 'QB': 0x82, 'QW': 0x82
        }

        if prefix not in area_map:
            print(f"[-] Área no soportada: '{prefix}'. Áreas válidas: V, M, SM, I, Q")
            return

        area_code = area_map[prefix]
        if prefix.endswith('D'):
            count = 4
        elif prefix.endswith('W'):
            count = 2
        else:
            count = 1

        print(f"[*] Leyendo {var} ({count} bytes en offset {offset}) en CPU {self.plc_addr}...")
        raw = await self.read_memory_area(area_code=area_code, start_byte=offset, count=count)
        if raw is None or len(raw) < count:
            print(f"[-] No se pudo leer {var} (Sin respuesta del PLC en bus RS485)")
            return

        hex_str = " ".join(f"{b:02X}" for b in raw)
        print("\n" + "=" * 55)
        print(f"  LECTURA DE VARIABLE: {var}")
        print("=" * 55)
        if count == 1:
            val_int = raw[0]
            print(f"  • Decimal (Byte) : {val_int}")
            print(f"  • Hexadecimal    : 0x{hex_str}")
            print(f"  • Binario        : {val_int:08b}")
        elif count == 2:
            val_int = (raw[0] << 8) | raw[1]
            val_signed = val_int if val_int < 32768 else val_int - 65536
            print(f"  • Decimal (Word) : {val_int} (Sin signo)")
            print(f"  • Decimal Signed : {val_signed}")
            print(f"  • Hexadecimal    : 0x{hex_str}")
        elif count == 4:
            val_int = (raw[0] << 24) | (raw[1] << 16) | (raw[2] << 8) | raw[3]
            val_float = struct.unpack('>f', raw)[0]
            print(f"  • Decimal (DWord): {val_int}")
            print(f"  • Float (Real)   : {val_float:.4f}")
            print(f"  • Hexadecimal    : 0x{hex_str}")
        print("=" * 55)

    async def run_status(self, watch=False):
        if not watch:
            print(f"[*] Consultando estado operativo y E/S en la CPU {self.plc_addr}...")
            data = await self.get_status_data()
            await self.display_status(data)
        else:
            print(f"[*] Modo monitor continuo activo (Ctrl+C para salir)...")
            last_valid_data = None
            try:
                while True:
                    data = await self.get_status_data()
                    if data is not None:
                        last_valid_data = data
                    os.system('clear')
                    await self.display_status(data if data is not None else last_valid_data)
                    await asyncio.sleep(0.15)
            except asyncio.CancelledError:
                pass

async def async_main():
    parser = argparse.ArgumentParser(description="Control y Monitor de E/S S7-200 por Bluetooth LE")
    parser.add_argument("command", choices=["status", "run", "stop", "io", "read"], help="Acción a realizar")
    parser.add_argument("variable", nargs="?", default="SMB28", help="Variable a leer con 'read' (ej: SMB28, VW100, MB0)")
    parser.add_argument("-w", "--watch", action="store_true", help="Monitor continuo en bucle")
    parser.add_argument("--address", default=DEFAULT_MAC, help=f"Dirección MAC BLE (default: {DEFAULT_MAC})")
    parser.add_argument("--plc", type=int, default=PLC_ADDR, help=f"Dirección de la CPU (default: {PLC_ADDR})")
    args = parser.parse_args()

    cmd = args.command
    if cmd == "io":
        cmd = "status"

    controller = BlePlcController(target_address=args.address, plc_addr=args.plc)
    try:
        await controller.connect()
        if cmd == "status":
            await controller.run_status(watch=args.watch)
        elif cmd == "run":
            await controller.set_mode("RUN")
        elif cmd == "stop":
            await controller.set_mode("STOP")
        elif cmd == "read":
            await controller.read_variable(args.variable)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"[-] Error: {e}")
    finally:
        await controller.disconnect()

def main():
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
