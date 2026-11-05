#!/usr/bin/env python3
"""
ai_copilot.py - Copiloto de IA Local y Offline para Lógica Siemens S7-200
=============================================================================
Asistente de ingeniería industrial basado en modelos LLM locales (Qwen 2.5 Coder
vía Ollama) para análisis, auditoría de seguridad y generación de código AWL/STL.

Funciona de forma 100% privada, desconectada (air-gapped) y ligera (~1.3 GB RAM).

Capacidades:
  1. Auditoría de Seguridad (--audit): Detecta condiciones de carrera, interlocks
     faltantes (ej. estrella-delta simultáneos) y pulsos virtuales no reseteados.
  2. Explicación Técnica (--explain): Traduce redes AWL complejas a lenguaje natural.
  3. Generación de Lógica (--generate): Escribe código AWL nativo a partir de
     descripciones en lenguaje natural, listo para ensamblar con s7_awl_asm.py.
  4. Modo Interactivo (--chat): Terminal interactiva para consultar dudas técnicas.

Autores: Humberto Gámez (@humbertogamez23) & Antigravity AI (open-ppi-bridge project)
Licencia: GPL-3.0
"""

import sys
import os
import json
import argparse
import urllib.request
import urllib.error
from typing import Optional, Dict, Any

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5-coder:1.5b"

SYSTEM_PROMPT = """Eres el Copiloto de Inteligencia Artificial Industrial de open-ppi-bridge, especializado en programación, auditoría y análisis de autómatas Siemens SIMATIC S7-200 (CPU 21x y 22x) en lenguaje AWL/STL (Lista de Instrucciones).

CONOCIMIENTOS TÉCNICOS ESENCIALES:
- Mnemónicos AWL Siemens:
  * LD, LDN: Carga contacto normalmente abierto / cerrado.
  * A, AN: Conjunción lógica AND con contacto NA / NC.
  * O, ON: Disyunción lógica OR con contacto NA / NC.
  * ALD, OLD: AND / OR entre bloques de contactos de la pila lógica.
  * =: Asignación a bobina física (Q) o marca interna (M, V).
  * S, R: Set (activación con enclavamiento) y Reset de bits.
  * TON, TONR, TOF: Temporizadores con retardo (Base 1ms, 10ms o 100ms).
  * CALL: Llamada a subrutinas (SBR0, SBR1, etc.).
  * MOVW, MOVB, MOVD: Transferencia de palabras, bytes o dobles palabras (AC0, VW, SMB).
- Áreas de memoria S7-200:
  * I (Entradas digitales físicas: I0.0..I1.7).
  * Q (Salidas digitales físicas: Q0.0..Q1.7).
  * M (Marcas de memoria de control: M0.0..M31.7).
  * V (Memoria variable / Bloque de Datos DB1: VB, VW, VD).
  * AC (Acumuladores: AC0..AC3).
  * SM (Marcas especiales: SM0.0 bit siempre ON, SM0.1 primer scan, SMB28/29 potenciómetros analógicos).
- Criterios de Seguridad Industrial:
  * Interbloqueos mecánicos/eléctricos por software (ej. Estrella Q0.1 y Delta Q0.2 NUNCA juntos).
  * Pulsadores virtuales de la App móvil (V200.0, V200.1) SIEMPRE deben auto-resetearse para evitar comandos pegados por pérdida de enlace BLE.
  * Retención de marcha con contacto auxiliar y parada de emergencia de corte activo (I0.1 con AN o A según contacto físico).

HERRAMIENTAS DISPONIBLES EN EL PROYECTO (open-ppi-bridge):
- Extraer programa del PLC: `python3 scripts/upload_s7_200.py --ble -o blocks/<nombre>.bin --ai` (o con cable `--port COM3` / `--port /dev/ttyUSB0`).
- Flashear a EEPROM: `python3 scripts/flash_s7_200.py --ble --block OB1 blocks/<nombre>.bin`
- Simular scan y lógica: `python3 scripts/simulador_awl.py blocks/<nombre>.awl`
- Desensamblar/Ensamblar: `python3 scripts/s7_awl_asm.py blocks/<nombre>.bin`
- Escaneo de estaciones: `python3 scripts/ble_scan_ppi.py` o `python3 scripts/scan_ppi.py`
- Listar archivos del repo: `ls -lh blocks/` o `ls -lh scripts/`

CAPACIDAD DE EJECUCIÓN:
Cuando el usuario te pida realizar una tarea concreta del sistema (como extraer el programa del PLC, simular lógica, flashear o listar archivos), describe brevemente lo que harás y coloca al final de tu respuesta una línea exacta con el formato:
COMANDO: <comando bash a ejecutar>
Ejemplo:
COMANDO: python3 scripts/upload_s7_200.py --ble -o blocks/OB1_extraido.bin --ai

TUS RESPUESTAS:
- Deben ser concisas, altamente técnicas, precisas y en español profesional.
- En generación de código, entrega código AWL bien estructurado con comentarios por Red (Network).
"""


