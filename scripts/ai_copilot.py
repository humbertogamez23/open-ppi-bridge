#!/usr/bin/env python3
"""
ai_copilot.py - Copiloto de IA Local y Offline para Lógica Siemens S7-200
=============================================================================
Asistente de ingeniería industrial basado en modelos LLM locales (Qwen 2.5 Coder
vía Ollama) para análisis, auditoría de seguridad, diálogo técnico y generación de código AWL/STL.

Funciona de forma 100% privada, desconectada (air-gapped) y ligera (~1.3 GB RAM).

Capacidades:
  1. Feedback y Diálogo Consultivo: Explica razonamientos, hace preguntas técnicas
     y conoce qué parámetros mover antes de ejecutar o generar código.
  2. Catálogo Completo de Scripts: Domina los argumentos (flags --) de todas las
     herramientas de open-ppi-bridge (BLE, serial, flasheo, escaneo y monitoreo).
  3. Memoria de Conversación: Mantiene el contexto entre turnos en el modo interactivo.
  4. Auditoría de Seguridad (--audit): Detecta condiciones de carrera, interlocks
     faltantes y salidas conflictivas simultáneas.
  5. Explicación Técnica (--explain): Traduce redes AWL complejas a lenguaje natural.
  6. Generación de Lógica (--generate): Escribe código AWL nativo a partir de
     descripciones en lenguaje natural, listo para ensamblar con s7_awl_asm.py.
  7. Modo Interactivo (--chat / ia-coder): Terminal interactiva con memoria y ejecución.

Autores: Humberto Gámez (@humbertogamez23) & Antigravity AI (open-ppi-bridge project)
Licencia: GPL-3.0
"""

import sys
import os
import json
import re
import argparse
import urllib.request
import urllib.error
from typing import Optional, Dict, Any, List, Tuple

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:3b"

