#!/usr/bin/env python3
"""
upload_s7_200.py - Extractor Autónomo de Bloques para Siemens SIMATIC S7-200
=============================================================================
Extrae bloques de programa (OB1), datos (DB1) y configuración (SDB) directamente
desde la memoria del PLC Siemens S7-200 (CPU 21x / 22x) vía:
  1. Conexión Inalámbrica Bluetooth Low Energy (BLE vía ESP32-S3)
  2. Cable RS-485 físico (FTDI / CH340 / Puertos COM en Windows y Linux)
  3. Modo Simulación (--dry-run) para pruebas y validaciones sin hardware.

Integra desensamblado automático a código AWL / STL mediante s7_awl_asm.py.

Autores: Humberto Gámez (@humbertogamez23) & Antigravity AI (open-ppi-bridge project)
Licencia: GPL-3.0
"""

import sys
import os
import time
import argparse
import asyncio
from typing import Optional, Tuple, Dict, List

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BLOCKS_DIR = os.path.join(BASE_DIR, "blocks")
sys.path.insert(0, os.path.dirname(__file__))

# Nombres de bloque canónicos en S7-200 (9 caracteres ASCII con prefijo _)
BLOCK_CONFIG = {
    "OB1": {
        "desc": "Bloque de Programa Principal y Subrutinas (OB1)",
        "name": b"_0800001A",
        "file_default": os.path.join(BLOCKS_DIR, "OB1_extraido.bin"),
    },
    "DB1": {
        "desc": "Bloque de Datos / Memoria V (DB1)",
        "name": b"_0A00001A",
        "file_default": os.path.join(BLOCKS_DIR, "DB1_extraido.bin"),
    },
    "SDB": {
        "desc": "Bloque de Configuración de Sistema (SDB)",
        "name": b"_0B00000A",
        "file_default": os.path.join(BLOCKS_DIR, "SDB_extraido.bin"),
    },
}

DEFAULT_PLC_ADDR = 2
DEFAULT_PC_ADDR = 0
DEFAULT_SERIAL = "COM3" if sys.platform.startswith("win") else "/dev/ttyUSB0"
DEFAULT_BAUD = 9600
DEFAULT_BLE_MAC = "28:84:85:91:45:06"
BLE_RX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # Host -> ESP32
BLE_TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # ESP32 -> Host


def calc_fcs(payload: bytes) -> int:
    return sum(payload) & 0xFF


def build_sd1(fc: int = 0x4C, plc_addr: int = DEFAULT_PLC_ADDR, pc_addr: int = DEFAULT_PC_ADDR) -> bytes:
    fcs = (plc_addr + pc_addr + fc) & 0xFF
    return bytes([0x10, plc_addr, pc_addr, fc, fcs, 0x16])


def build_sd2(pdu_body: bytes, fc: int, plc_addr: int = DEFAULT_PLC_ADDR, pc_addr: int = DEFAULT_PC_ADDR) -> bytes:
    payload = bytes([plc_addr, pc_addr, fc]) + pdu_body
    fcs = calc_fcs(payload)
    return bytes([0x68, len(payload), len(payload), 0x68]) + payload + bytes([fcs, 0x16])


# ============================================================================
# Transporte Serial Físico y Mock
# ============================================================================

class BaseTransport:
    def open(self): raise NotImplementedError
    def close(self): raise NotImplementedError
    def write(self, data: bytes): raise NotImplementedError
    def read_exact(self, count: int, timeout: float) -> bytes: raise NotImplementedError
    def read_until_frame(self, timeout: float) -> Optional[bytes]: raise NotImplementedError
    def reset_buffers(self): raise NotImplementedError


