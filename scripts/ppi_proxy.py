#!/usr/bin/env python3
"""
ppi_proxy.py  v8.5 – Pasarela Serializada Blindada con Alternancia Estricta de FCB en Bloques
Siemens SIMATIC S7-200 (CPU 214 Rel 00.91) sobre RS-485 FTDI FT232RL.

MEJORAS CRÍTICAS v8.5:
  - [CORRECCIÓN CRÍTICA FCB POST-_INSE]:
    Al capturar la petición de trabajo Job _DOWN (0x1B) tras _INSE, no se invierte
    redundantemente plc_fcb si ya fue invertido por la respuesta de _INSE. Esto garantiza
    que el primer fragmento de código (Chunk 1) se transmita con FCB estrictamente alternado
    (0x7C tras 0x5C), evitando que la CPU 214 lo descarte como eco o retransmisión repetida.
  - [TIMEOUT ADAPTATIVO REGULAR]:
    ack_timeout_dynamic para tramas comunes (READ_VAR / UserData) reducido a 0.8s base
    para que los reintentos concluyan antes de los 3.0s de timeout de Micro/WIN.
  - [SONDEO FÍSICO ACTIVO TRAS _INSE HEREDADO v8.4]:
    Sondeo físico continuo SD1 (10 02 00 4C) cada 120ms para capturar Job 0x1B del PLC.
  - [TOLERANCIA EEPROM HEREDADA v8.3]:
    7.0s para _DELE/_ENDB, 4.5s para _INSE/_DOWN, MAX_ACK_RETRIES = 8.
"""

import os
import sys
import time
import socket
import select
import serial
from collections import deque

SOCKET_PATH = "/tmp/qemu_serial.sock"
BAUD = 9600
PLC_ADDR = 2
PC_ADDR = 0

# ── Parámetros Temporales Calibrados ──
TURNAROUND_DELAY = 0.025   # 25ms post-transmisión para retorno de transceptor RS-485
POLL_INTERVAL = 0.12       # 120ms entre sondeos SD1 de lectura al PLC
POLL_TIMEOUT = 12.0        # 12.0s límite de sondeo para operaciones pesadas de EEPROM (_DELE/_INSE/_ENDB)
INTER_TX_GAP = 0.04        # 40ms entre fin de una transacción física y la siguiente
MAX_ACK_RETRIES = 8        # 8 reintentos por trama si el PLC no da ACK 0xE5 (tolerancia EEPROM de hasta 14s)
ACK_BASE_TIMEOUT = 1.5     # Base timeout en segundos (permite apertura/borrado/escritura de bloques en CPU 214)
ACK_INCREMENT = 0.008      # Incremento por byte de trama

# Estados de la máquina
ST_IDLE = 0
ST_WAIT_PLC_ACK = 1
ST_POLLING_PLC = 2
ST_RESP_READY = 3

# Trama corta estándar de esclavo PPI libre / sin datos pendientes (DA=0, SA=2, FC=0x00)
SD1_IDLE_ACK = bytes([0x10, PC_ADDR, PLC_ADDR, 0x00, (PC_ADDR + PLC_ADDR + 0x00) & 0xFF, 0x16])


def get_serial_node():
    for pat in [
        "/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A25ZA4HJ-if00-port0",
        "/dev/ttyUSB0",
        "/dev/ttyUSB1"
    ]:
        if os.path.exists(pat):
            return pat
    return None


def calc_fcs(payload: bytes) -> int:
    return sum(payload) & 0xFF


def is_valid_sd1(frame: bytes) -> bool:
    if len(frame) != 6:
        return False
    if frame[0] != 0x10 or frame[5] != 0x16:
        return False
    expected_fcs = (frame[1] + frame[2] + frame[3]) & 0xFF
    return frame[4] == expected_fcs


def is_valid_sd2(frame: bytes) -> bool:
    if len(frame) < 6:
        return False
    length = frame[1]
    if frame[0] != 0x68 or frame[2] != length or frame[3] != 0x68:
        return False
    if len(frame) != length + 6:
        return False
    if frame[-1] != 0x16:
        return False
    expected_fcs = calc_fcs(frame[4:-2])
    return frame[-2] == expected_fcs