SYSTEM_PROMPT = """Eres el Copiloto de IA de open-ppi-bridge para PLCs Siemens SIMATIC S7-200.
Tu prioridad es la PRECISIÓN TÉCNICA y la VELOCIDAD:
- Responde en 1 o 2 oraciones breves y directas. Cero rodeos, formalismos o explicaciones largas.
- Si hay una acción a realizar en el sistema, escribe SIEMPRE al final en una línea única:
  COMANDO: <comando exacto>

CATÁLOGO EXACTO DE SCRIPTS Y SINTAXIS (PROHIBIDO INVENTAR FLAGS):

1. EXTRACCIÓN (PLC -> PC):
   • Con etiqueta: COMANDO: python3 scripts/upload_s7_200.py --ble --plc 2 --tag <nombre> --awl
   • Con nombre fijo: COMANDO: python3 scripts/upload_s7_200.py --ble --plc 2 --block OB1 -o blocks/<archivo.bin>
   • Flags válidos: --ble, --port <disp>, --plc <num>, --tag <nom>, --block {OB1,DB1,SDB}, -o <ruta>, --awl, --ai
   • ⚠️ REGLA CRÍTICA: upload_s7_200.py NUNCA lleva el flag --program. No agregues argumentos posicionales sueltos al final sin '-o'.

2. FLASHEO / CARGA (PC -> PLC):
   • COMANDO: python3 scripts/flash_s7_200.py --ble --program
   • Flags válidos: --ble, --port <disp>, --plc <num>, --program, --system, --data, --all, --stop, --run, --blocks-dir <dir>
   • ⚠️ REGLA CRÍTICA: flash_s7_200.py NUNCA lleva --tag ni nombres de archivo posicionales sueltos al final.

3. MONITOREO Y CONTROL REMOTO (BLE):
   • Estado: COMANDO: python3 scripts/ble_plc_control.py status --plc 2
   • Monitoreo de E/S en vivo: COMANDO: python3 scripts/ble_plc_control.py io -w --plc 2
   • Detener CPU: COMANDO: python3 scripts/ble_plc_control.py stop --plc 2
   • Arrancar CPU: COMANDO: python3 scripts/ble_plc_control.py run --plc 2
   • Leer variable: COMANDO: python3 scripts/ble_plc_control.py read SMB28 --plc 2

4. ESCANEO DE ESTACIONES PPI:
   • Por BLE: COMANDO: python3 scripts/ble_scan_ppi.py --max-addr 15
   • Por Serie: COMANDO: python3 scripts/scan_ppi.py

5. SIMULACIÓN Y DESENSAMBLADO:
   • Simular lógica AWL: COMANDO: python3 scripts/simulador_awl.py --interactive blocks/latest.awl
   • Desensamblar binario a AWL: COMANDO: python3 scripts/s7_awl_asm.py --disasm blocks/latest.bin
   • Ensamblar AWL a binario: COMANDO: python3 scripts/s7_awl_asm.py --asm blocks/latest.awl

6. GESTIÓN DE ARCHIVOS:
   • Listar: COMANDO: ls -lh blocks/
   • Limpiar: COMANDO: rm -f blocks/*.bin blocks/*.awl

7. LISTA DE SCRIPTS DISPONIBLES:
   Si el usuario pide ver o listar los scripts o herramientas del repo, lístalos concisamente:
   - upload_s7_200.py: Extractor de bloques de CPU a PC (OB1, DB1, SDB).
   - flash_s7_200.py: Cargador/Flasher de bloques a la EEPROM de la CPU.
   - ble_plc_control.py: Monitoreo en tiempo real (io -w) y control RUN/STOP vía BLE.
   - ble_scan_ppi.py: Escaneo de direcciones PPI por BLE.
   - simulador_awl.py: Simulador interactivo de lógica AWL en PC.
   - s7_awl_asm.py: Ensamblador y desensamblador AWL <-> binario.
   - read_io_ppi.py / plc_control.py / scan_ppi.py: Herramientas por puerto serie cableado.
   - ppi_proxy.py: Proxy MITM para Micro/WIN en máquinas virtuales.
   - ble_serial_bridge.py: Puente virtual BLE a /tmp/ttyPPI.
   - generate_ladder_diagram.py: Generador de diagramas LADDER desde AWL.
   - sniffer_live.py: Sniffer pasivo de tramas FDL/PPI.
   - verify_ble_write.py: Verificación y tests de latencia BLE.
   - ai_copilot.py: Copiloto de IA local para terminal (ia-coder).
"""


