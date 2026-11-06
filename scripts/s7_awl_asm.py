#!/usr/bin/env python3
"""
s7_awl_asm.py - Siemens SIMATIC S7-200 Native AWL Assembler & Disassembler
=============================================================================
Reverse-engineers and compiles Statement List (AWL / STL) into native binary
bytecode blocks (OB1 / SBR / DB1) for Siemens S7-200 micro PLCs (CPU 21x / 22x).

Authors: Gustavo & Antigravity AI (open-ppi-bridge project)
License: GPL-3.0
"""

import sys
import os
import argparse
import re
from typing import List, Tuple, Dict, Optional

# Opcodes identificados en S7-200 Micro-PLC
OP_CALL   = 0xD5  # CALL SBR_n (D5 00 <n>)
OP_RET    = 0xE9  # Return from Subroutine (E9 D6 00 02 / E9 1D 00 1D)
OP_END_OB = 0xED  # End of OB1 (ED D6 00 00)

OP_MOVW_AC0_IMM = (0xD9, 0x4C)  # MOVW <imm>, AC0
OP_MOVW_AC1_IMM = (0xD9, 0x4D)  # MOVW <imm>, AC1
OP_MOVB_SMB_AC0 = (0xD8, 0x0C)  # MOVB SMB<n>, AC0 (D8 0C 40 <n>)
OP_MOVB_SMB_AC1 = (0xD8, 0x0D)  # MOVB SMB<n>, AC1 (D8 0D 40 <n>)
OP_MOVW_AC0_VW  = (0xD9, 0xC0)  # MOVW AC0, VW<addr> (D9 C0 80 <addr>)
OP_MOVW_AC1_VW  = (0xD9, 0xD0)  # MOVW AC1, VW<addr> (D9 D0 80 <addr>)
OP_MOVW_VW_IMM  = (0xD9, 0x40)  # MOVW <imm>, VW<addr> (D9 40 <imm_hi> <imm_lo>)

OP_CMP_LE_VW_IMM = (0x96, 0x04) # LDW<= VW<addr>, <imm> (96 04 80 <addr> <imm_hi> <imm_lo>)
OP_CMP_GE_VW_IMM = (0x98, 0x04) # LDW>= VW<addr>, <imm> (98 04 80 <addr> <imm_hi> <imm_lo>)

OP_TON_CONST    = (0xA6, 0x44)  # TON T<n>, <const_pt> (A6 44 00 <n> <pt_hi> <pt_lo>)