def get_s7_seq(frame: bytes):
    """Extrae el número de secuencia S7 si la trama es SD2 S7comm."""
    if len(frame) >= 13 and frame[0] == 0x68 and frame[7] == 0x32:
        return (frame[11] << 8) | frame[12]
    return None


def get_s7_func_desc(frame: bytes) -> str:
    """Extrae el código y descripción precisa de la función S7comm si la trama es SD2."""
    if len(frame) >= 18 and frame[0] == 0x68 and frame[7] == 0x32:
        if b"_DELE" in frame:
            return "_DELE"
        if b"_INSE" in frame:
            return "_INSE"
        if b"_ENDB" in frame:
            return "_ENDB"
        rosctr = frame[8]
        if rosctr == 0x01:
            fn = frame[17]
        elif rosctr in (0x02, 0x03):
            if frame[17] in (0x1A, 0x1B, 0x1C):
                fn = frame[17]
            elif len(frame) >= 20:
                fn = frame[19]
            else:
                fn = frame[17]
        elif rosctr == 0x07:
            return "UserData"
        else:
            fn = frame[17]
        fn_map = {
            0x04: "READ_VAR",
            0x05: "WRITE_VAR",
            0x1A: "_INSE",
            0x1B: "_DOWN",
            0x1C: "_ENDB",
            0x28: "RUN",
            0x29: "STOP",
            0xF0: "PDU_NEG"
        }
        return fn_map.get(fn, f"0x{fn:02X}")
    return ""


def get_s7_error_desc(frame: bytes) -> str:
    """Extrae y decodifica el ErrorCode S7comm en tramas de respuesta (ROSCTR 0x02 o 0x03)."""
    if len(frame) >= 19 and frame[0] == 0x68 and frame[7] == 0x32:
        rosctr = frame[8]
        if rosctr in (0x02, 0x03):
            err = (frame[17] << 8) | frame[18]
            if err == 0:
                return ""
            err_map = {
                0xD240: "Violación de coordinación interna (recurso bloqueado / monitoreo activo)",
                0xD201: "Bloque no encontrado",
                0xD209: "Bloque ya existe",
                0x8104: "Contexto no soportado",
                0x8500: "Longitud de PDU excedida"
            }
            desc = err_map.get(err, "Error S7")
            return f", Error=0x{err:04X} ({desc})"
    return ""


def ts():
    return time.strftime("%H:%M:%S")


def send_to_plc(ser, frame):
    """Transmite una trama al bus RS-485 y respeta el turnaround físico."""
    ser.write(frame)
    ser.flush()
    time.sleep(TURNAROUND_DELAY)