def check_ollama_status(url: str = DEFAULT_OLLAMA_URL) -> bool:
    """Verifica si el servidor local de Ollama está activo y respondiendo."""
    try:
        req = urllib.request.Request(f"{url}/api/tags", headers={"User-Agent": "open-ppi-copilot"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            return resp.status == 200
    except Exception:
        return False


def get_latest_extraction_info() -> Tuple[Optional[dict], str]:
    """Lee los metadatos y código del último bloque extraído en vivo."""
    b_dir = os.path.join(os.path.dirname(__file__), "..", "blocks")
    meta_path = os.path.join(b_dir, "latest_extraction.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            awl_path = os.path.join(b_dir, meta.get("awl_file", "latest.awl"))
            code = ""
            if os.path.exists(awl_path):
                with open(awl_path, "r", encoding="utf-8") as f:
                    code = f.read()
            return meta, code
        except Exception:
            pass
    return None, ""


def build_context_system_prompt(base_system: str, prompt_hint: str = "") -> str:
    """Enriquece el system prompt con contexto mínimo y veloz para no sobrecargar el modelo local."""
    meta, code = get_latest_extraction_info()
    extra_ctx = ""

    # Detectar si el usuario mencionó un archivo .awl específico en su mensaje
    match_awl = re.search(r'([\w\-\./]+\.awl)', prompt_hint)
    if match_awl:
        specified_path = match_awl.group(1)
        b_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "blocks"))
        cand1 = os.path.join(b_dir, os.path.basename(specified_path))
        cand2 = os.path.abspath(specified_path)
        target = cand1 if os.path.exists(cand1) else (cand2 if os.path.exists(cand2) else None)

        if target and os.path.exists(target):
            try:
                with open(target, "r", encoding="utf-8") as f:
                    file_code = f.read()
                snippet = "\n".join(file_code.splitlines()[:50])
                extra_ctx = f"""
INFORMACIÓN DEL ARCHIVO AWL ESPECIFICADO:
- Archivo AWL: {os.path.basename(target)}
- Enlace local: file://{target}
- Código fuente:
```awl
{snippet}
```
"""
            except Exception:
                pass

    needs_code_analysis = bool(re.search(r'(audit|explic|analiz|revis|lógic|logica|código|codigo|red\s*\d|network)', prompt_hint, re.IGNORECASE))
    if not extra_ctx and meta:
        if needs_code_analysis and code:
            snippet = "\n".join(code.splitlines()[:50])
            extra_ctx = f"""
ÚLTIMO PROGRAMA EXTRAÍDO EN MÁQUINA:
- Archivo: blocks/{meta.get('awl_file')} (Estación {meta.get('plc_addr')})
```awl
{snippet}
```
"""
        else:
            # Contexto ultra-ligero de 1 sola línea (cero impacto en tokens y velocidad)
            extra_ctx = f"\n[Contexto máquina actual: Último bloque extraído en blocks/{meta.get('bin_file', 'latest.bin')} (PLC #{meta.get('plc_addr', 2)})]"

    return (base_system + "\n" + extra_ctx) if extra_ctx else base_system


def chat_with_ollama(
    messages: List[Dict[str, str]],
    model: str = DEFAULT_MODEL,
    url: str = DEFAULT_OLLAMA_URL,
    temperature: float = 0.2,
    num_predict: int = 300
) -> Optional[str]:
    """Envía un historial de mensajes a la API /api/chat de Ollama con parámetros optimizados de velocidad."""
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            "repeat_penalty": 1.15,
            "num_ctx": 2048,
            "num_predict": num_predict,
        }
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{url}/api/chat",
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "open-ppi-copilot"}
    )

    try:
        with urllib.request.urlopen(req, timeout=180.0) as resp:
            if resp.status == 200:
                result = json.loads(resp.read().decode("utf-8"))
                return result.get("message", {}).get("content", "").strip()
    except urllib.error.URLError as e:
        print(f"[-] Error de conexión con Ollama ({e}). Asegúrese de que el servicio esté activo (`ollama serve`).")
    except Exception as e:
        print(f"[-] Error inesperado procesando la consulta: {e}")
    return None


def query_ollama(
    prompt: str,
    system: str = SYSTEM_PROMPT,
    model: str = DEFAULT_MODEL,
    url: str = DEFAULT_OLLAMA_URL,
    temperature: float = 0.2
) -> Optional[str]:
    """Envía una consulta única empaquetándola en formato chat."""
    eff_system = build_context_system_prompt(system, prompt_hint=prompt)
    messages = [
        {"role": "system", "content": eff_system},
        {"role": "user", "content": prompt}
    ]
    return chat_with_ollama(messages, model=model, url=url, temperature=temperature)


def audit_awl_code(awl_text: str, model: str = DEFAULT_MODEL) -> str:
    """Audita un código AWL en busca de riesgos de seguridad, interlocks y buenas prácticas."""
    prompt = f"""Realiza una AUDITORÍA TÉCNICA DE SEGURIDAD INDUSTRIAL para el siguiente código AWL de Siemens S7-200.

IMPORTANTE: Basa tu análisis ÚNICA Y EXCLUSIVAMENTE en el código que se muestra abajo. NO asumas ni inventes funciones, nombres de máquinas o dispositivos que no estén en este texto.

```awl
{awl_text}
```

Estructura tu reporte con:
1. 🔍 Resumen General de la Lógica (Propósito del bloque OB1 y subrutinas según las redes reales).
2. ⏱️ Análisis de Temporizadores y Etapas (Tiempos de ciclo y temporizadores activos).
3. ⚠️ Puntos Críticos y Verificación de Seguridad (Interbloqueos entre salidas físicas, condiciones de parada y fallas).
4. 💡 Recomendaciones de Mantenimiento y Operación.
"""
    resp = query_ollama(prompt, model=model, temperature=0.1)
    return resp or "[-] No se pudo obtener la auditoría del modelo local."


