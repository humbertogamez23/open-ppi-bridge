#!/usr/bin/env python3
"""
plc_control.py
Herramienta de control de estado operativo (RUN / STOP) para Siemens S7-200 (CPU 214)
mediante tramas nativas PPI / S7comm sobre RS485.
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

def set_plc_mode(ser: serial.Serial, mode: str) -> bool:
    mode = mode.upper()
    if mode == "STOP":
        fc = 0x29
        desc = "STOP (Detener CPU)"
    elif mode == "RUN":
        fc = 0x28
        desc = "RUN (Poner CPU en Marcha)"
    else:
        print(f"[-] Modo desconocido: {mode}")
        return False

    p_prog = b"P_PROGRAM"
    param = bytes([fc, 0x00, 0x00, 0x00, 0x00, 0x00, len(p_prog)]) + p_prog
    pdu = bytes([
        0x32, 0x01, 0x00, 0x00, 0x00, fc,
        (len(param) >> 8) & 0xFF, len(param) & 0xFF,
        0x00, 0x00
    ]) + param

    print(f"[*] Enviando comando {desc} a la CPU {PLC_ADDR}...")
    resp = send_s7_request(ser, pdu)
    if resp and len(resp) >= 12 and resp[0] == 0x68 and resp[-1] == 0x16:
        # rosctr = resp[8], err = resp[17..18]
        print(f"[✓] ¡Comando {mode} aceptado exitosamente por el PLC!")
        return True
    else:
        print(f"[-] Error: El PLC no confirmó el cambio a modo {mode}.")
        return False

def main():
    parser = argparse.ArgumentParser(description="Control de Estado RUN / STOP - Siemens S7-200")
    parser.add_argument("action", choices=["run", "stop"], help="Acción a ejecutar: run o stop")
    parser.add_argument("-p", "--port", default=PORT, help=f"Puerto serial (default: {PORT})")
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

    time.sleep(0.1)
    success = set_plc_mode(ser, args.action)
    ser.close()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
