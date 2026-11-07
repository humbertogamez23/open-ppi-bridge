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


CPU_PROFILES = {
    0x00: {
        "name": "CPU 212",
        "family": "Serie 21x Legacy (Micro-PLC)",
        "in_base": [(0, "I0", 8, "IB0")],                # 8 DI (I0.0 - I0.7)
        "out_base": [(0, "Q0", 6, "QB0")],               # 6 DO (Q0.0 - Q0.5)
        "exp_in_start": 1,
        "exp_out_start": 1,
    },
    0x01: {
        "name": "CPU 214",
        "family": "Serie 21x Legacy (Compact PLC)",
        "in_base": [(0, "I0", 8, "IB0"), (1, "I1", 6, "IB1")],  # 14 DI (I0.0 - I0.7 y I1.0 - I1.5)
        "out_base": [(0, "Q0", 8, "QB0"), (1, "Q1", 2, "QB1")], # 10 DO (Q0.0 - Q0.7 y Q1.0 - Q1.1)
        "exp_in_start": 2,
        "exp_out_start": 2,
    },
    0x02: {
        "name": "CPU 215",
        "family": "Serie 21x Legacy (Profibus-DP)",
        "in_base": [(0, "I0", 8, "IB0"), (1, "I1", 6, "IB1")],  # 14 DI
        "out_base": [(0, "Q0", 8, "QB0"), (1, "Q1", 2, "QB1")], # 10 DO
        "exp_in_start": 2,
        "exp_out_start": 2,
    },
    0x03: {
        "name": "CPU 216",
        "family": "Serie 21x Legacy (Dual Port)",
        "in_base": [(0, "I0", 8, "IB0"), (1, "I1", 8, "IB1"), (2, "I2", 8, "IB2")], # 24 DI
        "out_base": [(0, "Q0", 8, "QB0"), (1, "Q1", 8, "QB1")],                      # 16 DO
        "exp_in_start": 3,
        "exp_out_start": 2,
    },
    0x04: {
        "name": "CPU 221",
        "family": "Serie 22x Industrial",
        "in_base": [(0, "I0", 6, "IB0")],                # 6 DI (I0.0 - I0.5)
        "out_base": [(0, "Q0", 4, "QB0")],               # 4 DO (Q0.0 - Q0.3)
        "exp_in_start": None,
        "exp_out_start": None,
    },
    0x05: {
        "name": "CPU 222",
        "family": "Serie 22x Industrial",
        "in_base": [(0, "I0", 8, "IB0")],                # 8 DI (I0.0 - I0.7)
        "out_base": [(0, "Q0", 6, "QB0")],               # 6 DO (Q0.0 - Q0.5)
        "exp_in_start": 1,
        "exp_out_start": 1,
    },
    0x06: {
        "name": "CPU 224 / 224XP",
        "family": "Serie 22x Industrial",
        "in_base": [(0, "I0", 8, "IB0"), (1, "I1", 6, "IB1")],  # 14 DI (I0.0 - I0.7 y I1.0 - I1.5)
        "out_base": [(0, "Q0", 8, "QB0"), (1, "Q1", 2, "QB1")], # 10 DO (Q0.0 - Q0.7 y Q1.0 - Q1.1)
        "exp_in_start": 2,
        "exp_out_start": 2,
    },
    0x07: {
        "name": "CPU 226 / 226XM",
        "family": "Serie 22x Industrial (Dual Port)",
        "in_base": [(0, "I0", 8, "IB0"), (1, "I1", 8, "IB1"), (2, "I2", 8, "IB2")], # 24 DI
        "out_base": [(0, "Q0", 8, "QB0"), (1, "Q1", 8, "QB1")],                      # 16 DO
        "exp_in_start": 3,
        "exp_out_start": 2,
    },
}