def explain_awl_code(awl_text: str, model: str = DEFAULT_MODEL) -> str:
    """Explica detalladamente qué hace cada red del código AWL."""
    prompt = f"""Explica en detalle y de forma comprensible para un técnico de mantenimiento qué hace el siguiente código AWL de Siemens S7-200.
Explica red por red (Network) la función de las entradas, marcas, temporizadores y salidas reales del código:

```awl
{awl_text}
```
"""
    resp = query_ollama(prompt, model=model, temperature=0.2)
    return resp or "[-] No se pudo obtener la explicación del modelo local."


def generate_awl_code(requirements: str, model: str = DEFAULT_MODEL) -> str:
    """Genera código AWL Siemens nativo a partir de un requerimiento en lenguaje natural."""
    prompt = f"""Genera el código de programa en lenguaje AWL/STL Siemens S7-200 para cumplir con los siguientes requerimientos:

REQUERIMIENTOS:
{requirements}

REGLAS DE FORMATO:
- Utiliza la estructura estándar de Siemens:
  ORGANIZATION_BLOCK Bloque_de_programa:OB1
  TITLE=...
  BEGIN
  Network 1 // Comentario explicativo
  ...
  END_ORGANIZATION_BLOCK
- Si se requieren subrutinas, créalas con SUBROUTINE_BLOCK SBR_x:SBRx ... END_SUBROUTINE_BLOCK.
- Entrega únicamente el código AWL válido y listo para compilar con explicaciones breves.
"""
    resp = query_ollama(prompt, model=model, temperature=0.2)
    return resp or "[-] No se pudo generar el código AWL solicitado."


def show_available_scripts():
    """Muestra el catálogo completo de scripts y utilidades de open-ppi-bridge de forma instantánea."""
    print("""
================================================================================
🛠️  CATÁLOGO DE SCRIPTS Y HERRAMIENTAS - OPEN-PPI-BRIDGE
================================================================================
📥 1. EXTRACCIÓN (PLC -> PC)
   • scripts/upload_s7_200.py
     Extrae bloques (OB1, DB1, SDB) del PLC a la PC con auto-etiquetado y fecha.
     Flags: --ble, --port <disp>, --plc <num>, --tag <nom>, -o <ruta>, --awl, --ai
     Ejemplos:
       python3 scripts/upload_s7_200.py --ble --tag mi_maquina --awl
       python3 scripts/upload_s7_200.py --ble --block OB1 -o blocks/mi_prog.bin

⚡ 2. CARGA Y FLASHEO (PC -> PLC)
   • scripts/flash_s7_200.py
     Graba bloques en la memoria no volátil EEPROM del autómata.
     Flags: --ble, --port <disp>, --plc <num>, --program, --data, --system, --all, --stop, --run
     Ejemplos:
       python3 scripts/flash_s7_200.py --ble --program
       python3 scripts/flash_s7_200.py --ble --all --stop --run

📡 3. MONITOREO Y CONTROL INALÁMBRICO BLE
   • scripts/ble_plc_control.py
     Control de marcha/paro y monitoreo en vivo de hasta 40I / 38O.
     Comandos: status, run, stop, io [-w], read <var>, info
     Ejemplos:
       python3 scripts/ble_plc_control.py status --plc 2
       python3 scripts/ble_plc_control.py io -w --plc 2
       python3 scripts/ble_plc_control.py read SMB28 --plc 2

🔍 4. ESCANEO DE ESTACIONES PPI
   • scripts/ble_scan_ppi.py   -> Escáner de estaciones sobre Bluetooth LE
     Ejemplo: python3 scripts/ble_scan_ppi.py --max-addr 15
   • scripts/scan_ppi.py       -> Escáner sobre puerto serie cableado

🧪 5. SIMULACIÓN Y ENSAMBLADO AWL
   • scripts/simulador_awl.py  -> Simulador/intérprete interactivo de lógica AWL en PC
     Ejemplo: python3 scripts/simulador_awl.py --interactive blocks/latest.awl
   • scripts/s7_awl_asm.py     -> Ensambla AWL a .bin o desensambla .bin a AWL
     Ejemplos:
       python3 scripts/s7_awl_asm.py --disasm blocks/latest.bin
       python3 scripts/s7_awl_asm.py --asm blocks/latest.awl

🔌 6. COMUNICACIÓN SERIE CABLEADA Y SERVICIOS VM
   • scripts/read_io_ppi.py       -> Lectura de entradas/salidas vía RS-485 cableado
   • scripts/plc_control.py       -> Control RUN/STOP vía RS-485 cableado
   • scripts/ppi_proxy.py         -> Proxy MITM para STEP 7-Micro/WIN en QEMU/KVM
   • scripts/ble_serial_bridge.py -> Puente BLE a puerto virtual /tmp/ttyPPI
   • scripts/sniffer_live.py      -> Sniffer pasivo de tramas PROFIBUS FDL/PPI
   • scripts/verify_ble_write.py  -> Test de latencia y verificación de tramas BLE

🤖 7. ASISTENTE DE IA
   • scripts/ai_copilot.py (ia-coder) -> Asistente interactivo (--chat), auditoría (--audit),
     explicación (--explain) y generación de código (--generate).

💻 8. VIRTUALIZACIÓN STEP 7-Micro/WIN (QEMU / KVM)
   • vm/setup_win7_vm.sh -> Asistente automatizado para crear e instalar VM Windows 7.
   • vm/run_win7_vm.sh [--ble] -> Lanzador de producción con filtro anti-960B y COM1 virtual.
   • scripts/web_transfer.py -> Servidor HTTP de intercambio de archivos (.mwp/.awl) en http://10.0.2.2:8000.
================================================================================
""")


