#!/usr/bin/env python3
"""
read_io_ppi.py
Lector en tiempo real de Entradas (I) y Salidas (Q) para Siemens S7-200 (CPU 214)
vía protocolo nativo PPI sobre RS485.
"""

import sys
import time
import argparse
import serial

PORT = "/dev/ttyUSB0"
BAUD = 9600
PLC_ADDR = 2
PC_ADDR = 0

def calc_fcs(payload: bytes) -> int:
    return sum(payload) & 0xFF

def send_s7_request(ser: serial.Serial, pdu_body: bytes) -> bytes:
    payload = bytes([PLC_ADDR, PC_ADDR, 0x4C]) + pdu_body
    fcs = calc_fcs(payload)
    frame = bytes([0x68, len(payload), len(payload), 0x68]) + payload + bytes([fcs, 0x16])

    ack = False
    for _ in range(4):
        ser.reset_input_buffer()
        ser.write(frame)
        ser.flush()
        time.sleep(0.04)
        r = ser.read(1)
        if r == b"\xE5":
            ack = True
            break
        time.sleep(0.06)

    if not ack:
        return None

    poll = bytes([0x10, PLC_ADDR, PC_ADDR, 0x4C, (PLC_ADDR + PC_ADDR + 0x4C) & 0xFF, 0x16])
    deadline = time.time() + 1.8
    resp = bytearray()
    while time.time() < deadline:
        time.sleep(0.05)
        ser.reset_input_buffer()
        ser.write(poll)
        ser.flush()
        time.sleep(0.05)
        c = ser.read(ser.in_waiting or 100)
        if c:
            if c == b"\xE5":
                continue
            resp.extend(c)
            if len(resp) >= 6 and resp[0] == 0x68 and resp[-1] == 0x16 and len(resp) >= (resp[1] + 6):
                return bytes(resp)
    return None

def init_connection(ser: serial.Serial) -> bool:
    pdu_neg = bytes([
        0x32, 0x01, 0x00, 0x00, 0xCC, 0xC1, 0x00, 0x08, 0x00, 0x00,
        0xF0, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0xF0
    ])
    res = send_s7_request(ser, pdu_neg)
    return res is not None

def read_area(ser: serial.Serial, area_code: int, start_byte: int, count: int, seq: int) -> bytes:
    start_bit = start_byte * 8
    pdu_read = bytes([
        0x32, 0x01, 0x00, 0x00, (seq >> 8) & 0xFF, seq & 0xFF, 0x00, 0x0E, 0x00, 0x00,
        0x04, 0x01, 0x12, 0x0A, 0x10, 0x02, (count >> 8) & 0xFF, count & 0xFF, 0x00, 0x00,
        area_code, (start_bit >> 16) & 0xFF, (start_bit >> 8) & 0xFF, start_bit & 0xFF
    ])
    res = send_s7_request(ser, pdu_read)
    if res and len(res) >= (21 + count) and res[0] == 0x68 and res[-1] == 0x16:
        return res[-(2 + count):-2]
    return None

def format_bits(byte_val: int, prefix: str, max_bits: int = 8) -> str:
    parts = []
    for bit in range(max_bits):
        val = (byte_val >> bit) & 1
        label = f"{prefix}.{bit}"
        status = "\033[92m● 1\033[0m" if val else "\033[90m○ 0\033[0m"
        parts.append(f"{label}: {status}")
    return " | ".join(parts)

def main():
    parser = argparse.ArgumentParser(description="Lector de E/S Siemens S7-200 PPI")
    parser.add_argument("-p", "--port", default=PORT, help=f"Puerto serie (default: {PORT})")
    parser.add_argument("-w", "--watch", action="store_true", help="Monitor continuo en bucle")
    parser.add_argument("-i", "--interval", type=float, default=0.2, help="Intervalo en segundos para modo watch")
    args = parser.parse_args()

    try:
        ser = serial.Serial(
            port=args.port,
            baudrate=BAUD,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_EVEN,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.05
        )
    except Exception as e:
        sys.exit(f"[-] Error abriendo {args.port}: {e}")

    print("=" * 70)
    print(" LECTOR DE ENTRADAS Y SALIDAS FÍSICAS - SIEMENS S7-200 (CPU 214)")
    print(f" Puerto: {args.port} | {BAUD} bps 8E1 | Dirección Estación: {PLC_ADDR}")
    print("=" * 70)

    print("[*] Negociando sesión PDU con CPU 214...")
    if not init_connection(ser):
        ser.close()
        sys.exit("[-] Error: El PLC no respondió a la negociación inicial.")
    print("[✓] Conexión PPI establecida y enlazada con éxito.\n")

    seq = 10
    try:
        while True:
            time.sleep(0.15)
            in_bytes = read_area(ser, area_code=0x81, start_byte=0, count=2, seq=seq)
            seq += 1

            time.sleep(0.15)
            out_bytes = read_area(ser, area_code=0x82, start_byte=0, count=2, seq=seq)
            seq += 1

            ts = time.strftime("%H:%M:%S")
            if in_bytes and out_bytes:
                ib0, ib1 = in_bytes[0], in_bytes[1]
                qb0, qb1 = out_bytes[0], out_bytes[1]

                print(f"[{ts}] ENTRADAS -> IB0: 0x{ib0:02X} | {format_bits(ib0, 'I0', 8)}")
                print(f"[{ts}] SALIDAS  -> QB0: 0x{qb0:02X} | {format_bits(qb0, 'Q0', 6)}")
                print("-" * 70)
            else:
                print(f"[{ts}] [!] Reintentando lectura de ciclo...")

            if not args.watch:
                break
            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\n[*] Monitor detenido por el usuario.")
    finally:
        ser.close()

if __name__ == "__main__":
    main()
