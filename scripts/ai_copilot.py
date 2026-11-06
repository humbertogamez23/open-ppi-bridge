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
DEFAULT_MODEL = "qwen2.5-coder:1.5b"

SYSTEM_PROMPT = """Eres el Copiloto de Inteligencia Artificial Industrial de open-ppi-bridge, especializado en programación, diagnóstico y auditoría de autómatas Siemens SIMATIC S7-200 (CPU 21x y 22x) en lenguaje AWL/STL (Lista de Instrucciones).
Tu personalidad es la de un ingeniero colega de automatización: conversacional, técnico, atento, consultivo y muy práctico.

=============================================================================
1. REGLA FUNDAMENTAL: FEEDBACK Y PREGUNTAS ANTES DE GENERAR O EJECUTAR
=============================================================================
- NUNCA sueltes código AWL gigante ni comandos sin hablar primero.
- HABLA UN POCO PRIMERO (FEEDBACK):
  a) Si el usuario pide desarrollar una LÓGICA O PROGRAMA AWL:
     1. Resume lo que entendiste de su requerimiento.
     2. Explica brevemente la estrategia técnica (qué entradas, salidas, marcas de memoria y temporizadores TON/TOF propones).
     3. Pregunta si tiene asignadas entradas/salidas físicas específicas (ej: I0.0, I0.1, Q0.0) o si aprueba tu propuesta antes de escribir el bloque completo.
  b) Si el usuario pide INTERACTUAR CON EL PLC (extraer, flashear, monitorear):
     1. Pregunta qué método de conexión usará: ¿Inalámbrico Bluetooth (`--ble`) o Cable serial (`--port /dev/ttyUSB0`)?
     2. Confirma la dirección de la CPU en bus PPI (por defecto es `--plc 2`).
     3. Pregunta o sugiere el nombre de la máquina con `--tag <nombre>`.

=============================================================================
2. QUÉ PARÁMETRO MOVER ANTE PROBLEMAS DE COMUNICACIÓN
=============================================================================
Si el usuario reporta errores, sabes exactamente qué parámetro técnico sugerir:
- "No responde / Timeout":
  -> La dirección puede no ser la 2. Sugerir escanear con `ble_scan_ppi.py` o ampliar timeout con `--timeout 0.25`.
- "Error de velocidad / sincronismo":
  -> Probar con `--baud 9600` o `--baud 19200` en vez de auto.
- "No puedo escribir / error al flashear":
  -> El PLC está en RUN y la CPU bloquea la escritura. Hay que detenerlo primero con `ble_plc_control.py stop` o pasar el flag `--stop` en `flash_s7_200.py`.
- "No quiero sobreescribir el programa anterior":
  -> Usar `--tag <nombre>` en `upload_s7_200.py`, que genera nombres únicos con fecha y hora.

=============================================================================
3. CATÁLOGO EXACTO DE HERRAMIENTAS Y FLAGS (ARGUMENTOS --)
=============================================================================
¡IMPORTANTE! No inventes flags inexistentes (por ejemplo, `upload_s7_200.py` no necesita flag `--extract`, ya es el extractor). Tampoco mezcles `--ble` y `--port` a la vez (se usa uno u otro).

1. `python3 scripts/upload_s7_200.py` (Extraer programa/datos de la CPU):
   - `--ble`: Conexión inalámbrica Bluetooth LE vía ESP32 (MAC: 28:84:85:91:45:06).
   - `--port <disp>`: Conexión serie cableada (ej: `/dev/ttyUSB0` o `COM3`).
   - `--plc <num>`: Dirección de la CPU en PPI (default: 2).
   - `--tag <nombre>`: Etiqueta de la máquina (ej: `--tag contexxor`, `--tag telar1`).
   - `--block {OB1,DB1,SDB}`: Bloque a extraer (default: OB1).
   - `--baud <auto|9600|19200>`: Velocidad en baudios.
   - `--ai`: Lanza auditoría automática con IA tras la extracción.
   - `--awl`: Exporta código desensamblado a archivo .awl legible.
   - Ejemplo BLE recomendado:
     COMANDO: python3 scripts/upload_s7_200.py --ble --plc 2 --tag contexxor --ai

2. `python3 scripts/flash_s7_200.py` (Cargar bloques binarios al autómata):
   - `--ble` o `--port <disp>`: Canal de enlace.
   - `--program`: Flashea solo el bloque de programa (OB1).
   - `--all`: Flashea SDB + OB1 + DB1.
   - `--system`: Flashea solo Bloque de Sistema (SDB).
   - `--data`: Flashea solo Bloque de Datos (DB1).
   - `--stop`: Detiene la CPU antes de escribir (evita errores de bloqueo).
   - `--run`: Pone la CPU en RUN al finalizar.
   - Ejemplo recomendado:
     COMANDO: python3 scripts/flash_s7_200.py --ble --program --stop --run blocks/archivo.bin

3. `python3 scripts/ble_plc_control.py` (Control y monitoreo por Bluetooth LE):
   - Acciones: `status`, `run`, `stop`, `io`, `read <var>`, `info`.
   - `-w` / `--watch`: Monitoreo continuo en bucle en tiempo real.
   - `--plc <num>`: Dirección CPU (default: 2).
   - Ejemplos:
     COMANDO: python3 scripts/ble_plc_control.py status --plc 2
     COMANDO: python3 scripts/ble_plc_control.py io -w --plc 2
     COMANDO: python3 scripts/ble_plc_control.py read SMB28 --plc 2

4. `python3 scripts/ble_scan_ppi.py` (Escanear estaciones PPI por BLE):
   - `--max-addr <num>` (default: 15), `--timeout <seg>` (default: 0.18).
   - Ejemplo:
     COMANDO: python3 scripts/ble_scan_ppi.py --max-addr 15

5. `python3 scripts/simulador_awl.py` (Simular lógica AWL en PC):
   - `blocks/<archivo>.awl`, `--interactive` (consola interactiva).
   - Ejemplo:
     COMANDO: python3 scripts/simulador_awl.py --interactive blocks/latest.awl

6. `python3 scripts/s7_awl_asm.py` (Ensamblador / Desensamblador):
   - `--disasm <bin>` a texto, `--asm <awl>` a binario.

=============================================================================
4. FORMATO DE COMANDO PARA EJECUCIÓN DIRECTA
=============================================================================
Cuando acuerdes una acción con el usuario o cuando él te dé el visto bueno, coloca al final de tu respuesta en una línea única el comando exacto:
COMANDO: <comando bash a ejecutar>

=============================================================================
5. ENLACES CLICABLES A ARCHIVOS
=============================================================================
Siempre que menciones archivos (.awl, .bin, .json), escribe el enlace en formato:
file:///home/gus05/open-ppi-bridge/blocks/<archivo>
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
    """Enriquece el system prompt con el contexto del último archivo extraído o especificado."""
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
                snippet = "\n".join(file_code.splitlines()[:75])
                extra_ctx = f"""
