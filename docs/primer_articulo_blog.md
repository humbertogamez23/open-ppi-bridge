# Cómo eliminamos Windows y Micro/WIN para flashear un PLC Siemens S7-200 desde Linux en 0.9 segundos

Durante décadas, la automatización industrial ha estado atada a ecosistemas de software cerrados. Si tienes un autómata **Siemens SIMATIC S7-200** (uno de los PLCs más robustos y extendidos del mundo en maquinaria de empaque, calderas y plantas de tratamiento), la historia siempre ha sido la misma: dependes obligatoriamente de **STEP 7-Micro/WIN**, un software propietario diseñado originalmente para Windows XP/7 de 32 bits, adaptadores USB-PPI con chips propietarios y procesos tediosos en máquinas virtuales.

Hoy rompemos esa dependencia: hemos logrado **escribir y transferir bloques de programa (OB1) y datos (DB1) directamente desde la terminal de Linux a través de RS-485 en solo 0.9 segundos**, prescindiendo al 100% de Windows y de Micro/WIN.

Aquí documentamos la ingeniería inversa del protocolo PPI/S7comm, la solución a los errores internos de Siemens y cómo llevar esto a un microcontrolador de $5 USD.

---

## 1. El protocolo bajo el osciloscopio: PROFIBUS/PPI

El puerto frontal de comunicación del S7-200 (puerto sub-D hembra de 9 pines) utiliza la capa física **RS-485** con una configuración asíncrona estándar:
* **Baudrate:** 9600 bps (o 19200 / 187.5k).
* **Formato:** 8 bits de datos, paridad par (Even), 1 bit de parada (`8E1`).
* **Pines:** Pin 3 (`RS-485 B / RxD/TxD-P`) y Pin 8 (`RS-485 A / RxD/TxD-N`).

A nivel de enlace de datos, corre **PROFIBUS FDL (Fieldbus Data Link)** utilizando tramas estandarizadas SD2 (Start Delimiter 2, `0x68`) para intercambio de datos con longitud variable:

```text
[0x68] [LE] [LEr] [0x68] [DA] [SA] [FC] [DSAP] [SSAP] ... [S7COMM PAYLOAD] ... [FCS] [0x16]
```

Donde:
* `LE` y `LEr`: Longitud de la carga útil duplicada para integridad.
* `DA` / `SA`: Dirección de destino (PLC = `0x02`) y origen (PC = `0x00`).
* `FC`: Function Code de control de enlace.
* `FCS`: Checksum aritmético de 8 bits (suma de los bytes de datos modulo 256).
* `0x16`: Delimitador de fin de trama (End Delimiter).

---

## 2. El misterio del error `0xD240`: Reglas de coordinación violadas

Uno de los mayores dolores de cabeza en ingeniería inversa de Siemens es encontrarse con este mensaje de error en la capa S7comm:
```text
S7comm Error [0xD240]: Internal coordination rules violated
```

Al desmenuzar las capturas con Wireshark y analizadores lógicos, descubrimos la causa raíz: el **Frame Count Bit (FCB)** en el byte `FC` de PROFIBUS.

En el estándar PROFIBUS FDL:
1. Las peticiones SDR (*Send and Request Data*) alternan estrictamente el bit 5 (`FCB`):
   * Primer comando: `0x7C` (FCB = 1, FCV = 1).
   * Segundo comando: `0x5C` (FCB = 0, FCV = 1).
   * Tercer comando: `0x7C` (FCB = 1, FCV = 1)...
2. Si envías dos peticiones consecutivas con el mismo valor en el bit `FCB`, el procesador de comunicaciones del S7-200 asume que se trata de una retransmisión por paquete perdido o duplicado y rechaza la ejecución de comandos de escritura de memoria o cambio de estado de CPU con el error `0xD240`.

Implementar la alternancia estricta del bit FCB en nuestro controlador resolvió instantáneamente el 100% de los rechazos de comunicación.

---

## 3. La máquina de estados del Flasher en Linux

Para escribir un nuevo bloque de programa en la memoria EEPROM/RAM del autómata, diseñamos una máquina de estados determinista en Python puro (`scripts/flash_s7_200.py`):

```text
       [1. Negociación PDU (240 bytes)]
                      ↓
       [2. STOP CPU (0x29 - P_PROGRAM)]
                      ↓
       [3. Borrado de bloque (_DELE 0x28)]
                      ↓
   ┌─→ [4. Inicio de descarga (_INSE 0x1A)]
   │                  ↓
   │   [5. Transferencia de Chunks (_DOWN 0x1B)]
   └── (Fragmentación en bloques de 219 bytes)
                      ↓
       [6. Fin de descarga (_ENDB 0x1C)]
                      ↓
       [7. Commit del bloque (_INSE 0x28)]
                      ↓
       [8. RUN CPU (0x28 - P_PROGRAM)]
```

### El resultado:
```bash
python3 scripts/flash_s7_200.py --port /dev/ttyUSB0 --block examples/blocks/program_block_ob1.bin
```

En **0.90 segundos**, el script negocia la sesión, detiene el autómata de forma segura, borra el bloque anterior en memoria, fragmenta y escribe los 310 bytes del bloque de programa OB1, verifica la integridad y reactiva el PLC en modo RUN.

---

## 4. Desensamblado de Bytecode Nativo a AWL

Para cerrar el círculo sin depender de compiladores cerrados, implementamos un desensamblador de bytecode (`scripts/s7_awl_asm.py`). El PLC ejecuta instrucciones de 16 bits nativas que traducimos automáticamente a lista de instrucciones (AWL/STL):

```text
0x0000: 68 00       -> LD      I0.0
0x0002: 50 01       -> =       Q0.1
0x0004: 69 00       -> LDN     I0.0
0x0006: 50 02       -> =       Q0.2
0x0008: 70 00       -> A       I0.0
0x000A: 78 01       -> AN      I0.1
0x000C: 38 60 00 1E -> TON     T96, +30
```

Esto permite auditar y reconstruir la lógica de cualquier autómata directamente desde sus bloques binarios.

---

## 5. El futuro: Un puente industrial IoT de $5 USD con ESP32-S3

El ensamblador y el motor de flasheo pesan **menos de 50 KB**. No requieren librerías externas complejas.

Esto abre una posibilidad revolucionaria en plantas industriales:
* Un módulo **ESP32-S3** acoplado a un transceptor **MAX485/SN65HVD** montado en el riel DIN junto al PLC.
* Conexión por **Bluetooth Low Energy (BLE)** o **WiFi/MQTT**.
* Los técnicos e ingenieros pueden actualizar la lógica de automatización, cargar recetas o auditar el código desde un teléfono móvil o panel web local, sin cables pesados ni licencias propietarias.

---

### Código y Repositorio Abierto
Todo el código, especificaciones del protocolo y utilidades de flasheo están publicados bajo licencia libre en GitHub:

👉 **Repositorio oficial:** [github.com/humbertogamez23/open-ppi-bridge](https://github.com/humbertogamez23/open-ppi-bridge)

¿Tienes dudas, sugerencias o autómatas S7-200 en tu taller? Deja tus comentarios abajo o abre un *Issue* en el repositorio.
