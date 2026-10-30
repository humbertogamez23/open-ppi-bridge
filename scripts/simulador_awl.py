#!/usr/bin/env python3
"""
Simulador y validador interactivo de lógica AWL / KOP para Siemens SIMATIC S7-200.
Permite testear PRUEBAPILOTO.awl sin hardware físico.
"""

import sys
import time
import argparse
import select
import termios
import tty
import os

class S7_200_Simulator:
    def __init__(self, fix_oscillation: bool = False, fix_clamping: bool = False):
        self.fix_oscillation = fix_oscillation
        self.fix_clamping = fix_clamping
        
        # Entradas digitales (I)
        self.I = {
            "I0.0": False, # START
            "I0.1": True,  # STOP (NC por defecto)
            "I0.2": True,  # PARO EMERGENCIA (NC por defecto)
            "I0.3": False, # CALOR (FY800)
            "I0.4": False,
            "I0.5": False,
        }
        # Salidas digitales (Q)
        self.Q = {
            "Q0.0": False, # M1P (Principal)
            "Q0.1": False, # M1E (Estrella)
            "Q0.2": False, # M1D (Delta)
            "Q0.3": False, # M2
            "Q0.4": False, # HW (Honeywell)
            "Q0.5": False, # IGNICION
        }
        # Marcas internas (M)
        self.M = {f"M0.{i}": False for i in range(8)}
        # Marcas especiales (SM)
        self.SM = {"SM0.0": True, "SM0.1": True}
        
        # Potenciómetros analógicos (0..255)
        self.SMB28 = 40  # ~4.0 s en T37
        self.SMB29 = 30  # ~3.0 s en T63
        
        # Acumuladores
        self.AC0 = 0
        self.AC1 = 0
        
        # Variables de memoria V
        self.VW = {"VW100": 0, "VW102": 0}
        
        # Temporizadores
        self.timers = {
            "T37":  {"in": False, "accum": 0.0, "pt": 0, "done": False, "base_sec": 0.1},
            "T33":  {"in": False, "accum": 0.0, "pt": 0, "done": False, "base_sec": 0.01},
            "T63":  {"in": False, "accum": 0.0, "pt": 0, "done": False, "base_sec": 0.1},
            "T101": {"in": False, "accum": 0.0, "pt": 0, "done": False, "base_sec": 0.1},
        }

    def update_timer(self, name: str, enable: bool, pt: int, dt: float):
        t = self.timers[name]
        t["in"] = enable
        t["pt"] = pt
        if enable:
            ticks_added = dt / t["base_sec"]
            t["accum"] += ticks_added
            if t["accum"] >= pt:
                t["done"] = True
                t["accum"] = pt
        else:
            t["accum"] = 0.0
            t["done"] = False

    def sbr2(self):
        """Lectura de potenciómetros analógicos"""
        self.AC0 = self.SMB28 & 0xFF
        self.VW["VW100"] = self.AC0
        if self.VW["VW100"] <= 15:
            self.VW["VW100"] = 15 if self.fix_clamping else self.AC0
        if self.VW["VW100"] >= 195:
            self.VW["VW100"] = 195 if self.fix_clamping else self.AC0

        self.AC1 = self.SMB29 & 0xFF
        self.VW["VW102"] = self.AC1
        if self.VW["VW102"] <= 15:
            self.VW["VW102"] = 15 if self.fix_clamping else self.AC1
        if self.VW["VW102"] >= 195:
            self.VW["VW102"] = 195 if self.fix_clamping else self.AC1

    def sbr0(self, dt: float):
        """Subrutina Estrella-Triángulo"""
        # Net 1: Q0.0 (Principal)
        self.Q["Q0.0"] = self.SM["SM0.0"]

        # Net 2: TON T37
        en_t37 = self.Q["Q0.0"] and (not self.Q["Q0.2"])
        self.update_timer("T37", en_t37, self.VW["VW100"], dt)

        # Net 3: Q0.1 (Estrella)
        self.Q["Q0.1"] = self.Q["Q0.0"] and (not self.Q["Q0.2"]) and (not self.timers["T37"]["done"])

        # Net 4: TON T33
        en_t33 = self.Q["Q0.0"] and self.timers["T37"]["done"] and (not self.Q["Q0.2"])
        self.update_timer("T33", en_t33, 60, dt)

        # Net 5: Q0.2 (Delta)
        b1 = self.timers["T33"]["done"]
        b2 = self.Q["Q0.0"] and self.Q["Q0.2"]
        self.Q["Q0.2"] = b1 or b2

    def scan_cycle(self, dt: float):
        # Net 1: CALL SBR2
        if self.SM["SM0.0"]:
            self.sbr2()

        # Net 2: M0.0
        b1 = self.I["I0.0"] and self.I["I0.1"]
        if self.fix_oscillation:
            b2 = self.M["M0.0"] and (not self.timers["T101"]["done"])
        else:
            b2 = (not self.M["M0.0"]) and (not self.timers["T101"]["done"])
        self.M["M0.0"] = b1 or b2

        # Net 3: M0.1
        self.M["M0.1"] = (self.I["I0.3"] or self.M["M0.1"]) and (not self.timers["T101"]["done"])

        # Net 4: TON T101
        self.update_timer("T101", self.M["M0.1"], 300, dt)

        # Net 5: CALL SBR0
        if self.M["M0.0"]:
            self.sbr0(dt)
        else:
            # Si M0.0 se desactiva, apagamos las salidas asociadas para simular comportamiento seguro
            if self.fix_oscillation:
                self.Q["Q0.0"] = False
                self.Q["Q0.1"] = False
                self.Q["Q0.2"] = False
                self.update_timer("T37", False, 0, dt)
                self.update_timer("T33", False, 0, dt)

        # Net 6: TON T63
        en_t63 = self.Q["Q0.2"] and (not self.Q["Q0.4"])
        self.update_timer("T63", en_t63, self.VW["VW102"], dt)

        # Net 7: Q0.4 (Honeywell)
        self.Q["Q0.4"] = (self.timers["T63"]["done"] or self.Q["Q0.4"]) and (not self.M["M0.1"])

        self.SM["SM0.1"] = False


