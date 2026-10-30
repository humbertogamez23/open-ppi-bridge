#!/usr/bin/env python3
"""
Generador del diagrama Ladder (KOP) estilo Siemens STEP 7 Micro/WIN
específico para CPU 214 Rel 00.91 usando las instrucciones soportadas MUL y DIV (sin cruz roja).
"""
from PIL import Image, ImageDraw, ImageFont
import os
import shutil

WIDTH = 1250
HEIGHT = 1750
BG_COLOR = (255, 255, 255)
LINE_COLOR = (20, 20, 20)
BOX_BG = (248, 250, 254)
BOX_HEADER = (215, 228, 248)
HEADER_BG = (225, 235, 248)
TEXT_COLOR = (15, 15, 15)
LABEL_COLOR = (0, 75, 160)     # Blue for tags/symbols
ADDR_COLOR = (160, 25, 25)     # Red for addresses
VAL_COLOR = (0, 95, 175)       # Blue for literal values / variables
COMMENT_COLOR = (85, 85, 85)
ACCENT_GREEN = (0, 125, 45)

FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"

f_title = ImageFont.truetype(FONT_BOLD, 18)
f_net_title = ImageFont.truetype(FONT_BOLD, 14)
f_body = ImageFont.truetype(FONT_REG, 12)
f_sym = ImageFont.truetype(FONT_BOLD, 12)
f_addr = ImageFont.truetype(FONT_MONO, 11)
f_box_title = ImageFont.truetype(FONT_BOLD, 13)
f_box_io = ImageFont.truetype(FONT_BOLD, 11)
f_box_val = ImageFont.truetype(FONT_MONO, 12)

img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
draw = ImageDraw.Draw(img)

# Main Title banner
draw.rectangle([(0, 0), (WIDTH, 46)], fill=(22, 54, 115))
draw.text((25, 13), "Siemens STEP 7-Micro/WIN  |  Esquema 100% Nativo CPU 214 (MUL / DIV sin MUL_I / DIV_I)", fill=(255, 255, 255), font=f_title)

RAIL_X = 60
RIGHT_RAIL_X = 1190

# Rails
draw.line([(RAIL_X, 50), (RAIL_X, HEIGHT - 20)], fill=(40, 40, 40), width=4)
draw.line([(RIGHT_RAIL_X, 50), (RIGHT_RAIL_X, HEIGHT - 20)], fill=(130, 130, 130), width=2)

def draw_network_header(y, num, title, comment=""):
    draw.rectangle([(RAIL_X - 15, y), (RIGHT_RAIL_X + 15, y + 25)], fill=HEADER_BG, outline=(175, 195, 220))
    draw.text((RAIL_X, y + 4), f"Network {num}: {title}", fill=(0, 40, 105), font=f_net_title)
    if comment:
        draw.text((RAIL_X + 10, y + 29), f"// {comment}", fill=COMMENT_COLOR, font=f_body)
    return y + (50 if comment else 34)

def draw_contact(x, y, sym, addr, is_nc=False):
    draw.line([(x, y), (x + 18, y)], fill=LINE_COLOR, width=2)
    draw.line([(x + 18, y - 14), (x + 18, y + 14)], fill=LINE_COLOR, width=2)
    draw.line([(x + 36, y - 14), (x + 36, y + 14)], fill=LINE_COLOR, width=2)
    draw.line([(x + 36, y), (x + 54, y)], fill=LINE_COLOR, width=2)
    
    if is_nc:
        draw.line([(x + 20, y + 13), (x + 34, y - 13)], fill=LINE_COLOR, width=2)
        
    draw.text((x + 2, y - 38), sym, fill=LABEL_COLOR, font=f_sym)
    draw.text((x + 2, y - 24), addr, fill=ADDR_COLOR, font=f_addr)
    return x + 54

def draw_coil(x, y, sym, addr):
    draw.line([(x, y), (x + 15, y)], fill=LINE_COLOR, width=2)
    draw.arc([(x + 15, y - 14), (x + 27, y + 14)], 90, 270, fill=LINE_COLOR, width=2)
    draw.arc([(x + 37, y - 14), (x + 49, y + 14)], 270, 90, fill=LINE_COLOR, width=2)
    draw.line([(x + 49, y), (x + 64, y)], fill=LINE_COLOR, width=2)
    
    draw.text((x + 5, y - 38), sym, fill=LABEL_COLOR, font=f_sym)
    draw.text((x + 5, y - 24), addr, fill=ADDR_COLOR, font=f_addr)
    return x + 64

