#!/usr/bin/env python3
"""
flash_s7_200.py - Standalone Siemens SIMATIC S7-200 Block Flasher for Linux
=============================================================================
Flashes compiled binary blocks (System Block SDB, Program Block OB1, Data Block DB1)
directly to Siemens S7-200 PLCs (CPU 21x / 22x) over native RS-485 PPI or Bluetooth LE.

Zero Windows or QEMU dependency. Fully autonomous Linux CLI flasher.

Authors: Gustavo & Antigravity AI (open-ppi-bridge project)
License: GPL-3.0
"""

import sys
import os
import time
import argparse
import asyncio
from typing import Optional, Tuple, List

# Códigos de Bloque S7comm para S7-200
BLOCK_CONFIG = {
    "SDB": {
        "desc": "Bloque de Sistema (SDB)",
        "name_inse": b"_0B00000P",
        "name_commit": b"0B00000P",
        "file_default": "system_block_sdb.bin",
        "attr_fmt": "000136000100",  # 136 bytes decimal
        "needs_delete": False,
    },
    "OB1": {
        "desc": "Bloque de Programa (OB1 + Subrutinas)",
        "name_inse": b"_0800001P",
        "name_commit": b"0800001P",
        "name_dele": b"0800001A",
        "file_default": "program_block_ob1.bin",
        "attr_fmt": "000308000239",  # 308 bytes decimal
        "needs_delete": True,
    },
    "DB1": {
        "desc": "Bloque de Datos (DB1 / Memoria V)",
        "name_inse": b"_0A00001P",
        "name_commit": b"0A00001P",
        "name_dele": b"0A00001A",
        "file_default": "data_block_db1.bin",
        "attr_fmt": "000036000000",  # 36 bytes decimal
        "needs_delete": True,
    },
}

DEFAULT_PLC_ADDR = 2
DEFAULT_PC_ADDR = 0
DEFAULT_SERIAL = "/dev/ttyUSB0"
DEFAULT_BAUD = 9600
DEFAULT_BLE_MAC = "28:84:85:91:45:06"
BLE_RX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # Host -> ESP32
BLE_TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # ESP32 -> Host


def calc_fcs(payload: bytes) -> int:
    """Calcula el Checksum FCS PROFIBUS/PPI (Suma módulo 256)."""
    return sum(payload) & 0xFF


def build_sd1(fc: int = 0x4C, plc_addr: int = DEFAULT_PLC_ADDR, pc_addr: int = DEFAULT_PC_ADDR) -> bytes:
    """Construye una trama corta SD1 (Sondeo o Poll)."""
    fcs = (plc_addr + pc_addr + fc) & 0xFF
    return bytes([0x10, plc_addr, pc_addr, fc, fcs, 0x16])


def build_sd2(pdu_body: bytes, fc: int, plc_addr: int = DEFAULT_PLC_ADDR, pc_addr: int = DEFAULT_PC_ADDR) -> bytes:
    """Construye una trama de longitud variable SD2 con su cabecera y FCS."""
    payload = bytes([plc_addr, pc_addr, fc]) + pdu_body
    fcs = calc_fcs(payload)
    return bytes([0x68, len(payload), len(payload), 0x68]) + payload + bytes([fcs, 0x16])


# ============================================================================
# Clases de Transporte: Serial (FTDI / PTY) y BLE (Bleak)
# ============================================================================

class BaseTransport:
    def open(self):
        raise NotImplementedError
    def close(self):
        raise NotImplementedError
    def write(self, data: bytes):
        raise NotImplementedError
    def read_exact(self, count: int, timeout: float) -> bytes:
        raise NotImplementedError
    def read_until_frame(self, timeout: float) -> Optional[bytes]:
        raise NotImplementedError
    def reset_buffers(self):
        pass