def run_diagnostic():
    print("=" * 72)
    print(" 🛠️  ANÁLISIS ESTÁTICO Y SIMULACIÓN TÉCNICA: PRUEBAPILOTO.awl")
    print("=" * 72)

    print("\n[1] TEST DE RETENCIÓN DE MARCHA (OB1 - Network 2):")
    sim_raw = S7_200_Simulator(fix_oscillation=False)
    sim_raw.I["I0.1"] = True # STOP cerrado
    states = []
    for _ in range(4):
        sim_raw.scan_cycle(0.01)
        states.append(sim_raw.M["M0.0"])
    
    print(f"    • AWL Original (LDN M0.0): M0.0 oscila -> {states}")
    print("      ❌ Fallo: LDN M0.0 actúa como contacto NC; invierte el estado cada scan.")
    print("      💡 Corrección: Usar LD M0.0 (contacto NA de auto-retención).\n")

    print("[2] TEST DE ACONDICIONAMIENTO DE POTENCIÓMETROS (SBR2 - Net 4, 5, 9, 10):")
    sim_pot = S7_200_Simulator(fix_clamping=False)
    sim_pot.SMB28 = 5   # Menor que 15
    sim_pot.SMB29 = 220 # Mayor que 195
    sim_pot.scan_cycle(0.01)
    print(f"    • SMB28 = 5   -> VW100 = {sim_pot.VW['VW100']} ticks")
    print(f"    • SMB29 = 220 -> VW102 = {sim_pot.VW['VW102']} ticks")
    print("      ⚠️ Advertencia: Las comparaciones 'MOVW AC0, VW100' no recortan los valores")
    print("         porque AC0 ya contiene el valor sin saturar.")
    print("         Si deseaba piso y techo (15 y 195): usar 'MOVW 15, VW100' y 'MOVW 195, VW100'.\n")

    print("[3] SIMULACIÓN SECUENCIA COMPLETA (Con corrección de auto-retención aplicada):")
    sim = S7_200_Simulator(fix_oscillation=True, fix_clamping=True)
    sim.SMB28 = 30 # T37: 3.0s (30 * 100ms)
    sim.SMB29 = 20 # T63: 2.0s (20 * 100ms)
    
    # Pulso de START (I0.0)
    sim.I["I0.0"] = True
    sim.scan_cycle(0.05)
    sim.I["I0.0"] = False

    dt = 0.05
    t = 0.05
    headers = f"{'Tiempo':>8} | {'M0.0':>5} | {'Q0.0 (Línea)':>12} | {'Q0.1 (Estrella)':>15} | {'Q0.2 (Delta)':>12} | {'Q0.4 (HW)':>10} | {'T37':>8} | {'T33':>8} | {'Fase Activa':<20}"
    print(headers)
    print("-" * len(headers))

    milestones = [
        (0.1, "Arranque Estrella"),
        (1.5, "Régimen Estrella"),
        (3.0, "Fin T37 (Desconecta Q0.1)"),
        (3.3, "Pausa Transición T33"),
        (3.65, "Entrada en Delta (Q0.2)"),
        (4.5, "Régimen Delta"),
        (5.7, "Disparo HW (Q0.4)"),
    ]
    
    cur_m = 0
    while t <= 6.0:
        sim.scan_cycle(dt)
        t += dt
        if cur_m < len(milestones) and t >= milestones[cur_m][0]:
            target_t, label = milestones[cur_m]
            t37_s = f"{int(sim.timers['T37']['accum'])}/{sim.VW['VW100']}"
            t33_s = f"{int(sim.timers['T33']['accum'])}/60"
            print(f"{t:7.2f}s | {int(sim.M['M0.0']):>5} | {int(sim.Q['Q0.0']):>12} | {int(sim.Q['Q0.1']):>15} | {int(sim.Q['Q0.2']):>12} | {int(sim.Q['Q0.4']):>10} | {t37_s:>8} | {t33_s:>8} | {label:<20}")
            cur_m += 1

    print("\n[✓] Simulación finalizada exitosamente.")
    print("    Para probar el simulador interactivo por consola con botones:")
    print("    $ python3 /home/gus05/rs485_ft232rl/scripts/simulador_awl.py --interactive\n")