def sanitize_and_validate_command(cmd: str) -> Tuple[str, Optional[str]]:
    """
    Inspecciona y auto-corrige comandos propuestos para garantizar que no contengan
    flags incompatibles, inexistentes o argumentos posicionales mal colocados.
    """
    if not cmd:
        return cmd, None

    warnings = []
    parts = cmd.strip().split()
    if not parts:
        return cmd, None

    if any("upload_s7_200.py" in p for p in parts):
        cleaned_parts = []
        i = 0
        while i < len(parts):
            p = parts[i]
            if p == "--program":
                warnings.append("removido '--program' (este flag no existe en upload_s7_200.py)")
                i += 1
                continue
            elif p in ("--all", "--system", "--data", "--stop", "--run"):
                warnings.append(f"removido '{p}' (es exclusivo de flash_s7_200.py)")
                i += 1
                continue
            elif (p.endswith(".bin") or p.endswith(".awl")) and (i == 0 or parts[i-1] not in ("-o", "--output", "--awl", "--block")):
                cleaned_parts.extend(["-o", p])
                warnings.append(f"archivo posicional convertido a parámetro '-o {p}'")
                i += 1
                continue
            cleaned_parts.append(p)
            i += 1
        cmd = " ".join(cleaned_parts)

    elif any("flash_s7_200.py" in p for p in parts):
        cleaned_parts = []
        i = 0
        while i < len(parts):
            p = parts[i]
            if p in ("--tag", "--block", "--ai"):
                warnings.append(f"removido '{p}' (es exclusivo de upload_s7_200.py)")
                if p in ("--tag", "--block") and i + 1 < len(parts) and not parts[i+1].startswith("-"):
                    i += 2
                    continue
                i += 1
                continue
            elif (p.endswith(".bin") or p.endswith(".awl")) and (i == 0 or parts[i-1] not in ("--blocks-dir", "-d")):
                warnings.append(f"removido argumento posicional '{p}' (flash_s7_200 carga por flags)")
                i += 1
                continue
            cleaned_parts.append(p)
            i += 1
        cmd = " ".join(cleaned_parts)

    warn_str = "; ".join(warnings) if warnings else None
    return cmd, warn_str