class BlePlcController:
    def __init__(self, target_address=DEFAULT_MAC, plc_addr=PLC_ADDR, pc_addr=PC_ADDR, baud="auto"):
        self.target_address = target_address
        self.plc_addr = plc_addr
        self.pc_addr = pc_addr
        self.baud = baud
        self.client = None
        self.rx_queue = asyncio.Queue()

    def notification_handler(self, sender, data: bytearray):
        self.rx_queue.put_nowait(bytes(data))

    async def set_ble_baudrate(self, target_baud: int):
        cmd = f"++BAUD:{target_baud}".encode()
        while not self.rx_queue.empty():
            self.rx_queue.get_nowait()
        await self.client.write_gatt_char(RX_UUID, cmd, response=False)
        await asyncio.sleep(0.08)

    async def negotiate_connection(self):
        pdu_init = bytes([
            0x32, 0x01, 0x00, 0x00, 0x00, 0x01, 0x00, 0x08, 0x00, 0x00,
            0xF0, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0xF0
        ])
        baud_str = str(self.baud).lower().strip()
        if baud_str in ("9600", "19200", "187500"):
            target_baud = int(baud_str)
            print(f"[*] Configurando velocidad en baudios fija a {target_baud}...")
            await self.set_ble_baudrate(target_baud)
            await self.send_s7_request(pdu_init, timeout=1.8)
        else:
            print("[*] Negociando velocidad de bus RS485 (Auto-Baud 9.6k / 19.2k)...")
            await self.set_ble_baudrate(9600)
            resp = await self.send_s7_request(pdu_init, timeout=1.6)
            if resp:
                self.current_baud = 9600
                print("[✓] Enlace sincronizado a 9.600 baudios.")
            else:
                print("[*] Sin respuesta a 9.600 bps. Conmutando a 19.200 baudios...")
                await self.set_ble_baudrate(19200)
                resp = await self.send_s7_request(pdu_init, timeout=1.8)
                if resp:
                    self.current_baud = 19200
                    print("[✓] Enlace sincronizado a 19.200 baudios.")

    async def connect(self):
        print(f"[*] Conectando vía Bluetooth LE a {DEFAULT_NAME} ({self.target_address})...")
        self.client = BleakClient(self.target_address, timeout=12.0)
        await self.client.connect()
        print(f"[✓] Enlace Bluetooth LE establecido con éxito.")
        await self.client.start_notify(TX_UUID, self.notification_handler)
        await self.negotiate_connection()

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
        """Obtiene una instantánea del estado, identificación de CPU, entradas y salidas."""
        # 1. Leer SMB0..SMB7 al inicio (Modo operativo, ID de CPU en SMB6, Firmware en SMB7)
        smb_data = await self.read_memory_area(area_code=0x05, start_byte=0, count=8, seq=1)
        if smb_data is None or len(smb_data) < 8:
            await asyncio.sleep(0.06)
            smb_data = await self.read_memory_area(area_code=0x05, start_byte=0, count=8, seq=1)

        await asyncio.sleep(0.04)

        # 2. Leer Entradas Digitales (5 bytes: IB0 a IB4 para cubrir base y expansiones)
        inputs = await self.read_memory_area(area_code=0x81, start_byte=0, count=5, seq=2)
        await asyncio.sleep(0.04)

        # 3. Leer Salidas Digitales (5 bytes: QB0 a QB4)
        outputs = await self.read_memory_area(area_code=0x82, start_byte=0, count=5, seq=3)
        await asyncio.sleep(0.04)

        # 4. Leer Potenciómetros Analógicos (SMB28, SMB29)
        pots = await self.read_memory_area(area_code=0x05, start_byte=28, count=2, seq=4)
        await asyncio.sleep(0.04)

        # 5. Segunda lectura de SMB0 para detección dinámica de ciclo de scan
        smb0_end = await self.read_memory_area(area_code=0x05, start_byte=0, count=1, seq=5)

        smb0 = smb_data[0] if smb_data and len(smb_data) > 0 else None
        smb6 = smb_data[6] if smb_data and len(smb_data) > 6 else None
        smb7 = smb_data[7] if smb_data and len(smb_data) > 7 else None
        smb0_end_val = smb0_end[0] if smb0_end and len(smb0_end) > 0 else None

        # Detección dinámica de ciclo de scan:
        # En RUN, SM0.6 (Scan Clock, bit 6) y SM0.5 (1s Clock, bit 5) oscilan en cada scan.
        # En STOP, el microprocesador está detenido y el registro permanece 100% congelado.
        switch_run = bool(smb0 & 0x80) if smb0 is not None else False
        scan_active = False

        if smb0 is not None and smb0_end_val is not None:
            if smb0 != smb0_end_val:
                scan_active = True
            else:
                # Comprobación de confirmación (3ra muestra separada 40ms)
                await asyncio.sleep(0.04)
                smb0_check = await self.read_memory_area(area_code=0x05, start_byte=0, count=1, seq=6)
                if smb0_check and smb0_check[0] != smb0_end_val:
                    scan_active = True

        is_run = switch_run or scan_active

        return {
            "smb0": smb0,
            "smb6": smb6,
            "smb7": smb7,
            "is_run": is_run,
            "switch_run": switch_run,
            "inputs": inputs,
            "outputs": outputs,
            "pots": pots
        }

    async def display_status(self, data, show_all_exp: bool = False):
        print("\n" + "=" * 65)
        print("          ESTADO INTEGRAL SIEMENS S7-200 [BLUETOOTH LE]")
        print("=" * 65)
        print(f"  • Enlace Inalámbrico : \033[92mCONECTADO (Bluetooth LE OK)\033[0m")
        print(f"  • Dispositivo        : {DEFAULT_NAME} ({self.target_address})")
        print(f"  • Dirección CPU      : {self.plc_addr}")

        if data is None:
            print(f"  • Estado del PLC     : \033[93mSIN RESPUESTA EN BUS RS485\033[0m")
            print(f"                         (PLC apagado o desconectado del módulo FTDI)")
            print("=" * 65)
            return

        # 1. Identificar modelo de CPU según SMB6
        smb6 = data.get("smb6")
        cpu_id = (smb6 & 0x0F) if smb6 is not None else 0x01  # Default CPU 214 si no se lee
        profile = CPU_PROFILES.get(cpu_id, CPU_PROFILES[0x01])

        fw_info = ""
        smb7 = data.get("smb7")
        if smb7 is not None and smb7 != 0:
            fw_info = f" [FW Rel. {smb7:02X}]"

        print(f"  • Modelo Detectado   : \033[1;32m{profile['name']}\033[0m ({profile['family']}){fw_info}")

        # Modo de la CPU
        if "is_run" in data:
            is_run = data["is_run"]
            switch_run = data.get("switch_run", False)
            modo_str = "\033[92m● RUN (En Marcha)\033[0m" if is_run else "\033[91m■ STOP (Detenido)\033[0m"
            llave_str = "RUN (Física)" if switch_run else "TERM / STOP"
            print(f"  • Estado Operativo   : {modo_str}")
            print(f"  • Posición de Llave  : {llave_str}")
        else:
            print(f"  • Estado del PLC     : \033[92mONLINE\033[0m")

        # 2. Entradas Digitales (I)
        print("-" * 65)
        in_bytes = data.get("inputs") or b""
        total_di = sum(bits for _, _, bits, _ in profile["in_base"])
        print(f"  [ ENTRADAS DIGITALES BASE ({profile['name']} - {total_di} DI Integradas) ]")
        if in_bytes:
            for byte_idx, prefix, bits, byte_label in profile["in_base"]:
                if len(in_bytes) > byte_idx:
                    b_val = in_bytes[byte_idx]
                    note = f"  ({prefix}.0 a {prefix}.{bits-1})" if bits < 8 else ""
                    print(f"  • {profile['name']} Base ({byte_label}): {format_io_bits(b_val, prefix, bits)}{note}")
                else:
                    print(f"  • {profile['name']} Base ({byte_label}): (No disponible)")

            # Expansión de Entradas
            exp_in_start = profile["exp_in_start"]
            if exp_in_start is not None and len(in_bytes) > exp_in_start:
                exp_bytes = in_bytes[exp_in_start:]
                has_active = any(b != 0 for b in exp_bytes)
                if has_active or show_all_exp:
                    print("\n  [ MÓDULOS DE EXPANSIÓN (DI) ]")
                    for i, b_val in enumerate(exp_bytes):
                        real_byte = exp_in_start + i
                        print(f"  • Expansión #{i+1}   (IB{real_byte}): {format_io_bits(b_val, f'I{real_byte}', 8)}")
                else:
                    print(f"  • Expansión (IB{exp_in_start}..IB{len(in_bytes)-1}): Sin módulos adicionales activos (0x00)")
        else:
            print("    (No se pudieron consultar entradas)")

        # 3. Salidas Digitales (Q)
        print("-" * 65)
        out_bytes = data.get("outputs") or b""
        total_do = sum(bits for _, _, bits, _ in profile["out_base"])
        print(f"  [ SALIDAS DIGITALES BASE ({profile['name']} - {total_do} DO Integradas) ]")
        if out_bytes:
            for byte_idx, prefix, bits, byte_label in profile["out_base"]:
                if len(out_bytes) > byte_idx:
                    b_val = out_bytes[byte_idx]
                    note = f"  ({prefix}.0 a {prefix}.{bits-1})" if bits < 8 else ""
                    print(f"  • {profile['name']} Base ({byte_label}): {format_io_bits(b_val, prefix, bits)}{note}")
                else:
                    print(f"  • {profile['name']} Base ({byte_label}): (No disponible)")

            # Expansión de Salidas
            exp_out_start = profile["exp_out_start"]
            if exp_out_start is not None and len(out_bytes) > exp_out_start:
                exp_bytes = out_bytes[exp_out_start:]
                has_active = any(b != 0 for b in exp_bytes)
                if has_active or show_all_exp:
                    print("\n  [ MÓDULOS DE EXPANSIÓN (DO) ]")
                    for i, b_val in enumerate(exp_bytes):
                        real_byte = exp_out_start + i
                        print(f"  • Expansión #{i+1}   (QB{real_byte}): {format_io_bits(b_val, f'Q{real_byte}', 8)}")
                else:
                    print(f"  • Expansión (QB{exp_out_start}..QB{len(out_bytes)-1}): Sin módulos adicionales activos (0x00)")
        else:
            print("    (No se pudieron consultar salidas)")

        # 4. Potenciómetros analógicos
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

    async def get_plc_info(self):
        """Consulta el registro SMB6 y datos de sistema para identificar modelo y versión."""
        print(f"[*] Consultando registros de identificación en la CPU {self.plc_addr}...")
        smb_data = await self.read_memory_area(area_code=0x05, start_byte=0, count=8, seq=10)
        if not smb_data or len(smb_data) < 8:
            print("[-] No se pudo leer la información de identificación del PLC.")
            return

        smb0 = smb_data[0]
        smb6 = smb_data[6]
        smb7 = smb_data[7]

        cpu_id = smb6 & 0x0F
        profile = CPU_PROFILES.get(cpu_id, CPU_PROFILES[0x01])

        # Muestreo dinámico de ciclo de scan
        await asyncio.sleep(0.06)
        smb0_end = await self.read_memory_area(area_code=0x05, start_byte=0, count=1, seq=11)
        scan_active = False
        if smb0_end and smb0_end[0] != smb0:
            scan_active = True
        else:
            await asyncio.sleep(0.04)
            smb0_c = await self.read_memory_area(area_code=0x05, start_byte=0, count=1, seq=12)
            if smb0_c and smb0_c[0] != smb0:
                scan_active = True

        switch_run = bool(smb0 & 0x80)
        is_run = switch_run or scan_active
        switch_pos = "RUN (Física)" if switch_run else "TERM / STOP"
        baud_rate = getattr(self, "current_baud", 9600)

        fw_ver = f"Rel. {smb7:02X}" if smb7 != 0 else "Rel. 02.xx (Flash ROM nativa)"
        total_di = sum(bits for _, _, bits, _ in profile["in_base"])
        total_do = sum(bits for _, _, bits, _ in profile["out_base"])

        print("\n" + "=" * 65)
        print("      IDENTIFICACIÓN DE HARDWARE SIEMENS SIMATIC S7-200")
        print("=" * 65)
        print(f"  • Modelo de CPU        : \033[1;32m{profile['name']}\033[0m")
        print(f"  • Familia / Serie      : {profile['family']}")
        print(f"  • Registro SMB6 (ID)   : 0x{smb6:02X} (Código de CPU: {cpu_id})")
        print(f"  • Versión de Firmware  : {fw_ver}")
        print(f"  • E/S Integradas Base  : {total_di} DI / {total_do} DO")
        print(f"  • Velocidad Enlace     : {baud_rate} baudios (8E1)")
        print(f"  • Dirección de Estación: {self.plc_addr}")
        print(f"  • Estado Operativo     : {'\033[92m● RUN (En Marcha)\033[0m' if is_run else '\033[91m■ STOP (Detenido)\033[0m'}")
        print(f"  • Posición de Llave    : {switch_pos}")
        print("=" * 65)
        print("  💡 Nota Técnica:")
        print("  El modelo de CPU se lee directamente del registro de memoria")
        print("  especial SMB6 del firmware del autómata en tiempo de ejecución.")
        print("=" * 65)

    async def run_status(self, watch=False, show_all_exp=False):
        if not watch:
            print(f"[*] Consultando estado operativo y E/S en la CPU {self.plc_addr}...")
            data = await self.get_status_data()
            await self.display_status(data, show_all_exp=show_all_exp)
        else:
            print(f"[*] Modo monitor continuo activo (Ctrl+C para salir)...")
            last_valid_data = None
            try:
                while True:
                    data = await self.get_status_data()
                    if data is not None:
                        last_valid_data = data
                    os.system('clear' if os.name == 'posix' else 'cls')
                    await self.display_status(data if data is not None else last_valid_data, show_all_exp=show_all_exp)
                    await asyncio.sleep(0.15)
            except asyncio.CancelledError:
                pass