def run_interactive():
    # Modo interactivo en terminal sin requerir librerías externas complejas
    sim = S7_200_Simulator(fix_oscillation=True, fix_clamping=True)
    
    # Salvar configuración del terminal
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    
    os.system("clear")
    print("\033[?25l", end="") # Ocultar cursor
    
    try:
        running = True
        last_time = time.time()
        msg = "Listo para interactuar."
        
        while running:
            # Comprobar teclas presionadas (non-blocking)
            r, _, _ = select.select([sys.stdin], [], [], 0.05)
            if r:
                ch = sys.stdin.read(1)
                if ch in ('q', 'Q', '\x03'): # 'q' o Ctrl+C
                    running = False
                    break
                elif ch == '1': # Toggle START (I0.0)
                    sim.I["I0.0"] = not sim.I["I0.0"]
                    msg = f"START (I0.0) -> {'ON (Pulsado)' if sim.I['I0.0'] else 'OFF'}"
                elif ch == '2': # Toggle STOP (I0.1)
                    sim.I["I0.1"] = not sim.I["I0.1"]
                    msg = f"STOP (I0.1) -> {'CERRADO (Normal)' if sim.I['I0.1'] else 'ABIERTO (Paro)'}"
                elif ch == '3': # Toggle CALOR (I0.3)
                    sim.I["I0.3"] = not sim.I["I0.3"]
                    msg = f"CALOR FY800 (I0.3) -> {'ON' if sim.I['I0.3'] else 'OFF'}"
                elif ch == '+': # Subir pot 0 (SMB28)
                    sim.SMB28 = min(255, sim.SMB28 + 10)
                    msg = f"Potenciómetro SMB28 (T37) -> {sim.SMB28} ticks ({sim.SMB28*0.1:.1f}s)"
                elif ch == '-': # Bajar pot 0 (SMB28)
                    sim.SMB28 = max(0, sim.SMB28 - 10)
                    msg = f"Potenciómetro SMB28 (T37) -> {sim.SMB28} ticks ({sim.SMB28*0.1:.1f}s)"
                elif ch == '*': # Subir pot 1 (SMB29)
                    sim.SMB29 = min(255, sim.SMB29 + 10)
                    msg = f"Potenciómetro SMB29 (T63) -> {sim.SMB29} ticks ({sim.SMB29*0.1:.1f}s)"
                elif ch == '/': # Bajar pot 1 (SMB29)
                    sim.SMB29 = max(0, sim.SMB29 - 10)
                    msg = f"Potenciómetro SMB29 (T63) -> {sim.SMB29} ticks ({sim.SMB29*0.1:.1f}s)"

            now = time.time()
            dt = now - last_time
            last_time = now
            sim.scan_cycle(dt)
            
            # Dibujar dashboard en la esquina superior
            out = []
            out.append("\033[H\033[2J") # Cursor a 0,0 y limpiar
            out.append("╔══════════════════════════════════════════════════════════════════════════╗")
            out.append("║        SIMULADOR INTERACTIVO SIEMENS SIMATIC S7-200 (CPU 214)            ║")
            out.append("║                   Lógica: PRUEBAPILOTO.awl                               ║")
            out.append("╠══════════════════════════════════════════════════════════════════════════╣")
            
            # Estados de Entradas
            s_i0 = "\033[1;32m[ON ]\033[0m" if sim.I["I0.0"] else "\033[90m[OFF]\033[0m"
            s_i1 = "\033[1;32m[ON ]\033[0m" if sim.I["I0.1"] else "\033[1;31m[OFF]\033[0m"
            s_i3 = "\033[1;32m[ON ]\033[0m" if sim.I["I0.3"] else "\033[90m[OFF]\033[0m"
            out.append(f"║ ENTRADAS:   [1] I0.0 (START): {s_i0}  [2] I0.1 (STOP): {s_i1}  [3] I0.3 (CALOR): {s_i3} ║")
            
            # Potenciómetros
            out.append(f"║ POTS:       [+/-] SMB28: {sim.SMB28:3d} ({sim.SMB28*0.1:4.1f}s)   [*//] SMB29: {sim.SMB29:3d} ({sim.SMB29*0.1:4.1f}s)          ║")
            out.append("╠══════════════════════════════════════════════════════════════════════════╣")
            
            # Salidas Digitales
            s_q0 = "\033[1;32m● ACTIVADA\033[0m" if sim.Q["Q0.0"] else "\033[90m○ Apagada \033[0m"
            s_q1 = "\033[1;33m● ACTIVADA\033[0m" if sim.Q["Q0.1"] else "\033[90m○ Apagada \033[0m"
            s_q2 = "\033[1;36m● ACTIVADA\033[0m" if sim.Q["Q0.2"] else "\033[90m○ Apagada \033[0m"
            s_q4 = "\033[1;35m● ACTIVADA\033[0m" if sim.Q["Q0.4"] else "\033[90m○ Apagada \033[0m"
            
            out.append(f"║ SALIDAS:                                                                 ║")
            out.append(f"║   • Q0.0 (M1P Línea Principal): {s_q0}                                  ║")
            out.append(f"║   • Q0.1 (M1E Estrella):        {s_q1}                                  ║")
            out.append(f"║   • Q0.2 (M1D Delta):           {s_q2}                                  ║")
            out.append(f"║   • Q0.4 (HW Quemador):         {s_q4}                                  ║")
            out.append("╠══════════════════════════════════════════════════════════════════════════╣")
            
            # Temporizadores
            t37_done = "DONE" if sim.timers["T37"]["done"] else "RUN " if sim.timers["T37"]["in"] else "OFF "
            t33_done = "DONE" if sim.timers["T33"]["done"] else "RUN " if sim.timers["T33"]["in"] else "OFF "
            t63_done = "DONE" if sim.timers["T63"]["done"] else "RUN " if sim.timers["T63"]["in"] else "OFF "
            t101_done = "DONE" if sim.timers["T101"]["done"] else "RUN " if sim.timers["T101"]["in"] else "OFF "
            
            out.append(f"║ TEMPORIZADORES:                                                          ║")
            out.append(f"║   • T37  (Estrella):   [{t37_done}] Acc: {int(sim.timers['T37']['accum']):3d} / PT: {sim.VW['VW100']:3d} ticks          ║")
            out.append(f"║   • T33  (Pausa):      [{t33_done}] Acc: {int(sim.timers['T33']['accum']):3d} / PT:  60 ticks          ║")
            out.append(f"║   • T63  (Honeywell):  [{t63_done}] Acc: {int(sim.timers['T63']['accum']):3d} / PT: {sim.VW['VW102']:3d} ticks          ║")
            out.append(f"║   • T101 (Chispero):   [{t101_done}] Acc: {int(sim.timers['T101']['accum']):3d} / PT: 300 ticks          ║")
            out.append("╠══════════════════════════════════════════════════════════════════════════╣")
            out.append(f"║ MENSAJE: {msg:<63} ║")
            out.append("║ Controles: [1] START  [2] STOP  [3] CALOR  [+/-] Pot0  [*//] Pot1  [q] Salir  ║")
            out.append("╚══════════════════════════════════════════════════════════════════════════╝")
            
            sys.stdout.write("\n".join(out) + "\n")
            sys.stdout.flush()
            time.sleep(0.04)

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        print("\033[?25h") # Restaurar cursor
        print("\nSimulador cerrado correctamente.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simulador S7-200 para PRUEBAPILOTO.awl")
    parser.add_argument("--interactive", action="store_true", help="Iniciar consola interactiva")
    args = parser.parse_args()

    if args.interactive:
        run_interactive()
    else:
        run_diagnostic()