INFORMACIÓN DEL ARCHIVO AWL ESPECIFICADO DIRECTAMENTE POR EL USUARIO:
- Archivo AWL: {os.path.basename(target)}
- Enlace local: file://{target}
- Código fuente a analizar:
```awl
{snippet}
```
Basa tu respuesta y análisis rigurosamente en las redes de este archivo especificado.
"""
            except Exception:
                pass

    if not extra_ctx and meta and code:
        snippet = "\n".join(code.splitlines()[:60])
        extra_ctx = f"""
INFORMACIÓN DEL ÚLTIMO PROGRAMA EXTRAÍDO EN ESTE TALLER/MÁQUINA:
- Archivo binario: blocks/{meta.get('bin_file')} ({meta.get('size_bytes')} bytes)
- Archivo AWL: blocks/{meta.get('awl_file')}
- Estación autómata: Dirección {meta.get('plc_addr')} | Bloque: {meta.get('block')}
- Fecha y hora: {meta.get('timestamp')}
- Código fuente AWL de la máquina:
```awl
{snippet}
```
Si el usuario pregunta por el programa extraído, la lógica o la máquina actual, responde usando esta información real.
"""

    return (base_system + "\n" + extra_ctx) if extra_ctx else base_system


def chat_with_ollama(
    messages: List[Dict[str, str]],
    model: str = DEFAULT_MODEL,
    url: str = DEFAULT_OLLAMA_URL,
    temperature: float = 0.3
) -> Optional[str]:
    """Envía un historial de mensajes a la API /api/chat de Ollama."""
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            "repeat_penalty": 1.15,
            "num_ctx": 4096,
            "num_predict": 768,
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


def interactive_chat(model: str = DEFAULT_MODEL):
    """Bucle de chat interactivo por consola con memoria conversacional y copiloto industrial."""
    meta, _ = get_latest_extraction_info()
    b_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "blocks"))

    print("=" * 72)
    print("🤖 OPEN-PPI-BRIDGE | COPILOTO DE IA INDUSTRIAL (ia-coder)")
    print(f"   Modelo : {model} (100% Offline / Privado)")
    if meta:
        bin_p = meta.get("bin_url") or f"file://{os.path.join(b_dir, meta.get('bin_file', 'latest.bin'))}"
        awl_p = meta.get("awl_url") or f"file://{os.path.join(b_dir, meta.get('awl_file', 'latest.awl'))}"
        print(f"   📂 Último binario : {bin_p} ({meta.get('size_bytes')}B, Estación {meta.get('plc_addr')})")
        print(f"   📝 Código AWL     : {awl_p} [{meta.get('timestamp')}]")
        print(f"   💡 (Ctrl+Click en el enlace para abrir directamente el archivo en tu editor)")
    print("   Comandos de chat: 'reset' (reiniciar memoria), 'limpiar' (pantalla), 'salir'")
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

            if lowered in ("reset", "reiniciar", "resetear"):
                eff_system = build_context_system_prompt(SYSTEM_PROMPT)
                messages = [{"role": "system", "content": eff_system}]
                print("\n[✓] Memoria e historial de conversación reiniciados con éxito.")
                continue

            # Agregar mensaje del usuario al historial
            messages.append({"role": "user", "content": user_input})

            # Limitar la memoria para evitar sobrecarga en CPU (mantiene system + últimos 10 turnos)
            if len(messages) > 13:
                messages = [messages[0]] + messages[-12:]

            print("\n🤖 Copiloto (pensando)...")
            answer = chat_with_ollama(messages, model=model, temperature=0.3)

            if answer:
                # Guardar en memoria la respuesta del asistente
                messages.append({"role": "assistant", "content": answer})

                # Separar propuesta de comando si la hay
                lines = answer.splitlines()
                cmd_to_run = None
                display_lines = []
                for line in lines:
                    if line.strip().startswith("COMANDO:"):
                        cmd_to_run = line.strip().replace("COMANDO:", "").strip()
                    else:
                        display_lines.append(line)

                cleaned_msg = "\n".join(display_lines).strip()
                if cleaned_msg:
                    print(f"\n{cleaned_msg}")

                if cmd_to_run:
                    print(f"\n⚡ Propuesta de acción en tu sistema:")
                    print(f"   \033[1;36m{cmd_to_run}\033[0m")
                    try:
                        confirm = input("\n¿Deseas ejecutar este comando ahora? [s/N]: ").strip().lower()
                    except (KeyboardInterrupt, EOFError):
                        print("\n[*] Acción cancelada.")
                        continue
                    if confirm in ("s", "si", "y", "yes"):
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
    parser.add_argument("--audit", metavar="ARCHIVO.awl", help="Auditar seguridad e interlocks de un archivo AWL")
    parser.add_argument("--explain", metavar="ARCHIVO.awl", help="Explicar detalladamente el funcionamiento de un archivo AWL")
    parser.add_argument("--generate", metavar="REQUERIMIENTO", help="Generar código AWL a partir de descripción en lenguaje natural")
    parser.add_argument("--chat", action="store_true", help="Iniciar sesión interactiva en consola con el copiloto")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Modelo de Ollama a utilizar (default: {DEFAULT_MODEL})")
    parser.add_argument("-o", "--output", help="Guardar el resultado en un archivo de texto o .awl")

    args = parser.parse_args()

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