def check_ollama_status(url: str = DEFAULT_OLLAMA_URL) -> bool:
    """Verifica si el servidor local de Ollama está activo y respondiendo."""
    try:
        req = urllib.request.Request(f"{url}/api/tags", headers={"User-Agent": "open-ppi-copilot"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            return resp.status == 200
    except Exception:
        return False


def query_ollama(prompt: str, system: str = SYSTEM_PROMPT, model: str = DEFAULT_MODEL, url: str = DEFAULT_OLLAMA_URL, temperature: float = 0.2) -> Optional[str]:
    """Envía una consulta a la API de Ollama y devuelve la respuesta generada."""
    payload = {
        "model": model,
        "prompt": prompt,
        "system": system,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_ctx": 4096,
            "num_predict": 512,
        }
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{url}/api/generate",
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "open-ppi-copilot"}
    )

    try:
        with urllib.request.urlopen(req, timeout=180.0) as resp:
            if resp.status == 200:
                result = json.loads(resp.read().decode("utf-8"))
                return result.get("response", "").strip()
    except urllib.error.URLError as e:
        print(f"[-] Error de conexión con Ollama ({e}). Asegúrese de que el servicio esté activo (`ollama serve`).")
    except Exception as e:
        print(f"[-] Error inesperado procesando la consulta: {e}")
    return None


def audit_awl_code(awl_text: str, model: str = DEFAULT_MODEL) -> str:
    """Audita un código AWL en busca de riesgos de seguridad, interlocks y buenas prácticas."""
    prompt = f"""Realiza una AUDITORÍA TÉCNICA DE SEGURIDAD INDUSTRIAL para el siguiente código AWL de Siemens S7-200:

```awl
{awl_text}
```

Estructura tu reporte con:
1. 🔍 Resumen General de la Lógica (Propósito del bloque y subrutinas).
2. ⚠️ Puntos Críticos y Verificación de Seguridad:
   - ¿Existen interbloqueos adecuados entre salidas mutuamente excluyentes (ej. contactores estrella/delta o apertura/cierre)?
   - ¿El paro de emergencia y seguridades cortan la retención de marcha?
   - ¿Las variables de control remoto (bits V o de App móvil) tienen auto-reset de seguridad?
3. 💡 Recomendaciones de Mejora o Corrección (si aplica).
"""
    resp = query_ollama(prompt, model=model, temperature=0.1)
    return resp or "[-] No se pudo obtener la auditoría del modelo local."


def explain_awl_code(awl_text: str, model: str = DEFAULT_MODEL) -> str:
    """Explica detalladamente qué hace cada red del código AWL."""
    prompt = f"""Explica en detalle y de forma comprensible para un técnico de mantenimiento qué hace el siguiente código AWL de Siemens S7-200.
Explica red por red (Network) la función de las entradas, marcas, temporizadores y salidas:

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
    """Bucle de chat interactivo por consola con el copiloto industrial."""
    print("=" * 70)
    print("🤖 OPEN-PPI-BRIDGE | COPILOTO DE IA INDUSTRIAL LOCAL")
    print(f"   Modelo: {model} (100% Offline / Privado)")
    print("   Escribe 'salir' o 'exit' para terminar, o 'limpiar' para despejar la pantalla.")
    print("=" * 70)

    while True:
        try:
            user_input = input("\n👨‍💻 Tú: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("salir", "exit", "quit"):
                print("[*] Saliendo del Copiloto de IA.")
                break
            if user_input.lower() in ("limpiar", "clear"):
                os.system("clear" if os.name == "posix" else "cls")
                continue

            print("\n🤖 Copiloto (pensando)...")
            answer = query_ollama(user_input, model=model)
            if answer:
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
                        print("[*] Comando cancelado por el usuario.")
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