def main():
    real_port = get_serial_node()
    if not real_port:
        sys.exit("[-] No se encontró convertidor serial FTDI.")

    print(f"[{ts()}] Gateway Serializado v8.6 (Cierre Inmediato de _ENDB y FCB Blindado) en: {real_port}", flush=True)

    ser = serial.Serial(
        port=real_port,
        baudrate=BAUD,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_EVEN,
        stopbits=serial.STOPBITS_ONE,
        timeout=0.02
    )

    # ── Sincronización Inicial con CPU 214 ──
    print(f"[{ts()}] Sincronizando con CPU 214...", flush=True)
    ser.reset_input_buffer()
    time.sleep(0.1)

    # Ping de prueba inicial
    ping = bytes([0x10, PLC_ADDR, PC_ADDR, 0x49, (PLC_ADDR + PC_ADDR + 0x49) & 0xFF, 0x16])
    ser.write(ping)
    ser.flush()
    time.sleep(0.15)
    r = ser.read(100)
    if r and len(r) >= 6 and r[0] == 0x10 and is_valid_sd1(r[:6]):
        print(f"[{ts()}] ✓ Ping inicial OK: {r[:6].hex(' ')}", flush=True)
    else:
        print(f"[{ts()}] ⚠ Ping sin respuesta SD1 (normal si la CPU está en STOP)", flush=True)

    time.sleep(0.1)

    # Negociación inicial de PDU 240B (0x00F0) con FCV=0 (0x4C) para resetear estado FCB
    pdu_init = bytes([
        0x68, 0x15, 0x15, 0x68, 0x02, 0x00, 0x4C, 0x32, 0x01, 0x00, 0x00, 0xCC, 0xC1,
        0x00, 0x08, 0x00, 0x00, 0xF0, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0xF0, 0xF8, 0x16
    ])
    ser.reset_input_buffer()
    ser.write(pdu_init)
    ser.flush()
    time.sleep(0.08)
    ack = ser.read(1)
    if ack == b"\xE5":
        poll = bytes([0x10, PLC_ADDR, PC_ADDR, 0x4C, (PLC_ADDR + PC_ADDR + 0x4C) & 0xFF, 0x16])
        for _ in range(25):
            time.sleep(0.1)
            ser.write(poll)
            ser.flush()
            time.sleep(0.05)
            rr = ser.read(100)
            if rr and len(rr) >= 6 and rr[0] == 0x68 and is_valid_sd2(rr):
                print(f"[{ts()}] ✓ PDU 240B negociada con éxito con la CPU 214", flush=True)
                break
    else:
        print(f"[{ts()}] ⚠ PDU init sin ACK (se sincronizará dinámicamente)", flush=True)

    time.sleep(0.1)
    ser.reset_input_buffer()

    # Preparar Socket UNIX para QEMU
    if os.path.exists(SOCKET_PATH):
        try:
            os.remove(SOCKET_PATH)
        except OSError:
            pass

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)
    server.listen(1)
    os.chmod(SOCKET_PATH, 0o777)

    poll_frame = bytes([0x10, PLC_ADDR, PC_ADDR, 0x4C, (PLC_ADDR + PC_ADDR + 0x4C) & 0xFF, 0x16])

    try:
        while True:
            print(f"[{ts()}] Socket listo en {SOCKET_PATH}. Esperando conexión de QEMU...", flush=True)
            try:
                client, _ = server.accept()
            except KeyboardInterrupt:
                break

            print(f"[{ts()}] ✓ QEMU conectado. Gateway serializado v8.6 activo.", flush=True)
            client.setblocking(False)

            buf_qemu = bytearray()
            buf_ser = bytearray()
            tx_queue = deque(maxlen=20)
            state = ST_IDLE
            pending_resp = None
            current_frame = None
            current_frame_to_send = None
            retry_count = 0
            plc_fcb = 0                # Bit FCB físico: alterna 0 (0x5C) y 1 (0x7C)
            expected_seq = None        # Secuencia esperada para validación
            poll_start_t = 0.0
            last_poll_t = 0.0
            last_tx_done_t = 0.0
            last_tx_time = 0.0
            waiting_plc_job = False
            plc_job_poll_start_t = 0.0
            last_job_poll_t = 0.0

            while True:
                rlist, _, _ = select.select([client, ser.fileno()], [], [], 0.005)
                now = time.time()

                # ── 1. Lectura de QEMU (Micro/WIN) ──
                if client in rlist:
                    try:
                        data = client.recv(2048)
                        if not data:
                            print(f"[{ts()}] [!] Micro/WIN cerró la conexión.", flush=True)
                            break
                        buf_qemu.extend(data)
                    except (BlockingIOError, InterruptedError):
                        pass
                    except (socket.error, BrokenPipeError, ConnectionResetError):
                        print(f"[{ts()}] [!] Conexión QEMU interrumpida.", flush=True)
                        break

                # ── 2. Lectura Serial desde el PLC ──
                if ser.fileno() in rlist:
                    try:
                        waiting = ser.in_waiting
                        if waiting > 0:
                            chunk = ser.read(waiting)
                            if chunk:
                                buf_ser.extend(chunk)
                    except serial.SerialException as se:
                        print(f"[{ts()}] [-] Error en bus serial: {se}", flush=True)
                        break

                # ── 3. Parseo y Validación de Tramas del PLC ──
                while buf_ser:
                    # Carácter de confirmación inmediata SC
                    if buf_ser[0] == 0xE5:
                        del buf_ser[:1]
                        if state == ST_WAIT_PLC_ACK:
                            fn_desc_curr = get_s7_func_desc(current_frame) if current_frame else ""
                            if fn_desc_curr == "_ENDB":
                                # Cierre de bloque completado: el PLC confirmó con 0xE5 (ACK) la finalización de la transferencia.
                                # Tras _ENDB el PLC no envía más tramas SD2 de datos.
                                # Pasamos de inmediato a ST_IDLE alternando FCB para que la orden de activación (_INSE)
                                # que Micro/WIN tiene en cola se transmita en menos de 10ms sin timeout.
                                plc_fcb ^= 1
                                state = ST_IDLE
                                current_frame = None
                                current_frame_to_send = None
                                expected_seq = None
                                last_tx_done_t = now
                                print(f"[{ts()}] ✓ PLC ACK a _ENDB recibido → Bloque completado al 100%. Listo para activar programa.", flush=True)
                            else:
                                state = ST_POLLING_PLC
                                poll_start_t = now
                                last_poll_t = 0  # Disparar sondeo inmediato
                                retry_count = 0
                                print(f"[{ts()}]   PLC ACK ✓ → sondeando respuesta...", flush=True)
                        continue

                    # Trama de sondeo / estado corto SD1
                    elif buf_ser[0] == 0x10:
                        if len(buf_ser) >= 6:
                            candidate = bytes(buf_ser[:6])
                            if is_valid_sd1(candidate):
                                del buf_ser[:6]
                                if state == ST_POLLING_PLC:
                                    pending_resp = candidate
                                    state = ST_RESP_READY
                                    last_tx_done_t = now
                                    current_frame = None
                                    current_frame_to_send = None
                                    plc_fcb ^= 1  # Éxito: alternar FCB para la próxima petición
                                    print(f"[{ts()}]   PLC respondió SD1 ({len(candidate)}B) [Lista para entregar en sondeo]", flush=True)
                                else:
                                    print(f"[{ts()}]   PLC SD1 verificado ({candidate.hex(' ')})", flush=True)
                                continue
                            else:
                                del buf_ser[:1]
                                continue
                        else:
                            break

                    # Trama de datos variable SD2
                    elif buf_ser[0] == 0x68:
                        if len(buf_ser) >= 4:
                            if buf_ser[1] == buf_ser[2] and buf_ser[3] == 0x68:
                                total = buf_ser[1] + 6
                                if len(buf_ser) >= total:
                                    candidate = bytes(buf_ser[:total])
                                    if is_valid_sd2(candidate):
                                        del buf_ser[:total]

                                        # Caso A: Petición de Trabajo del PLC hacia la PC (ROSCTR == 0x01, ej. Función 0x1B _DOWN pidiendo bytecode).
                                        # En S7comm, el PLC solicita los bloques de programa tras _INSE.
                                        # NUNCA se debe descartar por secuencia, sino entregarse directamente a Micro/WIN.
                                        is_job = len(candidate) >= 18 and candidate[7] == 0x32 and candidate[8] == 0x01
                                        if is_job:
                                            fn_desc = get_s7_func_desc(candidate)
                                            seq_job = get_s7_seq(candidate)
                                            print(f"[{ts()}] ⚡ PLC solicitó Bloque/Trabajo ({len(candidate)}B, fn={fn_desc}, seq=0x{seq_job:04X}) → lista para entregar a Micro/WIN", flush=True)
                                            pending_resp = candidate
                                            state = ST_RESP_READY
                                            last_tx_done_t = now
                                            current_frame = None
                                            current_frame_to_send = None
                                            expected_seq = None
                                            if not waiting_plc_job:
                                                plc_fcb ^= 1
                                            waiting_plc_job = False
                                            continue

                                        if state in (ST_POLLING_PLC, ST_WAIT_PLC_ACK):
                                            seq_resp = get_s7_seq(candidate)
                                            if expected_seq is not None and seq_resp != expected_seq:
                                                print(f"[{ts()}] ⚠ Respuesta SD2 con seq desfasado (esperado 0x{expected_seq:04X}, got 0x{seq_resp:04X}) → resincronizando FCB y retransmitiendo...", flush=True)
                                                # El PLC reenvió la respuesta anterior (ej. 0xCCC1) porque el FCB no alternó.
                                                # Alternamos FCB y retransmitimos de inmediato la petición pendiente con el nuevo FC
                                                plc_fcb ^= 1
                                                if current_frame is not None:
                                                    frame_mut = bytearray(current_frame)
                                                    target_fc = 0x5C if plc_fcb == 0 else 0x7C
                                                    frame_mut[6] = target_fc
                                                    frame_mut[-2] = calc_fcs(frame_mut[4:-2])
                                                    current_frame_to_send = bytes(frame_mut)
                                                    time.sleep(INTER_TX_GAP)
                                                    send_to_plc(ser, current_frame_to_send)
                                                    state = ST_WAIT_PLC_ACK
                                                    now_tx = time.time()
                                                    poll_start_t = now_tx
                                                    last_tx_time = now_tx
                                                    seq_tx = get_s7_seq(current_frame)
                                                    seq_str = f", seq=0x{seq_tx:04X}" if seq_tx is not None else ""
                                                    print(f"[{ts()}] → [PLC] Retransmitida con FC=0x{target_fc:02X}{seq_str} tras resincronización", flush=True)
                                                else:
                                                    state = ST_IDLE
                                                continue
                                            else:
                                                pending_resp = candidate
                                                state = ST_RESP_READY
                                                last_tx_done_t = now
                                                current_frame = None
                                                current_frame_to_send = None
                                                elapsed = (now - poll_start_t) * 1000
                                                plc_fcb ^= 1  # Éxito: alternar FCB para la próxima petición
                                                seq_str = f", seq=0x{seq_resp:04X}" if seq_resp is not None else ""
                                                fn_desc = get_s7_func_desc(candidate)
                                                fn_str = f", fn={fn_desc}" if fn_desc else ""
                                                err_str = get_s7_error_desc(candidate)
                                                print(f"[{ts()}]   PLC respondió SD2 ({len(candidate)}B{seq_str}{fn_str}{err_str}, {elapsed:.0f}ms) [Lista para entregar en sondeo]", flush=True)
                                        else:
                                            if pending_resp is None:
                                                pending_resp = candidate
                                                state = ST_RESP_READY
                                                last_tx_done_t = now
                                                current_frame = None
                                                current_frame_to_send = None
                                                print(f"[{ts()}]   PLC respondió SD2 no solicitado ({len(candidate)}B)", flush=True)
                                            else:
                                                print(f"[{ts()}] ⚠ SD2 repetido ignorado para proteger respuesta activa", flush=True)
                                        continue
                                    else:
                                        print(f"[{ts()}] ⚠ Descartada trama SD2 corrupta (fallo FCS o Delimitador 0x16)", flush=True)
                                        del buf_ser[:1]
                                        continue
                                else:
                                    # La trama SD2 sigue entrando por el puerto serie -> esperar
                                    break
                            else:
                                del buf_ser[:1]
                                continue
                        else:
                            break
                    else:
                        del buf_ser[:1]

                # ── 4. Procesamiento de Peticiones de Micro/WIN (QEMU) ──
                while buf_qemu:
                    # Confirmación SC enviada por Micro/WIN
                    if buf_qemu[0] == 0xE5:
                        ser.write(b"\xE5")
                        ser.flush()
                        del buf_qemu[:1]
                        continue

                    # Sondeo corto SD1 de Micro/WIN
                    elif buf_qemu[0] == 0x10:
                        if len(buf_qemu) >= 6:
                            frame = bytes(buf_qemu[:6])
                            del buf_qemu[:6]
                            da, sa, fc = frame[1], frame[2], frame[3]

                            if da == PLC_ADDR and fc in (0x5C, 0x7C, 0x4C, 0x6C):
                                # ── SONDEO SD1 DE MICRO/WIN: RESPUESTA PRECISA SEGÚN ESTADO ──
                                if state == ST_RESP_READY and pending_resp is not None:
                                    try:
                                        client.sendall(pending_resp)
                                        seq_deliv = get_s7_seq(pending_resp)
                                        fn_deliv = get_s7_func_desc(pending_resp)
                                        seq_str = f", seq=0x{seq_deliv:04X}" if seq_deliv is not None else ""
                                        fn_str = f", fn={fn_deliv}" if fn_deliv else ""
                                        print(f"[{ts()}] → [MW] Respuesta entregada en sondeo ({len(pending_resp)}B{seq_str}{fn_str})", flush=True)
                                    except (socket.error, BrokenPipeError, ConnectionResetError):
                                        break

                                    if fn_deliv == "_INSE":
                                        # Tras aceptar _INSE, el PLC debe emitir una petición de trabajo hacia el PG (Función 0x1B _DOWN)
                                        waiting_plc_job = True
                                        plc_job_poll_start_t = time.time()
                                        last_job_poll_t = 0.0
                                        print(f"[{ts()}] ⚡ _INSE completado → Activando sondeo físico continuo al PLC para capturar petición _DOWN (0x1B)...", flush=True)
                                    else:
                                        waiting_plc_job = False

                                    pending_resp = None
                                    state = ST_IDLE
                                    expected_seq = None
                                    last_tx_done_t = time.time()

                                elif state in (ST_WAIT_PLC_ACK, ST_POLLING_PLC):
                                    # Caso 2: El PLC está activamente procesando una orden -> responder 0xE5 (Busy)
                                    try:
                                        client.sendall(b"\xE5")
                                    except (socket.error, BrokenPipeError, ConnectionResetError):
                                        break

                                else:
                                    # Caso 3: Estado ST_IDLE (sin transacción activa).
                                    # [CORRECCIÓN CRÍTICA v7]: NO responder 0xE5, porque 0xE5 le dice a Windows "sigo ocupado".
                                    # Responder con confirmación de reposo (libre sin datos), permitiendo que Micro/WIN
                                    # envíe inmediatamente el siguiente bloque de programa (_INSE).
                                    try:
                                        client.sendall(SD1_IDLE_ACK)
                                    except (socket.error, BrokenPipeError, ConnectionResetError):
                                        break

                            elif da == PLC_ADDR and fc in (0x49, 0x59, 0x69):
                                # Ping de presencia: responder ONLINE localmente
                                resp_ping = bytes([0x10, PC_ADDR, PLC_ADDR, 0x00, (PC_ADDR + PLC_ADDR) & 0xFF, 0x16])
                                try:
                                    client.sendall(resp_ping)
                                    print(f"[{ts()}] ⚡ Ping → ONLINE", flush=True)
                                except (socket.error, BrokenPipeError, ConnectionResetError):
                                    break
                            continue
                        else:
                            break

                    # Trama variable SD2 emitida por Micro/WIN
                    elif buf_qemu[0] == 0x68:
                        if len(buf_qemu) >= 4:
                            if buf_qemu[1] == buf_qemu[2] and buf_qemu[3] == 0x68:
                                total_len = buf_qemu[1] + 6
                                if len(buf_qemu) >= total_len:
                                    frame = bytes(buf_qemu[:total_len])
                                    del buf_qemu[:total_len]

                                    # Si va destinada a otra dirección fuera del PLC local
                                    if len(frame) >= 5 and frame[4] != PLC_ADDR:
                                        try:
                                            client.sendall(b"\xE5")
                                        except (socket.error, BrokenPipeError, ConnectionResetError):
                                            break
                                        continue

                                    # Intercepción crítica de negociación PDU (restringir a 240 bytes)
                                    target_pdu = b"\xF0\x00\x00\x01\x00\x01"
                                    if target_pdu in frame and len(frame) == 27:
                                        seq_hi = frame[11]
                                        seq_lo = frame[12]
                                        resp_payload = bytes([
                                            0x00, 0x02, 0x08, 0x32, 0x03, 0x00, 0x00, seq_hi, seq_lo,
                                            0x00, 0x08, 0x00, 0x00, 0x00, 0x00, 0xF0, 0x00, 0x00,
                                            0x01, 0x00, 0x01, 0x00, 0xF0
                                        ])
                                        fcs = calc_fcs(resp_payload)
                                        pdu_resp = bytes([0x68, len(resp_payload), len(resp_payload), 0x68]) + resp_payload + bytes([fcs, 0x16])

                                        try:
                                            client.sendall(b"\xE5")
                                        except (socket.error, BrokenPipeError, ConnectionResetError):
                                            break
                                        pending_resp = pdu_resp
                                        state = ST_RESP_READY
                                        last_tx_done_t = now
                                        print(f"[{ts()}] ⚡ PDU 240B interceptada → respuesta lista para sondeo", flush=True)
                                        continue

                                    # ACK 0xE5 inmediato a Micro/WIN para liberar su transmisor
                                    try:
                                        client.sendall(b"\xE5")
                                    except (socket.error, BrokenPipeError, ConnectionResetError):
                                        break

                                    # ── DEDUPLICACIÓN DE PETICIONES REPETIDAS ──
                                    seq_in = get_s7_seq(frame)
                                    is_dup = False
                                    if seq_in is not None:
                                        if state in (ST_WAIT_PLC_ACK, ST_POLLING_PLC) and current_frame is not None and get_s7_seq(current_frame) == seq_in:
                                            is_dup = True
                                        else:
                                            for qf in tx_queue:
                                                if get_s7_seq(qf) == seq_in:
                                                    is_dup = True
                                                    break

                                    if is_dup:
                                        print(f"[{ts()}] ⚡ Reintento Micro/WIN (seq=0x{seq_in:04X}) reconocido → ACK enviado, omitida duplicación en cola", flush=True)
                                        continue

                                    tx_queue.append(frame)
                                    fn_desc = get_s7_func_desc(frame)
                                    fn_str = f", fn={fn_desc}" if fn_desc else ""
                                    seq_str = f", seq=0x{seq_in:04X}{fn_str}" if seq_in is not None else ""
                                    print(f"[{ts()}] ← [MW] Trama encolada ({len(frame)}B{seq_str}) [cola: {len(tx_queue)}]", flush=True)
                                    continue
                                else:
                                    break
                            else:
                                del buf_qemu[:1]
                                continue
                        else:
                            break
                    else:
                        del buf_qemu[:1]

                # ── 5. Despacho y Máquina de Estados contra el PLC Físico ──

                # IDLE: Despachar siguiente petición pendiente de la cola
                if state == ST_IDLE and tx_queue and (now - last_tx_done_t) >= INTER_TX_GAP:
                    waiting_plc_job = False
                    current_frame = tx_queue.popleft()
                    retry_count = 0

                    # ── Sincronización Estricta de FCB hacia la CPU 214 física ──
                    frame_mut = bytearray(current_frame)
                    target_fc = 0x5C if plc_fcb == 0 else 0x7C
                    frame_mut[6] = target_fc
                    frame_mut[-2] = calc_fcs(frame_mut[4:-2])
                    current_frame_to_send = bytes(frame_mut)

                    expected_seq = get_s7_seq(current_frame)

                    send_to_plc(ser, current_frame_to_send)
                    state = ST_WAIT_PLC_ACK
                    now_tx = time.time()
                    poll_start_t = now_tx
                    last_tx_time = now_tx
                    seq_tx = get_s7_seq(current_frame)
                    fn_desc = get_s7_func_desc(current_frame)
                    fn_str = f", fn={fn_desc}" if fn_desc else ""
                    seq_str = f", seq=0x{seq_tx:04X}{fn_str}" if seq_tx is not None else ""
                    print(f"[{ts()}] → [PLC] Enviada trama ({len(current_frame_to_send)}B, FC=0x{target_fc:02X}{seq_str}) [cola restante: {len(tx_queue)}]", flush=True)

                # IDLE + waiting_plc_job: Sondear activamente al PLC en RS-485 para recoger su Job request (_DOWN 0x1B)
                elif state == ST_IDLE and waiting_plc_job and not tx_queue:
                    if (now - plc_job_poll_start_t) > 10.0:
                        waiting_plc_job = False
                        print(f"[{ts()}] ⚠ Timeout esperando petición _DOWN del PLC tras _INSE (10s)", flush=True)
                    elif (now - last_job_poll_t) >= POLL_INTERVAL:
                        if len(buf_ser) == 0 and (ser.in_waiting == 0):
                            send_to_plc(ser, poll_frame)
                            last_job_poll_t = time.time()

                # WAIT_PLC_ACK: Reintentar si el PLC no responde con 0xE5
                if state == ST_WAIT_PLC_ACK:
                    fn_desc = get_s7_func_desc(current_frame_to_send) if current_frame_to_send else ""
                    if fn_desc in ("_DELE", "_ENDB"):
                        # Operaciones pesadas de borrado o quemado físico en EEPROM (la CPU 214 requiere hasta 6.0s)
                        ack_timeout_dynamic = max(7.0, ACK_BASE_TIMEOUT + (len(current_frame_to_send) * ACK_INCREMENT))
                    elif fn_desc in ("_INSE", "_DOWN"):
                        # Apertura/asignación o transferencia de bloques en EEPROM
                        ack_timeout_dynamic = max(4.5, ACK_BASE_TIMEOUT + (len(current_frame_to_send) * ACK_INCREMENT))
                    else:
                        ack_timeout_dynamic = 0.8 + (len(current_frame_to_send) * ACK_INCREMENT) if current_frame_to_send else 0.8

                    if (now - last_tx_time) >= ack_timeout_dynamic:
                        retry_count += 1
                        if retry_count <= MAX_ACK_RETRIES and current_frame_to_send is not None:
                            print(f"[{ts()}] ⚠ PLC no dio ACK → reintento {retry_count}/{MAX_ACK_RETRIES} (tras {ack_timeout_dynamic:.2f}s)", flush=True)
                            time.sleep(TURNAROUND_DELAY)
                            send_to_plc(ser, current_frame_to_send)
                            last_tx_time = time.time()
                        else:
                            print(f"[{ts()}] ✗ PLC no respondió tras {MAX_ACK_RETRIES} reintentos → descartando trama", flush=True)
                            state = ST_IDLE
                            last_tx_done_t = time.time()
                            current_frame = None
                            current_frame_to_send = None
                            retry_count = 0

                # POLLING_PLC: Enviar sondeos periódicos SD1 de lectura
                if state == ST_POLLING_PLC:
                    # [CORRECCIÓN CRÍTICA ANTI-COLISIÓN v7]:
                    # Si el buffer serial ya está recibiendo bytes del PLC, congelar el temporizador
                    # de sondeo y NUNCA transmitir. Esto previene colisionar con tramas largas (ej. 237B)
                    if len(buf_ser) > 0 or (ser.in_waiting and ser.in_waiting > 0):
                        last_poll_t = now  # El PLC está transmitiendo en el bus: silencio absoluto en TX
                    elif (now - last_poll_t) >= POLL_INTERVAL:
                        send_to_plc(ser, poll_frame)
                        last_poll_t = time.time()

                    if (now - poll_start_t) >= POLL_TIMEOUT:
                        print(f"[{ts()}] ⚠ Timeout sondeando respuesta del PLC ({POLL_TIMEOUT}s)", flush=True)
                        plc_fcb ^= 1  # Resincronizar FCB para evitar duplicados en la siguiente petición
                        state = ST_IDLE
                        last_tx_done_t = time.time()
                        current_frame = None
                        current_frame_to_send = None
                        retry_count = 0

            # Limpieza de conexión cliente
            try:
                client.close()
            except Exception:
                pass

    except KeyboardInterrupt:
        print(f"\n[{ts()}] Terminando pasarela por solicitud del usuario...", flush=True)
    finally:
        ser.close()
        server.close()
        if os.path.exists(SOCKET_PATH):
            try:
                os.remove(SOCKET_PATH)
            except OSError:
                pass
        print(f"[{ts()}] Gateway cerrado limpiamente.", flush=True)


if __name__ == "__main__":
    main()