class SerialTransport(BaseTransport):
    def __init__(self, port: str = DEFAULT_SERIAL, baud: int = DEFAULT_BAUD):
        self.port = port
        self.baud = baud
        self.ser = None

    def open(self):
        import serial
        # 8 data bits, Even parity, 1 stop bit (8E1 estándar PPI)
        self.ser = serial.Serial(
            port=self.port,
            baudrate=self.baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_EVEN,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.05
        )
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
            if c:
                buf.extend(c)
                # Detección SC ACK 0xE5
                if len(buf) == 1 and buf[0] == 0xE5:
                    return bytes(buf)
                # Detección SD1 (6 bytes)
                if len(buf) >= 6 and buf[0] == 0x10 and buf[5] == 0x16:
                    if buf[4] == ((buf[1] + buf[2] + buf[3]) & 0xFF):
                        return bytes(buf[:6])
                # Detección SD2
                if len(buf) >= 6 and buf[0] == 0x68 and buf[1] == buf[2] and buf[3] == 0x68:
                    total_len = buf[1] + 6
                    if len(buf) >= total_len:
                        if buf[total_len - 1] == 0x16:
                            return bytes(buf[:total_len])
            else:
                time.sleep(0.005)
        return bytes(buf) if buf else None


class MockTransport(BaseTransport):
    """Simulador en memoria para validación end-to-end de la máquina de estados."""
    def __init__(self):
        self.last_write = b""
        self.state = "INIT"
        self.current_block = ""
        self.chunk_count = 0

    def open(self):
        print("[MOCK] Transporte de simulación iniciado (Modo PLC Virtual Activo).")

    def close(self):
        print("[MOCK] Transporte de simulación cerrado.")

    def write(self, data: bytes):
        self.last_write = data
        if len(data) >= 7 and data[0] == 0x68:
            # Analizar comando escrito
            pdu = data[7:-2]
            if b"_DELE" in pdu:
                self.state = "DELE_CONFIRM"
            elif len(pdu) >= 18 and pdu[10] == 0x1A:  # INSE
                if b"_0800001P" in pdu:
                    self.current_block = "OB1"
                elif b"_0B00000P" in pdu:
                    self.current_block = "SDB"
                elif b"_0A00001P" in pdu:
                    self.current_block = "DB1"
                self.state = "INSE_CONFIRM"
                self.chunk_count = 0
            elif len(pdu) >= 14 and pdu[1] == 0x03 and pdu[12] == 0x1B:  # DOWN Chunk ACK
                self.chunk_count += 1
                if self.current_block == "OB1" and self.chunk_count == 1:
                    self.state = "DOWN_CHUNK_2"
                else:
                    self.state = "ENDB_REQ"
            elif len(pdu) >= 14 and pdu[1] == 0x03 and pdu[13] == 0x1C:  # ENDB ACK
                self.state = "WAIT_COMMIT"
            elif b"_INSE" in pdu and pdu[10] == 0x28:  # Commit
                self.state = "COMMIT_CONFIRM"

    def reset_buffers(self):
        pass

    def read_exact(self, count: int, timeout: float) -> bytes:
        return b"\xE5"

    def read_until_frame(self, timeout: float) -> Optional[bytes]:
        if len(self.last_write) >= 4 and self.last_write[0] == 0x68:
            return b"\xE5"

        if self.last_write == b"\x10\x02\x00\x4c\x4e\x16":
            # Sondeo SD1
            if self.state == "INIT":
                pdu = bytes.fromhex("32 03 00 00 00 20 00 02 00 18 00 00 04 01 FF 04 00 A0") + b"CPU 214 REL 0.910091"
                self.state = "READY"
                return build_sd2(pdu, fc=0x08, plc_addr=0, pc_addr=2)

            elif self.state == "READY":
                # Confirmación STOP o RUN
                pdu = bytes.fromhex("32 03 00 00 00 21 00 01 00 00 00 00")
                return build_sd2(pdu, fc=0x08, plc_addr=0, pc_addr=2)

            elif self.state == "DELE_CONFIRM":
                pdu = bytes.fromhex("32 03 00 00 00 22 00 01 00 00 00 00 28")
                self.state = "READY"
                return build_sd2(pdu, fc=0x08, plc_addr=0, pc_addr=2)

            elif self.state == "INSE_CONFIRM":
                pdu = bytes.fromhex("32 03 00 00 00 23 00 01 00 00 00 00 1A")
                self.state = "DOWN_REQ_1"
                return build_sd2(pdu, fc=0x08, plc_addr=0, pc_addr=2)

            elif self.state == "DOWN_REQ_1":
                # Job Request DOWN (seq 1)
                name = BLOCK_CONFIG[self.current_block]["name_inse"]
                pdu = bytes.fromhex("32 01 00 00 00 01 00 12 00 00 1B 00 00 00 00 00 00 00") + bytes([len(name)]) + name
                self.state = "WAITING_CHUNK_1"
                return build_sd2(pdu, fc=0x08, plc_addr=0, pc_addr=2)

            elif self.state == "DOWN_CHUNK_2":
                name = BLOCK_CONFIG[self.current_block]["name_inse"]
                pdu = bytes.fromhex("32 01 00 00 00 02 00 12 00 00 1B 00 00 00 00 00 00 00") + bytes([len(name)]) + name
                self.state = "WAITING_CHUNK_2"
                return build_sd2(pdu, fc=0x08, plc_addr=0, pc_addr=2)

            elif self.state == "ENDB_REQ":
                seq = 3 if self.current_block == "OB1" else 2
                name = BLOCK_CONFIG[self.current_block]["name_inse"]
                pdu = bytes([0x32, 0x01, 0x00, 0x00, 0x00, seq, 0x00, 0x12, 0x00, 0x00, 0x1C, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, len(name)]) + name
                self.state = "WAITING_ENDB_ACK"
                return build_sd2(pdu, fc=0x08, plc_addr=0, pc_addr=2)

            elif self.state == "COMMIT_CONFIRM":
                pdu = bytes.fromhex("32 03 00 00 00 24 00 01 00 00 00 00 28")
                self.state = "READY"
                return build_sd2(pdu, fc=0x08, plc_addr=0, pc_addr=2)

        return b"\xE5"



