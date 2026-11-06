# Puente RS485 PPI (Siemens S7-200) <-> Micro/WIN (ESP32-S3)

Firmware nativo en C con **ESP-IDF v5.3** y **FreeRTOS** para implementar un puente transparente y determinista entre **STEP 7-Micro/WIN** (en VM Windows 7 QEMU) y autómatas programables **Siemens S7-200** sobre bus físico **RS485** con protocolo **PPI**.

---

## 1. Conexiones y Pinout (ESP32-S3)

| Señal / Conexión | Pin ESP32-S3 | Dispositivo Conectado | Configuración |
| :--- | :--- | :--- | :--- |
| **UART0 TX** | GPIO 43 | Conversor USB-Serial CH343 hacia PC | 9600 baud, **8E1** |
| **UART0 RX** | GPIO 44 | Conversor USB-Serial CH343 desde PC | 9600 baud, **8E1** |
| **UART1 TX** | GPIO 17 | Transceptor MAX485 (pin DI) | 9600 baud, **8E1** |
| **UART1 RX** | GPIO 16 | Transceptor MAX485 (pin RO) | 9600 baud, **8E1** |
| **RTS (DE/RE)** | GPIO 4 | Transceptor MAX485 (pines DE y RE puenteados) | Control de dirección half-duplex por hardware |
| **LED RGB** | GPIO 48 | NeoPixel WS2812 integrado | Diagnóstico visual de tráfico |
| **USB JTAG/Serial**| D+ / D- nativo | Puerto USB secundario del ESP32-S3 | Consola de logs (`ESP_LOGI`) y flasheo |

### Conexión del MAX485 al PLC Siemens S7-200 (Conector DB9)
* **Pin 3 DB9**: RS485 Señal **B (+)** ➡️ Conectar a pin **B** del módulo MAX485.
* **Pin 8 DB9**: RS485 Señal **A (-)** ➡️ Conectar a pin **A** del módulo MAX485.
* **Pin 5 DB9**: GND / 0V ➡️ Conectar a **GND común** del ESP32 / MAX485.

---

## 2. Arquitectura de Firmware (v2)

* **Acumulación de telegramas por silencio (`FRAME_GAP_MS = 5 ms`)**:
  * Para evitar la fragmentación que rompía los telegramas largos SD2, la tarea de recepción de la PC acumula los bytes entrantes en un buffer (`FRAME_MAX_BYTES = 512`) hasta detectar una pausa de silencio de 5 ms.
  * Una vez acumulada la trama completa, se verifica la cabecera PPI (`0x68`, `0x10`, `0xE5`). Si es válida, se envía en un solo bloque continuo a la UART RS485.
* **Manejo Half-Duplex por Hardware**:
  * Configurado con `uart_set_mode(RS485_UART, UART_MODE_RS485_HALF_DUPLEX)`.
  * La línea RTS (GPIO 4) se eleva automáticamente por hardware antes de transmitir y cae exactamente al completarse el último bit de parada, eliminando necesidad de delays manuales.
  * Timeout de transmisión `uart_wait_tx_done` ajustado a 500 ms para permitir tramas largas completas.
* **Compatibilidad con Task Watchdog (TWDT)**:
  * La lectura inicial de UART utiliza un timeout de 1000 ms en lugar de espera infinita, alimentando periódicamente el watchdog para evitar falsos reinicios durante tiempos sin tráfico de la PC.
* **Distribución de núcleos en FreeRTOS**:
  * `task_pc_to_plc`: Core 0 (Prioridad 10).
  * `task_plc_to_pc`: Core 1 (Prioridad 10).
  * `task_led`: Core 0 (Prioridad 3).

### Códigos de Color del LED RGB (GPIO 48)
* 🟢 **Verde (breve)**: Inicialización del sistema correcta.
* 🔵 **Azul**: Tráfico detectado de PC (Micro/WIN) hacia el PLC.
* 🔴 **Rojo**: Tráfico detectado del PLC hacia la PC.
* 🟣 **Magenta**: Comunicación bidireccional activa y sincronizada.

---

## 3. Comandos de Compilación y Flasheo

### Entorno ESP-IDF
```bash
source /home/gus05/esp/esp-idf/export.sh
cd /home/gus05/esp/ppi_bridge
```

### Compilar
```bash
idf.py build
```

### Grabar en el ESP32-S3 (Conectado al puerto USB JTAG / /dev/ttyACM0)
```bash
python -m esptool --chip esp32s3 -b 460800 --before default_reset --after hard_reset write_flash "@build/flash_args"
```
O directamente:
```bash
idf.py -p /dev/ttyACM0 flash
```

---

## 4. Integración con Máquina Virtual Windows 7

El script `/home/gus05/VMs/windows7/start-win7.sh` vincula el chip conversor serial **CH343** (`1a86:55d3`) del ESP32-S3 como puerto serial COM nativo a QEMU:

```bash
# Configuración en start-win7.sh:
# 1. Habilita permisos chmod 666 al nodo ttyUSB*/ttyACM*
# 2. Configura modo low_latency mediante setserial
# 3. Agrega el argumento de QEMU:
-serial /dev/ttyACM0
```

En Windows 7, Micro/WIN se configura para comunicarse a través de **PC/PPI cable**, puerto **COM1**, velocidad **9600 baudios**.
