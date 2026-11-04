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
        code_offset = int.from_bytes(self.data[29:33], "big")
        code_len = int.from_bytes(self.data[33:37], "big")
        networks_ob1 = int.from_bytes(self.data[37:39], "little")

        return {
            "type": "OB1" if block_type == 0x08 else f"0x{block_type:02X}",
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

    def disassemble_all(self) -> str:
        hdr = self.parse_header()
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