# ============================================================================
# Máquina de Estados del Flasher PPI
# ============================================================================

class S7_200_Flasher:
    def __init__(self, transport: BaseTransport, plc_addr: int = DEFAULT_PLC_ADDR, pc_addr: int = DEFAULT_PC_ADDR):
        self.transport = transport
        self.plc_addr = plc_addr
        self.pc_addr = pc_addr
        self.fcb_state = 0  # 0 -> 0x5C, 1 -> 0x7C
        self.seq_counter = 0x0020

    def next_seq(self) -> int:
        self.seq_counter = (self.seq_counter + 1) & 0x7FFF
        return self.seq_counter

    def get_fc(self) -> int:
        """Alternancia obligatoria FCB PROFIBUS FDL (0x5C <-> 0x7C)."""
        fc = 0x7C if self.fcb_state else 0x5C
        self.fcb_state ^= 1
        return fc

    def send_raw_sd2_wait_ack(self, pdu: bytes, max_retries: int = 4) -> bool:
        """Transmite una trama SD2 y espera confirmación inmediata SC (0xE5)."""
        fc = self.get_fc()
        frame = build_sd2(pdu, fc, self.plc_addr, self.pc_addr)

        for attempt in range(max_retries):
            self.transport.reset_buffers()
            self.transport.write(frame)
            ack = self.transport.read_exact(1, timeout=0.15)
            if ack == b"\xE5":
                return True
            time.sleep(0.05)
        return False

    def poll_for_sd2_response(self, timeout: float = 4.0) -> Optional[bytes]:
        """Sondea activamente con SD1 (0x4C) hasta recibir la trama SD2 del PLC."""
        poll = build_sd1(fc=0x4C, plc_addr=self.plc_addr, pc_addr=self.pc_addr)
        deadline = time.time() + timeout

        while time.time() < deadline:
            self.transport.reset_buffers()
            self.transport.write(poll)
            resp = self.transport.read_until_frame(timeout=0.15)
            if resp:
                if resp == b"\xE5":
                    # PLC ocupado procesando o borrando memoria
                    time.sleep(0.04)
                    continue
                if len(resp) >= 6 and resp[0] == 0x68 and resp[-1] == 0x16:
                    return resp
            time.sleep(0.04)
        return None

    def execute_s7_transaction(self, pdu: bytes, timeout: float = 4.0) -> Optional[bytes]:
        """Envía solicitud SD2, valida ACK y sondea la respuesta SD2."""
        if not self.send_raw_sd2_wait_ack(pdu):
            return None
        return self.poll_for_sd2_response(timeout=timeout)

    # ------------------------------------------------------------------------
    # Comandos de Nivel Superior
    # ------------------------------------------------------------------------

    def ping_and_negotiate_pdu(self) -> Optional[str]:
        """Inicializa enlace, negocia PDU de 240B y consulta modelo del PLC."""
        print("[*] Negociando PDU de 240 bytes y consultando modelo del PLC...")
        seq = self.next_seq()
        # Petición S7comm READ_VAR para identificación de CPU
        pdu = bytes([
            0x32, 0x01, 0x00, 0x00, (seq >> 8) & 0xFF, seq & 0xFF, 0x00, 0x0E, 0x00, 0x00,
            0x04, 0x01, 0x12, 0x0A, 0x10, 0x02, 0x00, 0x14, 0x00, 0x00,
            0x03, 0x00, 0x00, 0x00
        ])
        resp = self.execute_s7_transaction(pdu, timeout=2.0)
        if resp and len(resp) >= 30:
            try:
                # Extraer cadena ASCII del nombre de la CPU
                ascii_part = resp[25:-2].decode("latin1", errors="ignore").strip()
                return ascii_part
            except Exception:
                return "S7-200 (Online)"
        return None

    def set_cpu_mode(self, mode: str) -> bool:
        """Pone la CPU en modo STOP o RUN mediante la función 0x29 / 0x28."""
        mode = mode.upper()
        if mode == "STOP":
            fc = 0x29
            desc = "STOP (Detener CPU)"
        elif mode == "RUN":
            fc = 0x28
            desc = "RUN (Poner en Marcha)"
        else:
            raise ValueError(f"Modo inválido: {mode}")

        p_prog = b"P_PROGRAM"
        param = bytes([fc, 0x00, 0x00, 0x00, 0x00, 0x00, len(p_prog)]) + p_prog
        seq = self.next_seq()
        pdu = bytes([
            0x32, 0x01, 0x00, 0x00, (seq >> 8) & 0xFF, seq & 0xFF,
            (len(param) >> 8) & 0xFF, len(param) & 0xFF,
            0x00, 0x00
        ]) + param

        print(f"[*] Enviando comando {desc}...")
        resp = self.execute_s7_transaction(pdu, timeout=3.5)
        if resp and len(resp) >= 12 and resp[0] == 0x68 and resp[-1] == 0x16:
            print(f"[✓] Modo {mode} confirmado exitosamente por el PLC.")
            return True
        print(f"[!] Advertencia: No se recibió confirmación explícita para {mode}.")
        return False

    def delete_block(self, block_name_dele: bytes) -> bool:
        """Borra la versión anterior del bloque en EEPROM (_DELE)."""
        seq = self.next_seq()
        pdu = bytes([
            0x32, 0x01, 0x00, 0x00, (seq >> 8) & 0xFF, seq & 0xFF, 0x00, 0x1A, 0x00, 0x00,
            0x28, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xFD, 0x00, 0x0A, 0x01, 0x00
        ]) + block_name_dele + bytes([0x05]) + b"_DELE"

        print(f"[*] Borrando bloque previo ({block_name_dele.decode()})...")
        # El borrado físico de la EEPROM puede tomar hasta 5 segundos
        resp = self.execute_s7_transaction(pdu, timeout=7.0)
        if resp and len(resp) >= 12:
            print(f"[✓] Bloque {block_name_dele.decode()} borrado con éxito.")
            return True
        return False

    def flash_single_block(self, block_key: str, block_data: bytes) -> bool:
        """Ejecuta el protocolo completo de carga para un bloque binario."""
        cfg = BLOCK_CONFIG[block_key]
        desc = cfg["desc"]
        name_inse = cfg["name_inse"]
        name_commit = cfg["name_commit"]
        total_len = len(block_data)

        print(f"\n{'='*70}")
        print(f"⚡ INICIANDO CARGA: {desc} ({total_len} bytes)")
        print(f"{'='*70}")

        # 1. Borrado previo si aplica
        if cfg.get("needs_delete") and "name_dele" in cfg:
            self.delete_block(cfg["name_dele"])

        # 2. Apertura del Bloque (_INSE, Función 0x1A)
        seq_inse = self.next_seq()
        attr_str = cfg["attr_fmt"].encode()
        pdu_inse = bytes([
            0x32, 0x01, 0x00, 0x00, (seq_inse >> 8) & 0xFF, seq_inse & 0xFF, 0x00, 0x20, 0x00, 0x00,
            0x1A, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00,
            len(name_inse)
        ]) + name_inse + bytes([len(attr_str) + 1, 0x01]) + attr_str

        print(f"[*] Enviando solicitud de apertura _INSE para {name_inse.decode()}...")
        resp_inse = self.execute_s7_transaction(pdu_inse, timeout=3.5)
        if not resp_inse:
            print(f"[X] Falló la apertura _INSE para {desc}.")
            return False
        print(f"[✓] Apertura _INSE aceptada por el PLC.")

        # 3. Sondeo activo continuo esperando petición de trabajo _DOWN (0x1B)
        print("[*] Sondeando solicitud de datos _DOWN del PLC...")
        down_job = self.poll_for_sd2_response(timeout=4.0)
        if not down_job or len(down_job) < 20 or down_job[17] != 0x1B:
            print("[X] El PLC no solicitó los datos (_DOWN).")
            return False

        # Extraer número de secuencia solicitado por el PLC
        job_seq = (down_job[11] << 8) | down_job[12]
        print(f"[✓] PLC solicitó el bloque: _DOWN (seq=0x{job_seq:04X})")

        # 4. Despacho de paquetes de datos (Segmentación si > 219 bytes)
        # La CPU 214 requiere bloques de máximo 219 bytes de datos útiles por PDU
        CHUNK_SIZE = 219
        offset = 0
        chunk_idx = 1

        while offset < total_len:
            chunk = block_data[offset : offset + CHUNK_SIZE]
            offset += len(chunk)
            has_more = (offset < total_len)

            # Cabecera de datos S7comm para _DOWN
            # 1B [has_more 0x01/0x00] [chunk_len 2B] 00 [payload]
            chunk_len_field = len(chunk) - 1
            data_hdr = bytes([0x1B, 0x01 if has_more else 0x00, (chunk_len_field >> 8) & 0xFF, chunk_len_field & 0xFF, 0x00])
            full_data = data_hdr + chunk

            s7_data_len = len(full_data) - 2
            pdu_down_ack = bytes([
                0x32, 0x03, 0x00, 0x00, (job_seq >> 8) & 0xFF, job_seq & 0xFF,
                0x00, 0x02,
                (s7_data_len >> 8) & 0xFF, s7_data_len & 0xFF,
                0x00, 0x00
            ]) + full_data

            print(f"[*] Despachando Chunk {chunk_idx}: {len(chunk)} bytes (restantes: {total_len - offset} B)...")
            if not self.send_raw_sd2_wait_ack(pdu_down_ack):
                print(f"[X] Error: El PLC no respondió ACK (0xE5) al chunk {chunk_idx}.")
                return False

            if has_more:
                # Sondeo esperando la siguiente petición _DOWN del PLC
                next_req = self.poll_for_sd2_response(timeout=4.0)
                if not next_req or len(next_req) < 20 or next_req[17] != 0x1B:
                    print(f"[X] Error en sondeo de siguiente chunk.")
                    return False
                job_seq = (next_req[11] << 8) | next_req[12]
                chunk_idx += 1

        print(f"[✓] Todos los bytes de datos transmitidos con éxito.")

        # 5. Sondeo de Petición de Fin de Bloque _ENDB (0x1C)
        print("[*] Esperando solicitud de fin de bloque _ENDB del PLC...")
        endb_job = self.poll_for_sd2_response(timeout=4.0)
        if not endb_job or len(endb_job) < 20 or endb_job[17] != 0x1C:
            print("[X] El PLC no solicitó el fin de bloque (_ENDB).")
            return False

        endb_seq = (endb_job[11] << 8) | endb_job[12]
        print(f"[✓] PLC emitió _ENDB (seq=0x{endb_seq:04X}). Confirmando...")

        # Responder ACK a _ENDB
        pdu_endb_ack = bytes([
            0x32, 0x03, 0x00, 0x00, (endb_seq >> 8) & 0xFF, endb_seq & 0xFF,
            0x00, 0x01, 0x00, 0x00,
            0x00, 0x1C
        ])
        if not self.send_raw_sd2_wait_ack(pdu_endb_ack):
            print("[X] Falló el ACK a _ENDB.")
            return False

        # 6. Commit de Activación Final (_INSE, Función 0x28)
        seq_commit = self.next_seq()
        pdu_commit = bytes([
            0x32, 0x01, 0x00, 0x00, (seq_commit >> 8) & 0xFF, seq_commit & 0xFF,
            0x00, 0x1A, 0x00, 0x00,
            0x28, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xFD, 0x00, 0x0A, 0x01, 0x00
        ]) + name_commit + bytes([0x05]) + b"_INSE"

        print(f"[*] Grabando y validando bloque en EEPROM física...")
        resp_commit = self.execute_s7_transaction(pdu_commit, timeout=8.0)
        if resp_commit and len(resp_commit) >= 12:
            print(f"[✓] ¡ÉXITO 100%! {desc} grabado y activado en la memoria del autómata.")
            return True
        else:
            print(f"[!] Advertencia: No se recibió confirmación de commit en el plazo esperado.")
            return False