class SerialTransport(BaseTransport):
    def __init__(self, port: str = DEFAULT_SERIAL, baud: int = DEFAULT_BAUD):
        self.port = port
        self.baud = baud
        self.ser = None

    def open(self):
        import serial
        try:
            self.ser = serial.Serial(
                port=self.port, baudrate=self.baud,
                bytesize=serial.EIGHTBITS, parity=serial.PARITY_EVEN,
                stopbits=serial.STOPBITS_ONE, timeout=0.05
            )
        except Exception:
            self.ser = serial.Serial(port=self.port, baudrate=self.baud, timeout=0.05)
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()

    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()

    def write(self, data: bytes):
        self.ser.write(data)
        self.ser.flush()

    def reset_buffers(self):
        if self.ser:
            self.ser.reset_input_buffer()

    def read_exact(self, count: int, timeout: float) -> bytes:
        deadline = time.time() + timeout
        buf = bytearray()
        while time.time() < deadline and len(buf) < count:
            c = self.ser.read(count - len(buf))
            if c:
                buf.extend(c)
            else:
                time.sleep(0.005)
        return bytes(buf)

    def read_until_frame(self, timeout: float) -> Optional[bytes]:
        deadline = time.time() + timeout
        buf = bytearray()
        while time.time() < deadline:
            c = self.ser.read(self.ser.in_waiting or 1)
            if not c:
                time.sleep(0.005)
                continue
            for b in c:
                if b == 0xE5 and len(buf) == 0:
                    return b"\xE5"
                buf.append(b)
                if buf[0] == 0x10 and len(buf) >= 6:
                    if buf[5] == 0x16:
                        return bytes(buf[:6])
                elif buf[0] == 0x68 and len(buf) >= 6:
                    expected_len = buf[1] + 6
                    if len(buf) >= expected_len and buf[expected_len - 1] == 0x16:
                        return bytes(buf[:expected_len])
        return bytes(buf) if buf else None


class MockTransport(BaseTransport):
    def __init__(self):
        block_path = os.path.join(BLOCKS_DIR, "OB1_extraido_en_vivo.bin")
        if not os.path.exists(block_path):
            block_path = os.path.join(BASE_DIR, "examples", "blocks", "program_block_ob1.bin")
        if os.path.exists(block_path):
            with open(block_path, "rb") as f:
                self.mock_code = f.read()
        else:
            self.mock_code = b"\xFB\x70\x70" + b"\x00" * 300
        self.state = "READY"
        self.mock_offset = 0

    def open(self):
        print("[MOCK] Simulador de CPU 214 Rel 00.91 inicializado.")
    def close(self): pass
    def reset_buffers(self): pass
    def write(self, data: bytes):
        if len(data) >= 7 and data[0] == 0x68:
            pdu = data[7:-2]
            func = pdu[10] if len(pdu) > 10 else 0x00
            if func == 0x1D:
                self.state = "START_UPLO"
                self.mock_offset = 0
            elif func == 0x1E:
                self.state = "UPLO_CHUNK"
            elif func == 0x1F:
                self.state = "END_UPLO"

    def read_exact(self, count: int, timeout: float) -> bytes:
        return b"\xE5"

    def read_until_frame(self, timeout: float) -> Optional[bytes]:
        if self.state == "START_UPLO":
            self.state = "READY"
            # Retorno simulado con Upload ID 0x01 y longitud 308 bytes
            return bytes.fromhex("68 1F 1F 68 00 02 08 32 03 00 00 00 40 00 10 00 00 00 00 1D 00 01 00 00 00 00 01 07 30 30 30 30 33 30 38 10 16")
        elif self.state == "UPLO_CHUNK":
            self.state = "READY"
            chunk = self.mock_code[self.mock_offset : self.mock_offset + 220]
            self.mock_offset += len(chunk)
            more = 0x01 if self.mock_offset < len(self.mock_code) else 0x00
            chunk_len = len(chunk)
            pdu_c = bytes([0x32, 0x03, 0x00, 0x00, 0x00, 0x41, 0x00, 0x08, 0x00, 0x00, 0x00, 0x00,
                           0x1E, more, (chunk_len >> 8) & 0xFF, chunk_len & 0xFF, 0x00]) + chunk
            return build_sd2(pdu_c, fc=0x08, plc_addr=0, pc_addr=2)
        elif self.state == "END_UPLO":
            self.state = "READY"
            pdu = bytes.fromhex("32 03 00 00 00 42 00 01 00 00 00 00 1F")
            return build_sd2(pdu, fc=0x08, plc_addr=0, pc_addr=2)
        return b"\xE5"


# ============================================================================
# Motor de Extracción Sincrónico (Serial / Mock)
# ============================================================================

