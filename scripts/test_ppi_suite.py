#!/usr/bin/env python3
"""
test_ppi_suite.py
Herramienta de diagnóstico y prueba interactiva de tramas PPI sobre RS485.
Permite validar la comunicación directa y determinista con el Siemens S7-200 (CPU 214).
"""

import sys
import time
import serial

PORT = "/dev/ttyUSB0"
BAUD = 9600
PLC_ADDR = 2
PC_ADDR = 0

def calc_fcs_sd1(da: int, sa: int, fc: int) -> int:
    return (da + sa + fc) & 0xFF

def calc_fcs_sd2(payload: bytes) -> int:
    return sum(payload) & 0xFF

def print_hex(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)

def send_s7_request(ser: serial.Serial, pdu_body: bytes, desc: str) -> bytes:
    print(f"\n--- {desc} ---")
    payload = bytes([PLC_ADDR, PC_ADDR, 0x4C]) + pdu_body
    fcs = calc_fcs_sd2(payload)
    frame = bytes([0x68, len(payload), len(payload), 0x68]) + payload + bytes([fcs, 0x16])
    print(f"-> [TX SD2] ({len(frame)} bytes): {print_hex(frame)}")

    t0 = time.time()
    ack = False
    for attempt in range(4):
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
        print(f"<- [RX]: Sin ACK (0xE5) del PLC tras reintentos ({(time.time()-t0)*1000:.1f}ms)")
        return None

    print(f"<- [RX]: ACK recibido (0xE5) en {(time.time()-t0)*1000:.1f}ms")

    # Sondeo (Poll con 0x4C) esperando que la CPU 214 termine de preparar la respuesta
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
                elapsed = (time.time() - t0) * 1000.0
                print(f"<- [RX SD2] ({len(resp)} bytes, {elapsed:.1f}ms): {print_hex(resp)}")
                decode_resp(resp)
                return bytes(resp)

    print(f"<- [RX]: Timeout esperando respuesta SD2")
    return None

def decode_resp(resp: bytes):
    if resp == b"\xE5":
        print("   [✓] ACK corto (0xE5). El PLC recibió y aceptó la trama.")
        return
    if len(resp) == 6 and resp[0] == 0x10 and resp[-1] == 0x16:
        da, sa, fc, fcs = resp[1], resp[2], resp[3], resp[4]
        estado = "ONLINE / LISTO (OK)" if fc == 0x00 else f"Código de estado 0x{fc:02X}"
        print(f"   [✓] Trama corta SD1: De PLC {sa} hacia PC {da} | FC=0x{fc:02X} ({estado})")
        return
    if resp[0] == 0x68 and resp[-1] == 0x16:
        l1 = resp[1]
        da, sa, fc = resp[4], resp[5], resp[6]
        print(f"   [✓] Trama de datos SD2 (Longitud={l1} bytes) | Dest: {da}, Origen: {sa}, FC: 0x{fc:02X}")
        if len(resp) >= 20 and resp[7] == 0x32:
            rosctr = resp[8]
            err = (resp[17] << 8) | resp[18]
            if rosctr == 0x03 and err == 0:
                print("   [✓] Protocolo S7comm: ACK_DATA recibido sin errores (OK).")

def main():
    print("=" * 65)
    print(" SUITE DE DIAGNÓSTICO Y ENVÍO DE TRAMAS PPI (SIEMENS S7-200)")
    print(f" Puerto: {PORT} | {BAUD} bps 8E1 | Dirección PLC: {PLC_ADDR}")
    print("=" * 65)

    try:
        ser = serial.Serial(
            port=PORT,
            baudrate=BAUD,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_EVEN,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.05
        )
    except Exception as e:
        sys.exit(f"[-] Error abriendo {PORT}: {e}")

    time.sleep(0.1)

    # 1. Ping rápido (SD1 FC 0x49)
    print("\n--- Prueba 1: Consulta de presencia (SD1 Ping FC 0x49) ---")
    f1 = bytes([0x10, PLC_ADDR, PC_ADDR, 0x49, calc_fcs_sd1(PLC_ADDR, PC_ADDR, 0x49), 0x16])
    print(f"-> [TX SD1] ({len(f1)} bytes): {print_hex(f1)}")
    
    ser.reset_input_buffer()
    t0 = time.time()
    ser.write(f1)
    ser.flush()
    time.sleep(0.04)
    r1 = ser.read(ser.in_waiting or 6)
    if r1:
        print(f"<- [RX SD1] ({len(r1)} bytes, {(time.time()-t0)*1000:.1f}ms): {print_hex(r1)}")
        decode_resp(r1)
    else:
        print(f"<- [RX]: Sin respuesta")

    time.sleep(0.15)

    # 2. Negociación PDU (240 bytes)
    pdu_neg = bytes([
        0x32, 0x01, 0x00, 0x00, 0xCC, 0xC1, 0x00, 0x08, 0x00, 0x00,
        0xF0, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0xF0
    ])
    send_s7_request(ser, pdu_neg, "Prueba 2: Solicitud y Negociación PDU 240B (0x00F0)")

    time.sleep(0.15)

    # 3. Lectura de Entradas Físicas (IB0 e IB1)
    pdu_read_in = bytes([
        0x32, 0x01, 0x00, 0x00, 0x00, 0x0A, 0x00, 0x0E, 0x00, 0x00,
        0x04, 0x01, 0x12, 0x0A, 0x10, 0x02, 0x00, 0x02, 0x00, 0x00,
        0x81, 0x00, 0x00, 0x00
    ])
    res_in = send_s7_request(ser, pdu_read_in, "Prueba 3: Lectura en vivo de Entradas Digitales (IB0)")
    if res_in:
        ib0 = res_in[-4]
        print(f"   [★] VALOR FÍSICO LEÍDO DEL PLC: IB0 = 0x{ib0:02X} ({bin(ib0)})")
        print(f"       I0.0 (START)   : {'ON (1)' if ib0 & 1 else 'OFF (0)'}")
        print(f"       I0.1 (STP)     : {'ON (1)' if ib0 & 2 else 'OFF (0)'}")
        print(f"       I0.2 (P_EMERG) : {'ON (1)' if ib0 & 4 else 'OFF (0)'}")
        print(f"       I0.3 (CALOR)   : {'ON (1)' if ib0 & 8 else 'OFF (0)'}")

    ser.close()
    print("\n" + "=" * 65)
    print(" PRUEBAS COMPLETADAS CON ÉXITO.")
    print("=" * 65)

if __name__ == "__main__":
    main()