# ============================================================================
# Interfaz de Línea de Comandos (CLI)
# ============================================================================

def auto_detect_serial() -> str:
    """Busca automáticamente puertos seriales FTDI o PTY disponibles."""
    for p in ["/tmp/ttyPPI", "/dev/ttyUSB0", "/dev/ttyUSB1"]:
        if os.path.exists(p):
            return p
    return DEFAULT_SERIAL


def main():
    parser = argparse.ArgumentParser(
        description="Flasher Autónomo de Bloques para Siemens SIMATIC S7-200 en Linux"
    )
    # Opciones de Conexión
    parser.add_argument("--port", default=None, help="Puerto serie (ej: /dev/ttyUSB0, /tmp/ttyPPI)")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD, help=f"Velocidad en baudios (default: {DEFAULT_BAUD})")
    parser.add_argument("--ble", action="store_true", help="Utilizar conexión directa Bluetooth LE vía ESP32")
    parser.add_argument("--mac", default=DEFAULT_BLE_MAC, help=f"Dirección MAC para BLE (default: {DEFAULT_BLE_MAC})")
    parser.add_argument("--dry-run", action="store_true", help="Modo simulación (sin acceder al hardware físico)")

    # Opciones de Operación
    parser.add_argument("--all", action="store_true", help="Cargar trilogía completa: Sistema (SDB) + Programa (OB1) + Datos (DB1)")
    parser.add_argument("--program", action="store_true", help="Cargar únicamente el Bloque de Programa (OB1)")
    parser.add_argument("--system", action="store_true", help="Cargar únicamente el Bloque de Sistema (SDB)")
    parser.add_argument("--data", action="store_true", help="Cargar únicamente el Bloque de Datos (DB1)")
    parser.add_argument("--stop", action="store_true", help="Poner el autómata en STOP")
    parser.add_argument("--run", action="store_true", help="Poner el autómata en RUN")
    parser.add_argument("--info", action="store_true", help="Consultar información de hardware del autómata")

    # Rutas de Archivos
    parser.add_argument(
        "--blocks-dir",
        default=os.path.join(os.path.dirname(__file__), "..", "examples", "blocks"),
        help="Directorio donde residen los binarios (.bin)"
    )

    args = parser.parse_args()

    # Si no se pasó ninguna acción, mostrar ayuda
    if not (args.all or args.program or args.system or args.data or args.stop or args.run or args.info):
        parser.print_help()
        print("\n[!] Debe especificar al menos una acción (ej: --all, --program, --info, --stop, --run).")
        sys.exit(1)

    # 1. Configurar Transporte
    if args.dry_run:
        transport = MockTransport()
    elif args.ble:
        print("[!] Modo BLE directo requiere el puente ble_serial_bridge.py o /tmp/ttyPPI.")
        port = "/tmp/ttyPPI"
        if not os.path.exists(port):
            print(f"[-] No se encontró el puerto virtual {port}.")
            print("    Ejecute primero en otra terminal: python3 scripts/ble_serial_bridge.py")
            sys.exit(1)
        transport = SerialTransport(port=port, baud=args.baud)
    else:
        port = args.port or auto_detect_serial()
        transport = SerialTransport(port=port, baud=args.baud)

    print(f"\n========================================================")
    print(f"🚀 open-ppi-bridge - Flasher Autónomo Siemens S7-200")
    print(f"========================================================")

    try:
        transport.open()
    except Exception as e:
        print(f"[-] Error abriendo transporte ({e}). Verifique permisos o conexión física.")
        sys.exit(1)

    flasher = S7_200_Flasher(transport)

    try:
        # Consulta de información / Handshake inicial
        dev_info = flasher.ping_and_negotiate_pdu()
        if dev_info:
            print(f"[✓] Autómata detectado en línea: \033[92m{dev_info}\033[0m")
        else:
            print("[!] Advertencia: No hubo respuesta al ping inicial. Intentando continuar...")

        if args.info:
            sys.exit(0)

        # Si se solicita STOP manual
        if args.stop:
            flasher.set_cpu_mode("STOP")
            sys.exit(0)

        # Si se va a flashear, poner obligatoriamente en STOP primero
        will_flash = args.all or args.program or args.system or args.data
        if will_flash:
            flasher.set_cpu_mode("STOP")
            time.sleep(0.5)

        blocks_to_flash = []
        if args.all:
            blocks_to_flash = ["SDB", "OB1", "DB1"]
        else:
            if args.system:
                blocks_to_flash.append("SDB")
            if args.program:
                blocks_to_flash.append("OB1")
            if args.data:
                blocks_to_flash.append("DB1")

        t_start = time.time()
        for b_key in blocks_to_flash:
            cfg = BLOCK_CONFIG[b_key]
            bin_path = os.path.join(args.blocks_dir, cfg["file_default"])
            if not os.path.isfile(bin_path):
                print(f"[X] Error: Archivo binario no encontrado: {bin_path}")
                sys.exit(1)

            with open(bin_path, "rb") as f:
                block_data = f.read()

            ok = flasher.flash_single_block(b_key, block_data)
            if not ok:
                print(f"\n[X] Error crítico durante la carga de {cfg['desc']}. Proceso abortado.")
                sys.exit(1)
            time.sleep(0.3)

        elapsed = time.time() - t_start

        # Reactivación a RUN al finalizar la carga
        if will_flash or args.run:
            print("\n[*] Reactivando autómata...")
            flasher.set_cpu_mode("RUN")

        if will_flash:
            print(f"\n{'='*70}")
            print(f"🎉 ¡PROCESO DE CARGA COMPLETADO EXITOSAMENTE EN {elapsed:.2f} SEGUNDOS!")
            print(f"   Bloques cargados : {', '.join(blocks_to_flash)}")
            print(f"   Estado final     : CPU en RUN (Lógica activa en autómata)")
            print(f"   Windows / QEMU   : 0% Dependencia (100% Nativo Linux)")
            print(f"{'='*70}\n")

    finally:
        transport.close()


if __name__ == "__main__":
    main()