def extract_proposed_command(text: str) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Extrae la propuesta de comando de la respuesta de la IA de forma robusta.
    Retorna (texto_limpio, comando_a_ejecutar, advertencia_autocorreccion).
    """
    cmd_to_run = None

    # 1. Buscar patrón COMANDO: (con o sin negrita/markdown/comillas)
    match = re.search(r'(?:\*\*|__)?(?:COMANDO|COMMAND):\s*(?:\*\*)?\s*[`"]?([^\n`"]+)[`"]?', text, re.IGNORECASE)
    if match:
        cand = match.group(1).strip()
        # Verificar que no sea un enlace a archivo tipo file:/// ni url
        if not cand.startswith("file://") and not cand.startswith("http://") and not cand.startswith("https://"):
            cmd_to_run = cand

    # 2. Si no hay COMANDO explícito, buscar bloques de código markdown con python3 scripts/
    if not cmd_to_run:
        match_block = re.search(r'```(?:bash|sh)?\s*\n\s*(python3\s+scripts/[\w\-\.]+\.py[^\n`]+)', text)
        if match_block:
            cmd_to_run = match_block.group(1).strip()

    # 3. Si no lo halló, buscar cualquier línea que empiece directamente con python3 scripts/
    if not cmd_to_run:
        match_line = re.search(r'^\s*(python3\s+scripts/[\w\-\.]+\.py[^\n]+)', text, re.MULTILINE)
        if match_line:
            cand = match_line.group(1).strip()
            if not cand.startswith("file://"):
                cmd_to_run = cand

    auto_warning = None
    if cmd_to_run:
        cmd_to_run = re.sub(r'^(?:COMANDO|COMMAND):\s*', '', cmd_to_run, flags=re.IGNORECASE).strip()
        cmd_to_run, auto_warning = sanitize_and_validate_command(cmd_to_run)

    # Limpiar líneas de COMANDO del mensaje a mostrar
    display_lines = []
    for line in text.splitlines():
        if re.search(r'^\s*(?:\*\*|__)?(?:COMANDO|COMMAND):\s*', line, re.IGNORECASE):
            continue
        display_lines.append(line)

    cleaned_text = "\n".join(display_lines).strip()
    return cleaned_text, cmd_to_run, auto_warning


def interactive_chat(model: str = DEFAULT_MODEL):
    """Bucle de chat interactivo por consola con memoria conversacional y copiloto industrial."""
    meta, _ = get_latest_extraction_info()
    b_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "blocks"))

    QUICK_SHORTCUTS = {
        "status": "python3 scripts/ble_plc_control.py status --plc 2",
        "estado": "python3 scripts/ble_plc_control.py status --plc 2",
        "io": "python3 scripts/ble_plc_control.py io -w --plc 2",
        "monitor": "python3 scripts/ble_plc_control.py io -w --plc 2",
        "scan": "python3 scripts/ble_scan_ppi.py --max-addr 15",
        "escanear": "python3 scripts/ble_scan_ppi.py --max-addr 15",
        "stop": "python3 scripts/ble_plc_control.py stop --plc 2",
        "parar": "python3 scripts/ble_plc_control.py stop --plc 2",
        "run": "python3 scripts/ble_plc_control.py run --plc 2",
        "arrancar": "python3 scripts/ble_plc_control.py run --plc 2",
        "extraer": "python3 scripts/upload_s7_200.py --ble --plc 2 --tag taller --awl",
        "upload": "python3 scripts/upload_s7_200.py --ble --plc 2 --tag taller --awl",
        "bloques": "ls -lh blocks/",
        "programas": "ls -lh blocks/",
        "listar": "ls -lh blocks/",
        "limpiar-bloques": "rm -i blocks/*.bin blocks/*.awl",
        "simular": "python3 scripts/simulador_awl.py --interactive blocks/latest.awl",
    }

    print("=" * 72)
    print("🤖 OPEN-PPI-BRIDGE | COPILOTO DE IA INDUSTRIAL (ia-coder)")
    print(f"   Modelo : {model} (100% Offline / Privado)")
    if meta:
        bin_p = meta.get("bin_url") or f"file://{os.path.join(b_dir, meta.get('bin_file', 'latest.bin'))}"
        awl_p = meta.get("awl_url") or f"file://{os.path.join(b_dir, meta.get('awl_file', 'latest.awl'))}"
        print(f"   📂 Último binario : {bin_p} ({meta.get('size_bytes')}B, Estación {meta.get('plc_addr')})")
        print(f"   📝 Código AWL     : {awl_p} [{meta.get('timestamp')}]")
        print(f"   💡 (Ctrl+Click en el enlace para abrir directamente el archivo en tu editor)")
    print("   Comandos de chat: 'scripts' (ver catálogo completo), 'reset' (reiniciar), 'salir'")
    print("   Atajos directos : 'status', 'scan', 'io', 'extraer', 'bloques', 'limpiar-bloques'")
    print("   Shell directo   : !<comando> o escribe directamente 'python3 scripts/...'")
    print("=" * 72)

    eff_system = build_context_system_prompt(SYSTEM_PROMPT)
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": eff_system}
    ]

    while True:
        try:
            user_input = input("\n👨‍💻 Tú: ").strip()
            if not user_input:
                continue

            lowered = user_input.lower()
            if lowered in ("salir", "exit", "quit"):
                print("[*] Saliendo del Copiloto de IA.")
                break

            if lowered in ("limpiar", "clear"):
                os.system("clear" if os.name == "posix" else "cls")
                continue

            if lowered in ("scripts", "herramientas", "tools", "ayuda", "help", "lista"):
                show_available_scripts()
                continue

            if lowered in ("reset", "reiniciar", "resetear"):
                eff_system = build_context_system_prompt(SYSTEM_PROMPT)
                messages = [{"role": "system", "content": eff_system}]
                print("\n[✓] Memoria e historial de conversación reiniciados con éxito.")
                continue

            # 1. Ejecución directa sin pasar por Ollama (ahorra tiempo y evita abrir otra terminal)
            direct_cmd = None
            if user_input.startswith("!"):
                direct_cmd = user_input[1:].strip()
            elif lowered in QUICK_SHORTCUTS:
                direct_cmd = QUICK_SHORTCUTS[lowered]
            elif user_input.startswith("python3 ") or user_input.startswith("./scripts/"):
                direct_cmd = user_input.strip()

            if direct_cmd:
                direct_cmd, direct_warn = sanitize_and_validate_command(direct_cmd)
                if direct_warn:
                    print(f"\n\033[93m[🛡️ Auto-corrección de comando]: {direct_warn}\033[0m")
                print(f"\n⚡ Ejecutando directamente en open-ppi-bridge:\n   \033[1;36m{direct_cmd}\033[0m\n" + "-" * 60)
                os.system(direct_cmd)
                print("-" * 60 + "\n[✓] Completado.")
                continue

            # 2. Agregar mensaje del usuario al historial para consultar al LLM
            messages.append({"role": "user", "content": user_input})

            # Limitar la memoria para evitar sobrecarga en CPU (mantiene system + últimos 8 turnos)
            if len(messages) > 9:
                messages = [messages[0]] + messages[-8:]

            print("\n🤖 Copiloto (pensando)...")
            answer = chat_with_ollama(messages, model=model, temperature=0.1, num_predict=250)

            if answer:
                # Guardar en memoria la respuesta del asistente
                messages.append({"role": "assistant", "content": answer})

                cleaned_msg, cmd_to_run, auto_warn = extract_proposed_command(answer)
                if cleaned_msg:
                    print(f"\n{cleaned_msg}")

                if auto_warn:
                    print(f"\n\033[93m[🛡️ Auto-corrección aplicada]: {auto_warn}\033[0m")

                if cmd_to_run:
                    print(f"\n⚡ Propuesta de acción en tu sistema:")
                    print(f"   \033[1;36m{cmd_to_run}\033[0m")
                    try:
                        confirm = input("\n¿Deseas ejecutar este comando ahora? [S/n]: ").strip().lower()
                    except (KeyboardInterrupt, EOFError):
                        print("\n[*] Acción cancelada.")
                        continue
                    if confirm in ("", "s", "si", "y", "yes"):
                        print(f"\n[*] Ejecutando: {cmd_to_run}\n" + "-" * 60)
                        os.system(cmd_to_run)
                        print("-" * 60 + "\n[✓] Comando completado.")
                    else:
                        print("[*] Comando no ejecutado por elección del usuario.")
            else:
                print("[-] No se recibió respuesta del modelo local.")

        except (KeyboardInterrupt, EOFError):
            print("\n[*] Sesión finalizada.")
            break


def main():
    parser = argparse.ArgumentParser(
        description="Copiloto de IA Local y Offline para Lógica Siemens S7-200 (open-ppi-bridge)"
    )
    parser.add_argument("--scripts", "--tools", action="store_true", help="Listar todos los scripts disponibles en open-ppi-bridge")
    parser.add_argument("--audit", metavar="ARCHIVO.awl", help="Auditar seguridad e interlocks de un archivo AWL")
    parser.add_argument("--explain", metavar="ARCHIVO.awl", help="Explicar detalladamente el funcionamiento de un archivo AWL")
    parser.add_argument("--generate", metavar="REQUERIMIENTO", help="Generar código AWL a partir de descripción en lenguaje natural")
    parser.add_argument("--chat", action="store_true", help="Iniciar sesión interactiva en consola con el copiloto")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Modelo de Ollama a utilizar (default: {DEFAULT_MODEL})")
    parser.add_argument("-o", "--output", help="Guardar el resultado en un archivo de texto o .awl")

    args = parser.parse_args()

    # Si se pide únicamente listar scripts
    if args.scripts:
        show_available_scripts()
        return

    # 1. Verificar si Ollama está en ejecución
    if not check_ollama_status():
        print("[-] El servidor de Ollama no está respondiendo en http://127.0.0.1:11434.")
        print("    Inicie el servicio ejecutando: sudo systemctl start ollama (o 'ollama serve').")
        sys.exit(1)

    result_text = None

    # 2. Modo Auditoría
    if args.audit:
        if not os.path.exists(args.audit):
            print(f"[-] Archivo no encontrado: {args.audit}")
            sys.exit(1)
        with open(args.audit, "r", encoding="utf-8", errors="replace") as f:
            code = f.read()
        print(f"\n[*] Auditando seguridad de: {args.audit} con {args.model}...")
        result_text = audit_awl_code(code, model=args.model)
        print("\n" + "=" * 70)
        print("🛡️ REPORTE DE AUDITORÍA DE SEGURIDAD INDUSTRIAL:")
        print("=" * 70)
        print(result_text)
        print("=" * 70)

    # 3. Modo Explicación
    elif args.explain:
        if not os.path.exists(args.explain):
            print(f"[-] Archivo no encontrado: {args.explain}")
            sys.exit(1)
        with open(args.explain, "r", encoding="utf-8", errors="replace") as f:
            code = f.read()
        print(f"\n[*] Analizando y explicando: {args.explain} con {args.model}...")
        result_text = explain_awl_code(code, model=args.model)
        print("\n" + "=" * 70)
        print("📖 EXPLICACIÓN TÉCNICA DEL PROGRAMA:")
        print("=" * 70)
        print(result_text)
        print("=" * 70)

    # 4. Modo Generación
    elif args.generate:
        print(f"\n[*] Generando lógica AWL para: '{args.generate}'...")
        result_text = generate_awl_code(args.generate, model=args.model)
        print("\n" + "=" * 70)
        print("⚡ CÓDIGO AWL GENERADO:")
        print("=" * 70)
        print(result_text)
        print("=" * 70)

    # 5. Modo Chat
    elif args.chat:
        interactive_chat(model=args.model)
        return

    else:
        parser.print_help()
        return

    # Guardar en archivo si se especificó -o
    if args.output and result_text:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(result_text)
        print(f"\n[✓] Resultado guardado con éxito en: {args.output}")


if __name__ == "__main__":
    main()