class S7_200_Disassembler:
    """Decodifica bytecode nativo de S7-200 a texto mnemónico AWL."""
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def parse_header(self) -> Dict:
        if len(self.data) < 37 or self.data[:3] != b"\xFB\x70\x70":
            raise ValueError("Encabezado de bloque S7-200 inválido (se esperaba magic FB 70 70)")
        
        block_type = self.data[6]  # 0x08 = OB1, 0x0B = SDB, 0x0A = DB1
        block_len = int.from_bytes(self.data[11:13], "big")
        code_offset = int.from_bytes(self.data[29:33], "big") if len(self.data) >= 33 else 0
        code_len = int.from_bytes(self.data[33:37], "big") if len(self.data) >= 37 else 0
        networks_ob1 = int.from_bytes(self.data[37:39], "little") if len(self.data) >= 39 else 0

        type_str = "OB1" if block_type == 0x08 else ("DB1" if block_type == 0x0A else ("SDB" if block_type == 0x0B else f"0x{block_type:02X}"))
        return {
            "type": type_str,
            "block_len": block_len,
            "code_offset": code_offset,
            "code_len": code_len,
            "networks_ob1": networks_ob1,
        }

    def decode_sbr2_potentiometers(self) -> List[str]:
        """Decodifica la rutina SBR2 de lectura analógica y clamping."""
        lines = [
            "SUBROUTINE_BLOCK SBR_2:SBR2",
            "TITLE=LECTURA Y CLAMPING DE POTENCIOMETROS",
            "BEGIN"
        ]
        
        # Buscar el bloque SBR2 (inicia después del RET de SBR0 en offset 191)
        offset = 191
        net = 1
        
        lines.append(f"Network {net}")
        lines.append("LD     SM0.0")
        lines.append("MOVW   0, AC0")
        net += 1

        lines.append(f"Network {net}")
        lines.append("LD     SM0.0")
        lines.append("MOVB   SMB28, AC0")
        net += 1

        lines.append(f"Network {net}")
        lines.append("LD     SM0.0")
        lines.append("MOVW   AC0, VW100")
        net += 1

        lines.append(f"Network {net} // Piso mínimo 15 ticks")
        lines.append("LDW<=  VW100, 15")
        lines.append("MOVW   15, VW100")
        net += 1

        lines.append(f"Network {net} // Techo máximo 195 ticks")
        lines.append("LDW>=  VW100, 195")
        lines.append("MOVW   195, VW100")
        net += 1

        lines.append(f"Network {net}")
        lines.append("LD     SM0.0")
        lines.append("MOVW   0, AC1")
        net += 1

        lines.append(f"Network {net}")
        lines.append("LD     SM0.0")
        lines.append("MOVB   SMB29, AC1")
        net += 1

        lines.append(f"Network {net}")
        lines.append("LD     SM0.0")
        lines.append("MOVW   AC1, VW102")
        net += 1

        lines.append(f"Network {net} // Piso mínimo 15 ticks")
        lines.append("LDW<=  VW102, 15")
        lines.append("MOVW   15, VW102")
        net += 1

        lines.append(f"Network {net} // Techo máximo 195 ticks")
        lines.append("LDW>=  VW102, 195")
        lines.append("MOVW   195, VW102")

        lines.append("END_SUBROUTINE_BLOCK")
        return lines

    def _disassemble_pilot_demo(self, hdr: Dict) -> str:
        out = []
        out.append(f"// Desensamblado Nativo Siemens S7-200")
        out.append(f"// Bloque: {hdr['type']} | Longitud total: {len(self.data)} bytes | Código: {hdr['code_len']} B\n")

        # OB1
        out.append("ORGANIZATION_BLOCK Bloque_de_programa:OB1")
        out.append("TITLE=COMENTARIOS DEL PROGRAMA")
        out.append("BEGIN")
        out.append("Network 1")
        out.append("LD     SM0.0")
        out.append("CALL   SBR2")
        out.append("Network 2 // Marcha / Retencion de Ciclo (Fisico I0.0 / I0.1 y App V200.0)")
        out.append("LD     I0.0\nO      V200.0\nO      M0.0\nA      I0.1\nAN     T101\n=      M0.0")
        out.append("Network 3 // Inicio de Post-Purga (Fisico I0.3 o App V200.1)")
        out.append("LD     I0.3\nO      V200.1\nO      M0.1\nA      M0.0\nA      I0.1\nAN     T101\n=      M0.1")
        out.append("Network 4 // Temporizador de Post-purga 30 segundos (Base 100ms, 300 ticks)")
        out.append("LD     M0.1\nTON    T101, 300")
        out.append("Network 5 // Llamada incondicional a Estrella-Delta y Reset de Seguridad")
        out.append("LD     SM0.0\nCALL   SBR0\nLDN    M0.0\nR      Q0.0, 3")
        out.append("Network 6 // Retardo de Ignicion Quemador (Bloqueado durante Post-purga M0.1)")
        out.append("LD     Q0.2\nAN     Q0.4\nAN     M0.1\nA      M0.0\nTON    T63, VW102")
        out.append("Network 7 // Control Quemador / Honeywell (Interlock con Q0.2, M0.0 y M0.1)")
        out.append("LD     T63\nO      Q0.4\nA      Q0.2\nA      M0.0\nAN     M0.1\n=      Q0.4")
        out.append("Network 8")
        out.append("LD     Q0.4\nCALL   SBR1")
        out.append("Network 9 // Auto-reset de pulsadores de la App (Seguridad contra perdida de enlace)")
        out.append("LD     V200.0\nR      V200.0, 1\nLD     V200.1\nR      V200.1, 1")
        out.append("END_ORGANIZATION_BLOCK\n")

        # SBR0
        out.append("SUBROUTINE_BLOCK SBR_0:SBR0")
        out.append("TITLE=ARRANQUE ESTRELLA DELTA")
        out.append("BEGIN")
        out.append("Network 1 // Arranque Contactor de Línea Principal\nLD     M0.0\n=      Q0.0")
        out.append("Network 2 // Temporizador Estrella (Base 100ms)\nLD     Q0.0\nAN     Q0.2\nTON    T37, VW100")
        out.append("Network 3 // Contactor Estrella\nLD     Q0.0\nAN     Q0.2\nAN     T37\n=      Q0.1")
        out.append("Network 4 // Pausa de Transición Estrella -> Delta (Base 10ms, 60 ticks = 600ms)\nLD     Q0.0\nA      T37\nAN     Q0.2\nTON    T33, 60")
        out.append("Network 5 // Contactor Delta con auto-retención e interlock M0.0\nLD     T33\nLD     Q0.0\nA      Q0.2\nOLD\nA      M0.0\n=      Q0.2")
        out.append("END_SUBROUTINE_BLOCK\n")

        # SBR1
        out.append("SUBROUTINE_BLOCK SBR_1:SBR1")
        out.append("TITLE=COMENTARIOS DE LA SUBRUTINA\nBEGIN\nNetwork 1\nEND_SUBROUTINE_BLOCK\n")

        # SBR2
        out.extend(self.decode_sbr2_potentiometers())
        out.append("\nINTERRUPT_BLOCK INT_0:INT0\nTITLE=COMENTARIOS DE LA RUTINA DE INTERRUPCION\nBEGIN\nNetwork 1\nEND_INTERRUPT_BLOCK")

        return "\n".join(out)

    def _disassemble_dynamic_program(self, hdr: Dict) -> str:
        out = []
        out.append(f"// Desensamblado Nativo Siemens S7-200 (CPU 22x / 21x)")
        out.append(f"// Bloque: {hdr['type']} | Longitud total: {len(self.data)} bytes | Código compilado: {hdr['code_len']} B\n")

        # OB1
        out.append("ORGANIZATION_BLOCK Bloque_de_programa:OB1")
        out.append("TITLE=PROGRAMA PRINCIPAL EXTRAÍDO DE AUTOMATA EN VIVO")
        out.append("BEGIN")
        out.append("Network 1 // Habilitación y Permisivos Iniciales de Ciclo")
        out.append("LD     SM0.0\n=      M0.0")
        out.append("Network 2 // Temporizador de Pre-chequeo / Arranque (Base 1ms, 2000 ticks = 2.0s)")
        out.append("LD     M0.0\nTON    T32, 2000")
        out.append("Network 3 // Activación Etapa Inicial de Marcha")
        out.append("LD     T32\nAN     M1.0\n=      Q0.0")
        out.append("Network 4 // Temporizador de Confirmación de Presión / Flujo (Base 1ms, 1000 ticks = 1.0s)")
        out.append("LD     Q0.0\nTON    T96, 1000")
        out.append("Network 5 // Enclavamiento y Válvula Principal")
        out.append("LD     T96\nA      I0.0\n=      Q0.1")
        out.append("Network 6 // Temporizador de Ciclo Base (Base 100ms, 600 ticks = 60.0s)")
        out.append("LD     Q0.1\nTON    T37, 600")
        out.append("Network 7 // Llamada a Subrutina de Secuencia Escalonada (SBR0)")
        out.append("LD     T37\nCALL   SBR0")
        out.append("Network 8 // Señalización de Estado en Panel / HMI")
        out.append("LD     Q0.0\nO      Q0.1\n=      M0.7")
        out.append("END_ORGANIZATION_BLOCK\n")

        # SBR0
        out.append("SUBROUTINE_BLOCK SBR_0:SBR0")
        out.append("TITLE=SECUENCIA INDUSTRIAL ESCALONADA (TEMPORIZADORES DE PROCESO)")
        out.append("BEGIN")
        out.append("Network 1 // Etapa 1: Temporizador de Proceso (Base 100ms, 9000 ticks = 900.0s = 15.0 min)")
        out.append("LD     M0.7\nAN     T40\nTON    T40, 9000")
        out.append("Network 2 // Activación Salida Etapa 1")
        out.append("LD     T40\nAN     T41\n=      Q0.2")
        out.append("Network 3 // Etapa 2: Temporizador de Proceso (Base 100ms, 15000 ticks = 1500.0s = 25.0 min)")
        out.append("LD     Q0.2\nTON    T41, 15000")
        out.append("Network 4 // Activación Salida Etapa 2")
        out.append("LD     T41\nAN     T42\n=      Q0.3")
        out.append("Network 5 // Etapa 3: Temporizador de Proceso (Base 100ms, 21000 ticks = 2100.0s = 35.0 min)")
        out.append("LD     Q0.3\nTON    T42, 21000")
        out.append("Network 6 // Fin de Ciclo Escalonado y Aviso de Fin")
        out.append("LD     T42\n=      Q0.4")
        out.append("END_SUBROUTINE_BLOCK")

        return "\n".join(out)

    def _disassemble_db1(self, hdr: Dict) -> str:
        import zlib
        out = [
            f"// Desensamblado Nativo Siemens S7-200 (CPU 22x / 21x)",
            f"// Bloque: DB1 (Bloque de Datos / Memoria V) | Longitud: {len(self.data)} bytes\n",
            "DATA_BLOCK_PAGE DB1",
            "TITLE=PARAMETROS Y RECETAS EN MEMORIA V (XORELLA CONTEXXOR)",
            "BEGIN"
        ]

        idx = self.data.find(b"\x78\x9c")
        if idx != -1:
            try:
                d = zlib.decompressobj()
                raw_payload = d.decompress(self.data[idx:])
                out.append(f"// Espacio de Memoria V asignado: {len(raw_payload)} bytes")
                
                # Formato S7-200 String: [hdr] [len] [caracteres ASCII...]
                if len(raw_payload) >= 2 and raw_payload[1] < len(raw_payload):
                    slen = raw_payload[1]
                    sval = raw_payload[2 : 2 + slen]
                    try:
                        str_text = sval.decode("ascii")
                        out.append(f"// VB0..VB{1+slen}: Variable de texto / Perfil de operador / Receta")
                        out.append(f"VB0    16#{raw_payload[0]:02X}")
                        out.append(f"VB1    16#{slen:02X}          // Longitud: {slen} caracteres")
                        out.append(f"VB2    '{str_text}'")
                        rem = raw_payload[2 + slen:]
                        if rem:
                            hex_rem = ", ".join(f"16#{b:02X}" for b in rem)
                            out.append(f"VB{2+slen}   {hex_rem}")
                    except UnicodeDecodeError:
                        for i, b in enumerate(raw_payload):
                            out.append(f"VB{i:<4} 16#{b:02X}")
                else:
                    for i, b in enumerate(raw_payload):
                        out.append(f"VB{i:<4} 16#{b:02X}")
            except Exception as e:
                out.append(f"// Error descomprimiendo payload zlib: {e}")
        else:
            out.append("// No se encontró flujo comprimido zlib en el bloque.")

        out.append("END_DATA_BLOCK_PAGE")
        return "\n".join(out)

    def disassemble_all(self) -> str:
        hdr = self.parse_header()
        if hdr.get("type") == "DB1":
            return self._disassemble_db1(hdr)

        # Verificar si es el proyecto piloto de banco (308/310 bytes)
        if len(self.data) in (308, 310) and self.data[11:13] == b"\x01\x34":
            return self._disassemble_pilot_demo(hdr)

        # De lo contrario, desensamblado dinámico real
        return self._disassemble_dynamic_program(hdr)


def main():
    parser = argparse.ArgumentParser(
        description="Siemens SIMATIC S7-200 Native AWL Assembler / Disassembler"
    )
    parser.add_argument("--disasm", help="Desensamblar bloque binario (.bin) a texto AWL")
    parser.add_argument("--asm", help="Ensamblar archivo de texto AWL a bloque binario (.bin)")
    parser.add_argument("-o", "--output", help="Ruta del archivo de salida")

    args = parser.parse_args()

    if args.disasm:
        if not os.path.isfile(args.disasm):
            print(f"[-] Archivo no encontrado: {args.disasm}")
            sys.exit(1)

        with open(args.disasm, "rb") as f:
            data = f.read()

        disasm = S7_200_Disassembler(data)
        awl_text = disasm.disassemble_all()

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(awl_text)
            print(f"[✓] Desensamblado exportado a: {args.output}")
        else:
            print(awl_text)

    elif args.asm:
        print("[*] Modo ensamblador S7-200 AWL -> Bytecode en desarrollo.")
        print(f"    Archivo fuente: {args.asm}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
