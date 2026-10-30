#!/usr/bin/env python3
"""
Escáner de Estaciones Siemens S7-200 PPI sobre RS485.
Envía tramas de sondeo SD1 para descubrir estaciones activas en el bus.
"""

import sys
import time
import argparse

try:
    import serial
except ImportError:
    sys.exit("Error: Módulo 'pyserial' no encontrado. Instálelo con: pip install pyserial")


def build_sd1(dest: int, src: int = 0, fc: int = 0x49) -> bytes:
    """Construye una trama SD1 de solicitud de estado."""
    fcs = (dest + src + fc) & 0xFF
    return bytes([0x10, dest, src, fc, fcs, 0x16])


def main():
    parser = argparse.ArgumentParser(description="Escáner de Direcciones Siemens PPI (RS485)")
    parser.add_argument("-p", "--port", default="/dev/ttyUSB0", help="Puerto serie (default: /dev/ttyUSB0)")
    parser.add_argument("-b", "--baud", type=int, default=9600, help="Baudrate (default: 9600)")
    parser.add_argument("--src", type=int, default=0, help="Dirección de la PC/Master (default: 0)")
    parser.add_argument("--max-addr", type=int, default=31, help="Dirección máxima a escanear (default: 31, máx 126)")
    parser.add_argument("--timeout", type=float, default=0.1, help="Timeout de espera de respuesta en seg (default: 0.1)")

    args = parser.parse_args()

    print("=" * 60)
    print(f" ESCÁNER DE ESTACIONES SIEMENS PPI")
    print(f" Puerto:   {args.port}")
    print(f" Config:   {args.baud} bps, 8E1 (Even Parity)")
    print(f" Rango:    Dirección 0 a {args.max_addr} (PC en {args.src})")
    print("=" * 60)

    try:
        ser = serial.Serial(
            port=args.port,
            baudrate=args.baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_EVEN,
            stopbits=serial.STOPBITS_ONE,
            timeout=args.timeout
        )
    except Exception as e:
        sys.exit(f"[-] Error abriendo puerto: {e}")

    encontradas = []

    try:
        for addr in range(0, args.max_addr + 1):
            if addr == args.src:
                continue

            frame = build_sd1(dest=addr, src=args.src, fc=0x49)
            ser.reset_input_buffer()
            ser.write(frame)
            time.sleep(0.015)

            resp = ser.read(32)
            if resp:
                hex_resp = " ".join(f"{b:02X}" for b in resp)
                print(f"[+] [RESPUESTA] Estación {addr:02d} respondió ({len(resp)} bytes): {hex_resp}")
                encontradas.append((addr, hex_resp))
            else:
                sys.stdout.write(f"\rBuscando estación {addr:02d}...")
                sys.stdout.flush()

        print("\r" + " " * 40 + "\r", end="")
        print("=" * 60)
        if encontradas:
            print(f"[✓] Se encontraron {len(encontradas)} estación(es) activa(s):")
            for addr, resp in encontradas:
                print(f"   -> Dirección PLC: {addr} (Respuesta: {resp})")
        else:
            print("[-] No se detectó respuesta de ninguna estación en el rango escaneado.")
            print("    Verifique:")
            print("    1. Cableado (Pin 3 = A+, Pin 8 = B-, Pin 5 = GND en el DB9 de S7-200).")
            print("    2. Alimentación del PLC.")
            print("    3. Baudrate correcto (habitualmente 9600 o 19200).")
        print("=" * 60)

    except KeyboardInterrupt:
        print("\n[*] Escaneo cancelado por el usuario.")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