def draw_microwin_box(x, y, title, in_pins, out_pins, w=110, h=70):
    draw.rectangle([(x, y), (x + w, y + h)], fill=BOX_BG, outline=LINE_COLOR, width=2)
    draw.rectangle([(x, y), (x + w, y + 20)], fill=BOX_HEADER, outline=LINE_COLOR, width=1)
    
    bbox = f_box_title.getbbox(title)
    tw = bbox[2] - bbox[0]
    draw.text((x + (w - tw) // 2, y + 2), title, fill=(10, 30, 80), font=f_box_title)
    
    # Inputs
    n_in = len(in_pins)
    spacing_in = (h - 22) / (n_in + 1)
    in_ys = []
    for i, (pin, val) in enumerate(in_pins):
        py = int(y + 20 + spacing_in * (i + 1))
        in_ys.append(py)
        draw.line([(x - 25, py), (x, py)], fill=LINE_COLOR, width=2)
        draw.text((x + 5, py - 6), pin, fill=TEXT_COLOR, font=f_box_io)
        if val:
            draw.text((x - 65, py - 18), val, fill=VAL_COLOR, font=f_box_val)
            
    # Outputs
    n_out = len(out_pins)
    out_ys = []
    if n_out > 0:
        spacing_out = (h - 22) / (n_out + 1)
        for i, (pin, val) in enumerate(out_pins):
            py = int(y + 20 + spacing_out * (i + 1))
            out_ys.append(py)
            draw.line([(x + w, py), (x + w + 25, py)], fill=LINE_COLOR, width=2)
            draw.text((x + w - 30, py - 6), pin, fill=TEXT_COLOR, font=f_box_io)
            if val:
                draw.text((x + w + 8, py - 18), val, fill=VAL_COLOR, font=f_box_val)
                
    return (x, y, w, h, in_ys, out_ys)

cur_y = 60

# -------------------------------------------------------------
# NETWORK 1: Escalado Potenciómetro 0 (SMB28 -> VW100 / DIV 3 -> VW106)
# -------------------------------------------------------------
cur_y = draw_network_header(cur_y, 1, "Escalado Potenciómetro 0 (SMB28 -> VW106 = 0 a 8.5s para T37)", 
                            "Usa MOV_B y DIV (disponibles en CPU 214). DIV VW100 / 3 deja el cociente 0..85 en VW106.")

y_w1 = cur_y + 35
draw.line([(RAIL_X, y_w1), (RAIL_X + 30, y_w1)], fill=LINE_COLOR, width=2)
draw_contact(RAIL_X + 30, y_w1, "SIEMPRE_ON", "SM0.0")

trunk1_x = RAIL_X + 115
draw.line([(RAIL_X + 84, y_w1), (trunk1_x, y_w1)], fill=LINE_COLOR, width=2)

box_x = trunk1_x + 95

# Box 1: MOV_B 0 -> VB100
y_b1 = y_w1 - 15
draw.line([(trunk1_x, y_w1), (trunk1_x, y_b1 + 35)], fill=LINE_COLOR, width=2)
draw.line([(trunk1_x, y_b1 + 35), (box_x - 25, y_b1 + 35)], fill=LINE_COLOR, width=2)
draw_microwin_box(box_x, y_b1, "MOV_B", [("IN", "0")], [("OUT", "VB100")], w=90, h=55)

# Box 2: MOV_B SMB28 -> VB101
y_b2 = y_b1 + 65
draw.line([(trunk1_x, y_b1 + 35), (trunk1_x, y_b2 + 35)], fill=LINE_COLOR, width=2)
draw.line([(trunk1_x, y_b2 + 35), (box_x - 25, y_b2 + 35)], fill=LINE_COLOR, width=2)
draw_microwin_box(box_x, y_b2, "MOV_B", [("IN", "SMB28")], [("OUT", "VB101")], w=90, h=55)

# Box 3: DIV VW100 / 3 -> VD104 (Cociente queda en VW106)
y_b3 = y_b2 + 65
draw.line([(trunk1_x, y_b2 + 35), (trunk1_x, y_b3 + 30)], fill=LINE_COLOR, width=2)
draw.line([(trunk1_x, y_b3 + 30), (box_x - 25, y_b3 + 30)], fill=LINE_COLOR, width=2)
draw_microwin_box(box_x, y_b3, "DIV", [("IN1", "VW100"), ("IN2", "3")], [("OUT", "VD104")], w=105, h=65)

draw.text((box_x + 225, y_b3 + 18), "==> Cociente en VW106 = 0..85 ticks (0.0s .. 8.5s para T37)", fill=ACCENT_GREEN, font=f_sym)

cur_y = y_b3 + 80

# -------------------------------------------------------------
# NETWORK 2: Escalado Potenciómetro 1 (SMB29 -> VW102 / DIV 3 -> VW112)
# -------------------------------------------------------------
cur_y = draw_network_header(cur_y, 2, "Escalado Potenciómetro 1 (SMB29 -> VW112 = 0 a 8.5s para T38)", 
                            "Usa MOV_B y DIV (nativos CPU 214). El cociente de VD110 queda en VW112 para T38.")

y_w2 = cur_y + 35
draw.line([(RAIL_X, y_w2), (RAIL_X + 30, y_w2)], fill=LINE_COLOR, width=2)
draw_contact(RAIL_X + 30, y_w2, "SIEMPRE_ON", "SM0.0")

trunk2_x = RAIL_X + 115
draw.line([(RAIL_X + 84, y_w2), (trunk2_x, y_w2)], fill=LINE_COLOR, width=2)

# Box 1: MOV_B 0 -> VB102
y_b1_2 = y_w2 - 15
draw.line([(trunk2_x, y_w2), (trunk2_x, y_b1_2 + 35)], fill=LINE_COLOR, width=2)
draw.line([(trunk2_x, y_b1_2 + 35), (box_x - 25, y_b1_2 + 35)], fill=LINE_COLOR, width=2)
draw_microwin_box(box_x, y_b1_2, "MOV_B", [("IN", "0")], [("OUT", "VB102")], w=90, h=55)

# Box 2: MOV_B SMB29 -> VB103
y_b2_2 = y_b1_2 + 65
draw.line([(trunk2_x, y_b1_2 + 35), (trunk2_x, y_b2_2 + 35)], fill=LINE_COLOR, width=2)
draw.line([(trunk2_x, y_b2_2 + 35), (box_x - 25, y_b2_2 + 35)], fill=LINE_COLOR, width=2)
draw_microwin_box(box_x, y_b2_2, "MOV_B", [("IN", "SMB29")], [("OUT", "VB103")], w=90, h=55)

# Box 3: DIV VW102 / 3 -> VD110 (Cociente queda en VW112)
y_b3_2 = y_b2_2 + 65
draw.line([(trunk2_x, y_b2_2 + 35), (trunk2_x, y_b3_2 + 30)], fill=LINE_COLOR, width=2)
draw.line([(trunk2_x, y_b3_2 + 30), (box_x - 25, y_b3_2 + 30)], fill=LINE_COLOR, width=2)
draw_microwin_box(box_x, y_b3_2, "DIV", [("IN1", "VW102"), ("IN2", "3")], [("OUT", "VD110")], w=105, h=65)

draw.text((box_x + 225, y_b3_2 + 18), "==> Cociente en VW112 = 0..85 ticks (0.0s .. 8.5s para T38)", fill=ACCENT_GREEN, font=f_sym)

cur_y = y_b3_2 + 80

# -------------------------------------------------------------
# NETWORK 3: Marcha / Parada Contactor Principal M1P
# -------------------------------------------------------------
cur_y = draw_network_header(cur_y, 3, "Marcha / Parada del Contactor Principal (M1P / Q0.0)", 
                            "Pulsador START (I0.0) con auto-enclavamiento y desenergización por STP o Emergencia")

y_w3 = cur_y + 42
draw.line([(RAIL_X, y_w3), (RAIL_X + 40, y_w3)], fill=LINE_COLOR, width=2)

draw_contact(RAIL_X + 40, y_w3, "START", "I0.0")

# Parallel M1P
draw.line([(RAIL_X + 40, y_w3), (RAIL_X + 40, y_w3 + 46)], fill=LINE_COLOR, width=2)
draw.line([(RAIL_X + 40, y_w3 + 46), (RAIL_X + 55, y_w3 + 46)], fill=LINE_COLOR, width=2)
draw_contact(RAIL_X + 55, y_w3 + 46, "M1P", "Q0.0")
draw.line([(RAIL_X + 109, y_w3 + 46), (RAIL_X + 130, y_w3 + 46)], fill=LINE_COLOR, width=2)
draw.line([(RAIL_X + 130, y_w3 + 46), (RAIL_X + 130, y_w3)], fill=LINE_COLOR, width=2)

x_join = RAIL_X + 130
draw.line([(RAIL_X + 94, y_w3), (x_join, y_w3)], fill=LINE_COLOR, width=2)

draw.line([(x_join, y_w3), (x_join + 40, y_w3)], fill=LINE_COLOR, width=2)
x_stp = draw_contact(x_join + 40, y_w3, "STP", "I0.1", is_nc=True)

draw.line([(x_stp, y_w3), (x_stp + 45, y_w3)], fill=LINE_COLOR, width=2)
x_emg = draw_contact(x_stp + 45, y_w3, "P_EMERG", "I0.2", is_nc=True)

draw.line([(x_emg, y_w3), (RIGHT_RAIL_X - 140, y_w3)], fill=LINE_COLOR, width=2)
x_coil = draw_coil(RIGHT_RAIL_X - 140, y_w3, "M1P (Línea)", "Q0.0")
draw.line([(x_coil, y_w3), (RIGHT_RAIL_X, y_w3)], fill=LINE_COLOR, width=2)

cur_y = y_w3 + 78

# -------------------------------------------------------------
# NETWORK 4: Temporizador Estrella -> Triángulo (T37)
# -------------------------------------------------------------
cur_y = draw_network_header(cur_y, 4, "Temporizador Estrella -> Triángulo (T37 con VW106)", 
                            "Inicia cuando entra M1P. El preset PT toma en vivo el cociente VW106 (0 a 8.5s)")

y_w4 = cur_y + 40
draw.line([(RAIL_X, y_w4), (RAIL_X + 40, y_w4)], fill=LINE_COLOR, width=2)
x_m1p = draw_contact(RAIL_X + 40, y_w4, "M1P", "Q0.0")

draw.line([(x_m1p, y_w4), (x_m1p + 80, y_w4)], fill=LINE_COLOR, width=2)
b_ton = draw_microwin_box(x_m1p + 80, y_w4 - 28, "TON", [("IN", ""), ("PT", "VW106")], [], w=95, h=65)
draw.text((x_m1p + 90, y_w4 - 44), "T37 (100 ms)", fill=LABEL_COLOR, font=f_sym)
draw.text((b_ton[0] + b_ton[2] + 25, y_w4 - 6), "<-- Preset regulable con Potenciómetro 0 (SMB28)", fill=ACCENT_GREEN, font=f_sym)

cur_y = y_w4 + 62

# -------------------------------------------------------------
# NETWORK 5: Contactor Estrella (M1E) con Enclavamiento Cruzado
# -------------------------------------------------------------
cur_y = draw_network_header(cur_y, 5, "Contactor Estrella (M1E / Q0.1) con Enclavamiento Eléctrico", 
                            "Activo de inmediato al arrancar M1P. Se apaga al vencer T37 o si entra Triángulo M1D")

y_w5 = cur_y + 40
draw.line([(RAIL_X, y_w5), (RAIL_X + 40, y_w5)], fill=LINE_COLOR, width=2)
x5_1 = draw_contact(RAIL_X + 40, y_w5, "M1P", "Q0.0")

draw.line([(x5_1, y_w5), (x5_1 + 45, y_w5)], fill=LINE_COLOR, width=2)
x5_2 = draw_contact(x5_1 + 45, y_w5, "T_ESTRELLA", "T37", is_nc=True)

draw.line([(x5_2, y_w5), (x5_2 + 45, y_w5)], fill=LINE_COLOR, width=2)
x5_3 = draw_contact(x5_2 + 45, y_w5, "M1D (Bloq)", "Q0.2", is_nc=True)

draw.line([(x5_3, y_w5), (RIGHT_RAIL_X - 140, y_w5)], fill=LINE_COLOR, width=2)
x5_c = draw_coil(RIGHT_RAIL_X - 140, y_w5, "M1E (Estrella)", "Q0.1")
draw.line([(x5_c, y_w5), (RIGHT_RAIL_X, y_w5)], fill=LINE_COLOR, width=2)

cur_y = y_w5 + 62

# -------------------------------------------------------------
# NETWORK 6: Contactor Triángulo (M1D) con Enclavamiento Cruzado
# -------------------------------------------------------------
cur_y = draw_network_header(cur_y, 6, "Contactor Triángulo (M1D / Q0.2) con Enclavamiento Eléctrico", 
                            "Conmuta al vencer T37 sólo si Estrella M1E está apagado (evita cortocircuito trifásico)")

y_w6 = cur_y + 40
draw.line([(RAIL_X, y_w6), (RAIL_X + 40, y_w6)], fill=LINE_COLOR, width=2)
x6_1 = draw_contact(RAIL_X + 40, y_w6, "M1P", "Q0.0")

draw.line([(x6_1, y_w6), (x6_1 + 45, y_w6)], fill=LINE_COLOR, width=2)
x6_2 = draw_contact(x6_1 + 45, y_w6, "T_ESTRELLA", "T37", is_nc=False)

draw.line([(x6_2, y_w6), (x6_2 + 45, y_w6)], fill=LINE_COLOR, width=2)
x6_3 = draw_contact(x6_2 + 45, y_w6, "M1E (Bloq)", "Q0.1", is_nc=True)

draw.line([(x6_3, y_w6), (RIGHT_RAIL_X - 140, y_w6)], fill=LINE_COLOR, width=2)
x6_c = draw_coil(RIGHT_RAIL_X - 140, y_w6, "M1D (Triángulo)", "Q0.2")
draw.line([(x6_c, y_w6), (RIGHT_RAIL_X, y_w6)], fill=LINE_COLOR, width=2)

cur_y = y_w6 + 62

# -------------------------------------------------------------
# NETWORK 7: Segundo Temporizador Independiente (T38 con Potenciómetro 1)
# -------------------------------------------------------------
cur_y = draw_network_header(cur_y, 7, "Segundo Temporizador Independiente (T38 con VW112)", 
                            "Usa VW112 como preset PT (0 a 8.5s) para retardo de proceso, lubricación o ventilador")

y_w7 = cur_y + 40
draw.line([(RAIL_X, y_w7), (RAIL_X + 40, y_w7)], fill=LINE_COLOR, width=2)
x7_c = draw_contact(RAIL_X + 40, y_w7, "HABILITA_2", "I0.3")

draw.line([(x7_c, y_w7), (x7_c + 80, y_w7)], fill=LINE_COLOR, width=2)
b_ton2 = draw_microwin_box(x7_c + 80, y_w7 - 28, "TON", [("IN", ""), ("PT", "VW112")], [], w=95, h=65)
draw.text((x7_c + 90, y_w7 - 44), "T38 (100 ms)", fill=LABEL_COLOR, font=f_sym)
draw.text((b_ton2[0] + b_ton2[2] + 25, y_w7 - 6), "<-- Preset regulable con Potenciómetro 1 (SMB29)", fill=ACCENT_GREEN, font=f_sym)

# Save
out_path_project = "/home/gus05/rs485_ft232rl/ladder_estrella_triangulo_cpu214.png"
img.save(out_path_project)
print(f"Generated: {out_path_project}")

brain_dir = "/home/gus05/.gemini/antigravity-cli/brain/f8f46243-e43b-4080-8dac-ef70a30577ee"
out_path_brain = os.path.join(brain_dir, "ladder_estrella_triangulo_cpu214.png")
shutil.copy(out_path_project, out_path_brain)
print(f"Copied to brain: {out_path_brain}")