async def async_main():
    parser = argparse.ArgumentParser(description="Control y Monitor de E/S S7-200 por Bluetooth LE")
    parser.add_argument("command", choices=["status", "run", "stop", "io", "read", "info"], help="Acción a realizar")
    parser.add_argument("variable", nargs="?", default="SMB28", help="Variable a leer con 'read' (ej: SMB28, VW100, MB0)")
    parser.add_argument("-w", "--watch", action="store_true", help="Monitor continuo en bucle")
    parser.add_argument("--address", default=DEFAULT_MAC, help=f"Dirección MAC BLE (default: {DEFAULT_MAC})")
    parser.add_argument("--plc", type=int, default=PLC_ADDR, help=f"Dirección de la CPU (default: {PLC_ADDR})")
    parser.add_argument("--baud", default="auto", help="Velocidad en baudios: auto (conmuta 9.6k y 19.2k), 9600 o 19200 (default: auto)")
    parser.add_argument("--expansion", action="store_true", help="Forzar visualización de todos los canales de expansión (IB2..IB4 / QB2..QB4)")
    args = parser.parse_args()

    cmd = args.command
    if cmd == "io":
        cmd = "status"

    controller = BlePlcController(target_address=args.address, plc_addr=args.plc, baud=args.baud)
    try:
        await controller.connect()
        if cmd == "status":
            await controller.run_status(watch=args.watch, show_all_exp=args.expansion)
        elif cmd == "info":
            await controller.get_plc_info()
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