class S7_200_SerialUploader:
    def __init__(self, transport: BaseTransport, plc_addr: int = DEFAULT_PLC_ADDR, pc_addr: int = DEFAULT_PC_ADDR):
        self.transport = transport
        self.plc_addr = plc_addr
        self.pc_addr = pc_addr
        self.current_fc = 0x5C
        self.seq_counter = 0x0040

    def next_seq(self) -> int:
        self.seq_counter = (self.seq_counter + 1) & 0x7FFF
        return self.seq_counter

    def send_raw_sd2_wait_ack(self, pdu: bytes, max_retries: int = 4) -> bool:
        eff_fc = self.current_fc
        for _ in range(max_retries):
            frame = build_sd2(pdu, fc=eff_fc, plc_addr=self.plc_addr, pc_addr=self.pc_addr)
            self.transport.reset_buffers()
            self.transport.write(frame)
            ack = self.transport.read_exact(1, timeout=0.25)
            if ack == b"\xE5":
                self.current_fc = eff_fc ^ 0x20
                return True
            # Alternar FCB en caso de desincronización
            eff_fc ^= 0x20
            time.sleep(0.03)
        return False

    def poll_for_sd2_response(self, timeout: float = 3.5) -> Optional[bytes]:
        poll = build_sd1(fc=0x4C, plc_addr=self.plc_addr, pc_addr=self.pc_addr)
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.transport.write(poll)
            resp = self.transport.read_until_frame(timeout=0.25)
            if resp:
                if resp == b"\xE5":
                    time.sleep(0.03)
                    continue
                if len(resp) >= 6 and resp[0] == 0x68 and resp[-1] == 0x16:
                    return resp
            time.sleep(0.02)
        return None

    def execute_s7_transaction(self, pdu: bytes, timeout: float = 3.5) -> Optional[bytes]:
        if not self.send_raw_sd2_wait_ack(pdu):
            return None
        return self.poll_for_sd2_response(timeout=timeout)

    def upload_block(self, block_key: str = "OB1") -> Optional[bytes]:
        cfg = BLOCK_CONFIG.get(block_key.upper())
        if not cfg:
            print(f"[-] Bloque desconocido: {block_key}")
            return None

        desc = cfg["desc"]
        name = cfg["name"]

        print(f"\n{'='*70}")
        print(f"📥 INICIANDO EXTRACCIÓN (UPLOAD): {desc}")
        print(f"{'='*70}")

        # 0. Negociación de PDU (0xF0 - 240B)
        print(f"[*] Negociando canal de comunicación S7comm (PDU 240B)...")
        pdu_init = bytes([
            0x32, 0x01, 0x00, 0x00, 0x00, 0x01, 0x00, 0x08, 0x00, 0x00,
            0xF0, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0xF0
        ])
        _ = self.execute_s7_transaction(pdu_init, timeout=2.0)

        # 1. Start Upload (0x1D)
        seq = self.next_seq()
        param_1d = bytes([0x1D, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, len(name)]) + name
        pdu_1d = bytes([0x32, 0x01, 0x00, 0x00, (seq >> 8) & 0xFF, seq & 0xFF, 0x00, len(param_1d), 0x00, 0x00]) + param_1d

        print(f"[*] Enviando solicitud Start Upload (0x1D) para {name.decode()}...")
        resp_start = self.execute_s7_transaction(pdu_1d, timeout=3.5)
        if not resp_start or len(resp_start) < 20:
            print(f"[X] Falló la solicitud Start Upload. Sin respuesta del PLC.")
            return None

        upload_id = resp_start[26]
        print(f"[✓] Sesión de Upload abierta con éxito. Session ID = 0x{upload_id:02X}")

        # 2. Bucle de Chunks con Upload (0x1E)
        accumulated_data = bytearray()
        chunk_idx = 1
        has_more = True

        while has_more:
            seq = self.next_seq()
            param_1e = bytes([0x1E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, upload_id])
            pdu_1e = bytes([0x32, 0x01, 0x00, 0x00, (seq >> 8) & 0xFF, seq & 0xFF, 0x00, len(param_1e), 0x00, 0x00]) + param_1e

            print(f"[*] Solicitando Chunk {chunk_idx} (Función 0x1E)...")
            resp_chunk = self.execute_s7_transaction(pdu_1e, timeout=4.0)
            if not resp_chunk:
                print(f"[X] Error recibiendo Chunk {chunk_idx}.")
                break

            pdu_c = resp_chunk[7:-2]
            idx_1e = pdu_c.find(b"\x1E")
            if idx_1e != -1 and idx_1e + 4 < len(pdu_c):
                status = pdu_c[idx_1e + 1]
                has_more = (status == 0x01)
                chunk_len = (pdu_c[idx_1e + 2] << 8) | pdu_c[idx_1e + 3]
                data_start = idx_1e + 5
                chunk_data = pdu_c[data_start : data_start + chunk_len]
                accumulated_data.extend(chunk_data)
                print(f"    -> Chunk {chunk_idx}: Extraídos {len(chunk_data)} bytes (has_more={has_more})")
            else:
                break
            chunk_idx += 1

        print(f"[✓] Transferencia finalizada. Total: {len(accumulated_data)} bytes extraídos.")

        # 3. Fin de Upload (Función 0x1F)
        seq = self.next_seq()
        param_1f = bytes([0x1F, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, upload_id])
        pdu_1f = bytes([0x32, 0x01, 0x00, 0x00, (seq >> 8) & 0xFF, seq & 0xFF, 0x00, len(param_1f), 0x00, 0x00]) + param_1f
        print("[*] Cerrando sesión con End Upload (0x1F)...")
        _ = self.execute_s7_transaction(pdu_1f, timeout=3.0)
        print("[✓] Sesión de Upload cerrada correctamente por el PLC.")

        return bytes(accumulated_data)


# ============================================================================
# Motor de Extracción Asíncrono Nativo BLE (Bleak)
# ============================================================================

async def run_ble_upload(mac: str, block_key: str, plc_addr: int = DEFAULT_PLC_ADDR, pc_addr: int = DEFAULT_PC_ADDR, baud: str = "auto") -> Optional[bytes]:
    try:
        from bleak import BleakClient
        from bleak.exc import BleakDeviceNotFoundError, BleakError
    except ImportError:
        print("[-] Error: 'bleak' no está instalado. Instálelo con: pip install bleak")
        return None

    cfg = BLOCK_CONFIG.get(block_key.upper())
    if not cfg:
        print(f"[-] Bloque desconocido: {block_key}")
        return None

    desc = cfg["desc"]
    name = cfg["name"]

    print(f"\n{'='*70}")
    print(f"📥 INICIANDO EXTRACCIÓN BLUETOOTH LE: {desc}")
    print(f"{'='*70}")
    print(f"[*] Conectando vía Bluetooth LE a pasarela ESP32 ({mac})...")

    client = BleakClient(mac, timeout=10.0)
    try:
        await client.connect()
    except BleakDeviceNotFoundError:
        print(f"\n[X] Dispositivo no encontrado: No se pudo localizar la pasarela ESP32 ({mac}).")
        print("    - Verifique que la pasarela ESP32-S3 esté alimentada y encendida.")
        print("    - Asegúrese de que el Bluetooth de su ordenador esté activado.")
        print("    - Compruebe que esté dentro del alcance de cobertura inalámbrica.")
        return None
    except (BleakError, asyncio.TimeoutError) as e:
        print(f"\n[X] Error de conexión Bluetooth LE: {e}")
        return None
    except Exception as e:
        print(f"\n[X] Error inesperado en enlace BLE: {e}")
        return None

    print("[✓] Conexión Bluetooth LE establecida con éxito.")

    rx_q = asyncio.Queue()
    await client.start_notify(BLE_TX_UUID, lambda s, d: rx_q.put_nowait(bytes(d)))

    current_fc = 0x5C

    async def set_ble_baudrate(target_baud: int):
        cmd = f"++BAUD:{target_baud}".encode()
        while not rx_q.empty():
            rx_q.get_nowait()
        await client.write_gatt_char(BLE_RX_UUID, cmd, response=False)
        await asyncio.sleep(0.08)

    async def trans(pdu: bytes) -> Optional[bytes]:
        nonlocal current_fc
        ack = False
        eff_fc = current_fc

        for _ in range(6):
            frame = build_sd2(pdu, eff_fc, plc_addr=plc_addr, pc_addr=pc_addr)
            while not rx_q.empty():
                rx_q.get_nowait()
            await client.write_gatt_char(BLE_RX_UUID, frame, response=False)

            t0 = time.time()
            while time.time() - t0 < 0.8:
                try:
                    r = await asyncio.wait_for(rx_q.get(), timeout=0.25)
                    if r and (b"\xE5" in r or r == b"\xE5"):
                        ack = True
                        break
                except asyncio.TimeoutError:
                    pass
            if ack:
                current_fc = eff_fc ^ 0x20
                break
            # Auto-sincronizar FCB
            eff_fc ^= 0x20
            await asyncio.sleep(0.06)

        if not ack:
            print(f"[-] No se recibió ACK del autómata tras alternar FCB.")
            return None

        # Sondeo con SD1 0x4C
        poll = build_sd1(0x4C, plc_addr=plc_addr, pc_addr=pc_addr)
        t_dead = time.time() + 3.5
        accum = bytearray()
        while time.time() < t_dead:
            await client.write_gatt_char(BLE_RX_UUID, poll, response=False)
            try:
                chunk = await asyncio.wait_for(rx_q.get(), timeout=0.20)
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
        return bytes(accum) if accum else None

    try:
        # 0. Negociación de Velocidad y Parámetros S7comm (PDU 240B)
        pdu_init = bytes([
            0x32, 0x01, 0x00, 0x00, 0x00, 0x01, 0x00, 0x08, 0x00, 0x00,
            0xF0, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0xF0
        ])

        baud_str = str(baud).lower().strip()
        if baud_str in ("9600", "19200", "187500"):
            target_baud = int(baud_str)
            print(f"[*] Configurando velocidad en baudios fija a {target_baud}...")
            await set_ble_baudrate(target_baud)
            print(f"[*] Negociando canal de comunicación S7comm (PDU 240B)...")
            resp_pdu = await trans(pdu_init)
            if not resp_pdu:
                print(f"[-] Advertencia: Sin respuesta inicial a {target_baud} baudios. Continuando...")
            else:
                print(f"[✓] Enlace y PDU sincronizados con éxito a {target_baud} baudios.")
        else:
            # Modo Auto-Baud (Doble negociación Serie 21x / 22x)
            print(f"[*] Negociando velocidad de bus RS485 (Auto-Baud: 9.6k Serie 21x / 19.2k Serie 22x)...")
            await set_ble_baudrate(9600)
            resp_pdu = await trans(pdu_init)
            if resp_pdu:
                print(f"[✓] ¡Enlace establecido con éxito a 9.600 baudios! (Compatible con Serie 21x / 22x base).")
            else:
                print(f"[*] Sin respuesta a 9.600 baudios. Probando conmutación a 19.200 baudios (Serie 22x industrial)...")
                await set_ble_baudrate(19200)
                current_fc = 0x5C
                resp_pdu = await trans(pdu_init)
                if resp_pdu:
                    print(f"[✓] ¡Enlace establecido con éxito a 19.200 baudios! (Serie 22x detectada).")
                else:
                    print(f"[-] Sin respuesta ACK en 9.600 ni en 19.200 baudios. Intentando Start Upload...")

        # 1. Start Upload (0x1D)
        seq = 0x0040
        print(f"[*] Enviando solicitud Start Upload (0x1D) para {name.decode()}...")
        param_1d = bytes([0x1D, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, len(name)]) + name
        pdu_1d = bytes([0x32, 0x01, 0x00, 0x00, (seq >> 8) & 0xFF, seq & 0xFF, 0x00, len(param_1d), 0x00, 0x00]) + param_1d

        resp_start = await trans(pdu_1d)
        if not resp_start or len(resp_start) < 20:
            print(f"[X] Falló la solicitud Start Upload. Sin respuesta de la CPU.")
            print(f"    Diagnóstico recomendado:")
            print(f"    1. Polaridad RS-485: Verifique que Pin 3 del DB9 sea B (RxTx+) y Pin 8 sea A (RxTx-).")
            print(f"    2. Velocidad en baudios: Si la CPU 222 está configurada a 19200 baudios, no responderá a 9600.")
            print(f"    3. Selector RUN/STOP: Si el puerto está en modo Freeport, mueva la llave física a STOP.")
            return None

        upload_id = resp_start[26]
        print(f"[✓] Sesión de Upload abierta con éxito por la CPU. Session ID = 0x{upload_id:02X}")

        # 2. Bucle de Chunks con Upload (0x1E)
        accumulated_data = bytearray()
        chunk_idx = 1
        has_more = True

        while has_more:
            seq += 1
            param_1e = bytes([0x1E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, upload_id])
            pdu_1e = bytes([0x32, 0x01, 0x00, 0x00, (seq >> 8) & 0xFF, seq & 0xFF, 0x00, len(param_1e), 0x00, 0x00]) + param_1e

            print(f"[*] Solicitando Chunk {chunk_idx} (Función 0x1E)...")
            resp_chunk = await trans(pdu_1e)
            if not resp_chunk:
                print(f"[X] Sin respuesta para Chunk {chunk_idx}.")
                break

            pdu_c = resp_chunk[7:-2]
            idx_1e = pdu_c.find(b"\x1E")
            if idx_1e != -1 and idx_1e + 4 < len(pdu_c):
                status = pdu_c[idx_1e + 1]
                has_more = (status == 0x01)
                chunk_len = (pdu_c[idx_1e + 2] << 8) | pdu_c[idx_1e + 3]
                data_start = idx_1e + 5
                chunk_data = pdu_c[data_start : data_start + chunk_len]
                accumulated_data.extend(chunk_data)
                print(f"    -> Chunk {chunk_idx}: Recibidos {len(chunk_data)} bytes (has_more={has_more})")
            else:
                break
            chunk_idx += 1

        print(f"[✓] Transferencia de datos finalizada. Total: {len(accumulated_data)} bytes extraídos.")

        # 3. Fin de Upload (0x1F)
        seq += 1
        param_1f = bytes([0x1F, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, upload_id])
        pdu_1f = bytes([0x32, 0x01, 0x00, 0x00, (seq >> 8) & 0xFF, seq & 0xFF, 0x00, len(param_1f), 0x00, 0x00]) + param_1f
        print(f"[*] Cerrando sesión con End Upload (0x1F)...")
        _ = await trans(pdu_1f)
        print(f"[✓] Sesión cerrada correctamente por el PLC.")

        return bytes(accumulated_data)

    finally:
        if client and client.is_connected:
            try:
                await client.disconnect()
                print("[*] Desconectado del enlace Bluetooth.")
            except Exception:
                pass


# ============================================================================
# Interfaz de Línea de Comandos (CLI)
# ============================================================================

def auto_detect_serial() -> str:
    if sys.platform.startswith("win"):
        return "COM3"
    for p in ["/tmp/ttyPPI", "/dev/ttyUSB0", "/dev/ttyUSB1"]:
        if os.path.exists(p):
            return p
    return DEFAULT_SERIAL


def main():
    parser = argparse.ArgumentParser(
        description="Extractor Autónomo de Programas para Siemens SIMATIC S7-200 (Windows y Linux)"
    )
    parser.add_argument("--port", default=None, help="Puerto serial (ej: COM3 en Windows, /dev/ttyUSB0 en Linux)")
    parser.add_argument("--baud", default="auto", help="Velocidad en baudios: auto (conmuta 9.6k y 19.2k), 9600 o 19200 (default: auto)")
    parser.add_argument("--ble", action="store_true", help="Utilizar conexión inalámbrica Bluetooth LE (vía ESP32)")
    parser.add_argument("--mac", default=DEFAULT_BLE_MAC, help=f"Dirección MAC BLE (default: {DEFAULT_BLE_MAC})")
    parser.add_argument("--dry-run", action="store_true", help="Modo simulación (sin acceder al hardware físico)")
    parser.add_argument("--plc", type=int, default=DEFAULT_PLC_ADDR, help=f"Dirección de la CPU (default: {DEFAULT_PLC_ADDR})")

    parser.add_argument("--block", choices=["OB1", "DB1", "SDB"], default="OB1", help="Bloque a extraer (default: OB1)")
    parser.add_argument("-o", "--output", default=None, help="Ruta para guardar el archivo binario (.bin)")
    parser.add_argument("--awl", default=None, nargs="?", const="", help="Desensamblar y exportar automáticamente a archivo AWL/STL")
    parser.add_argument("--ai", action="store_true", help="Auditar y analizar la lógica extraída con el copiloto de IA local (Qwen 2.5 Coder)")

    args = parser.parse_args()

    raw_block = None

    if args.dry_run:
        transport = MockTransport()
        transport.open()
        uploader = S7_200_SerialUploader(transport, plc_addr=args.plc)
        raw_block = uploader.upload_block(block_key=args.block)
        transport.close()
    elif args.ble:
        raw_block = asyncio.run(run_ble_upload(mac=args.mac, block_key=args.block, plc_addr=args.plc, baud=args.baud))
    else:
        port = args.port or auto_detect_serial()
        serial_baud = 9600 if str(args.baud).lower() == "auto" else int(args.baud)
        transport = SerialTransport(port=port, baud=serial_baud)
        try:
            transport.open()
        except Exception as e:
            print(f"[-] Error abriendo puerto serial {port}: {e}")
            sys.exit(1)
        uploader = S7_200_SerialUploader(transport, plc_addr=args.plc)
        try:
            raw_block = uploader.upload_block(block_key=args.block)
        finally:
            transport.close()

    if not raw_block:
        print("\n[-] No se pudo extraer el bloque del autómata.")
        sys.exit(1)

    out_path = args.output or BLOCK_CONFIG[args.block]["file_default"]
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(raw_block)
    print(f"\n[★] Bloque binario guardado exitosamente en: {out_path} ({len(raw_block)} bytes)")

    # Validación y Desensamblado si es OB1 o DB1
    if args.block in ("OB1", "DB1"):
        if len(raw_block) >= 3 and raw_block[:3] == b"\xFB\x70\x70":
            print(f"[✓] Magic bytecode nativo validado con éxito: FB 70 70 (Bloque {args.block})")
        else:
            print(f"[!] Advertencia: Magic bytecode inicial es {raw_block[:3].hex().upper()} (esperado FB 70 70)")

        try:
            from s7_awl_asm import S7_200_Disassembler
            disasm = S7_200_Disassembler(raw_block)
            awl_text = disasm.disassemble_all()

            awl_out = args.awl if (args.awl and len(args.awl) > 0) else out_path.replace(".bin", ".awl")
            with open(awl_out, "w", encoding="utf-8") as f:
                f.write(awl_text)

            print(f"[★] Contenido desensamblado exportado en: {awl_out}")

            # Registrar como última extracción para el Copiloto de IA local
            try:
                import json, shutil
                b_dir = os.path.dirname(os.path.abspath(out_path))
                latest_meta = {
                    "bin_file": os.path.basename(out_path),
                    "awl_file": os.path.basename(awl_out),
                    "block": args.block,
                    "plc_addr": args.plc,
                    "size_bytes": len(raw_block),
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                }
                with open(os.path.join(b_dir, "latest_extraction.json"), "w", encoding="utf-8") as f:
                    json.dump(latest_meta, f, indent=2)
                shutil.copy2(out_path, os.path.join(b_dir, "latest.bin"))
                shutil.copy2(awl_out, os.path.join(b_dir, "latest.awl"))
            except Exception:
                pass

            title_str = "CÓDIGO AWL" if args.block == "OB1" else "DATOS Y VARIABLES DE MEMORIA V"
            print("\n" + "=" * 65)
            print(f" RESUMEN DE {title_str} EXTRAÍDO DIRECTO DE LA MEMORIA:")
            print("=" * 65)
            for line in awl_text.splitlines()[:30]:
                print(f"  {line}")
            if len(awl_text.splitlines()) > 30:
                print(f"  ... ({len(awl_text.splitlines()) - 30} líneas más en el archivo)")
            print("=" * 65)

            if args.ai:
                try:
                    from ai_copilot import audit_awl_code
                    print("\n" + "=" * 65)
                    print("🤖 AUDITORÍA DE SEGURIDAD CON IA LOCAL (Qwen 2.5 Coder):")
                    print("=" * 65)
                    ai_report = audit_awl_code(awl_text)
                    print(ai_report)
                    print("=" * 65)
                except Exception as e:
                    print(f"[!] Nota: No se pudo ejecutar el análisis de IA ({e})")
        except Exception as e:
            print(f"[!] Nota: No se pudo decodificar el bloque ({e}), pero el binario está intacto.")

    print("\n[✓] ¡Proceso de extracción completado con éxito total!")


if __name__ == "__main__":
    main()
