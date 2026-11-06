# Puente RS485 PPI — Documentación del Proyecto

> **Última actualización:** 2026-09-26  
> **Hardware:** ESP32-S3 (QFN56 rev v0.2) — 8MB PSRAM, **16MB Flash**  
> **Firmware base:** ESP-IDF v5.3.1  
> **MAC:** `90:70:69:09:04:74`

---

## 1. Descripción general

Puente bidireccional entre el software **Micro/WIN** (PC) y un **PLC Siemens S7-200** usando el protocolo **PPI/MPI** (9600 baudios, 8E1).

```
[PC - Micro/WIN]
      │
  CH343 (USB→UART)
      │
  UART0 (GPIO43 TX / GPIO44 RX)
      │
  [ESP32-S3]
      │
  UART1 (GPIO1 TX / GPIO2 RX / GPIO5 DE/RE)
      │
  Optoacopladores PC817 (4 canales, señales invertidas)
      │
  Transceptor RS485
      │
  [PLC S7-200 — protocolo PPI]

  USB Serial/JTAG → logs en consola (idf.py monitor)
```

---

## 2. Pinout definitivo (versión actual)

| Función          | GPIO | Notas                              |
|------------------|------|------------------------------------|
| UART0 TX (PC)    | 43   | Default ESP32-S3, hacia CH343      |
| UART0 RX (PC)    | 44   | Default ESP32-S3, desde CH343      |
| UART1 TX (RS485) | 1    | Libre de PSRAM                     |
| UART1 RX (RS485) | 2    | Libre de PSRAM                     |
| UART1 DE/RE      | 5    | Controlado por RTS hardware        |
| LED NeoPixel     | 48   | WS2812 integrado                   |
| USB Serial/JTAG  | —    | Canal de logs (no toca UART0/1)    |

---

## 3. Configuración UART RS485

- **Baudios:** 9600
- **Formato:** 8E1 (8 bits, paridad par, 1 stop)
- **Modo:** `UART_MODE_RS485_HALF_DUPLEX` (control automático de RTS/DE)
- **Inversión de señales:** `UART_SIGNAL_TXD_INV | UART_SIGNAL_RXD_INV | UART_SIGNAL_RTS_INV`  
  → Necesario por los optoacopladores PC817 que invierten la lógica
- **DE/RE:** GPIO5 vía RTS hardware (automático)

---

## 4. Hardware físico

- **Módulo RS485:** Transceptor MAX485 (o compatible DIP-8 / módulo)
- **Aislamiento:** Etapa de alta velocidad con 1× A2631 (HCPL-2631 doble canal 10 MBd para TX y RTS) + 1× 6N137 (1 canal 10 MBd para RX) + Convertidor aislado DC-DC B0505S-1W
- **Pull-ups y Failsafe:** Resistencias de 1 kΩ (pull-ups en optos) y 4.7 kΩ (failsafe bus RS485)
- **ESP con GPIO quemado:** MAC `90:70:69:09:04:74` (GPIO17 dañado anteriormente por módulo sin aislamiento; pines actuales 1, 2 y 5 100% operativos)
- **Flash real del chip:** 16MB DIO @ 80MHz (validada y configurada 100% operativa en sdkconfig)

---

## 5. Comportamiento del LED (GPIO48 WS2812)

| Color   | Significado              |
|---------|--------------------------|
| Verde   | Arranque OK (200ms)      |
| Azul    | Tráfico PC → PLC activo  |
| Rojo    | Tráfico PLC → PC activo  |
| Magenta | Tráfico bidireccional    |
| Apagado | Sin tráfico              |

---

## 6. Tareas FreeRTOS

| Tarea     | Núcleo | Prioridad | Stack  | Función                         |
|-----------|--------|-----------|--------|---------------------------------|
| `pc2plc`  | 0      | 10        | 4096 B | Lee UART0, escribe UART1 RS485  |
| `plc2pc`  | 1      | 10        | 4096 B | Lee UART1 RS485, escribe UART0  |
| `led`     | any    | 3         | 2048 B | Indicador visual de tráfico     |

---

## 7. Historial de correcciones por versión

### v1 — inicial
- Filtro `is_ppi_start()` aplicado por chunk, no por telegrama completo
- Tramas largas SD2 se corrompían (llegaban partidas en múltiples lecturas)

### v2 — acumulación de telegrama completo
- Se acumula el telegrama completo por silencio `FRAME_GAP_MS = 5ms` antes de filtrar
- Tramas cortas SD1/SC funcionaban bien

### v3 — control manual DE/RE + timeout dinámico
- Se eliminó `UART_MODE_RS485_HALF_DUPLEX`: el driver dejaba DE asertado en reposo (2.8V medidos entre A/B sin PLC)
- Control manual con `gpio_set_level()` → DE arranca en LOW (escucha)
- Se agregó `uart_flush_input()` tras TX para descartar eco propio
- **Timeout `uart_wait_tx_done()` dinámico:**
  ```c
  uint32_t tx_ms = (uint32_t)((total * 11UL * 1000UL) / BAUD_RATE) + 30;
  uart_wait_tx_done(RS485_UART, pdMS_TO_TICKS(tx_ms));
  ```
  → Timeout fijo de 100ms cortaba tramas >87 bytes a mitad de transmisión
- Timeout de lectura inicial reducido de 50ms a 10ms (menos latencia)
- Puente transparente: sin filtro de cabecera (solo log informativo)

### v4 — actual (en `/esp/ppi_bridge/main/main.c`)
- Vuelve a `UART_MODE_RS485_HALF_DUPLEX` con inversión de señales por optos PC817
- DE/RE en GPIO5 controlado por RTS hardware automático
- GPIO cambiados: RS485 en GPIO1/2/5 (libres de PSRAM)
- ⚠️ **`uart_wait_tx_done()` regresó a timeout fijo 100ms** — pendiente aplicar cálculo dinámico de v3

---

## 8. Estado de Pendientes y Mejoras Aplicadas (v5 - 100% Funcional)

- [x] **Corregido `uart_wait_tx_done()` a timeout dinámico:**
  Calculado con precisión: `uint32_t tx_ms = (uint32_t)((total * 11UL * 1000UL) / BAUD_RATE) + 40;`
- [x] **Corregido y verificado Flash Size en 16MB:**
  Configurado en `sdkconfig` y `sdkconfig.defaults` a 16MB DIO @ 80MHz. Sin warnings de truncamiento.
- [x] **Tabla de particiones de 16MB (`partitions.csv`):**
  - `nvs` (64 KB): Almacenamiento permanente de métricas y parámetros.
  - `phy_init` (4 KB): Calibración RF.
  - `factory` (4096 KB = 4 MB): Espacio de firmware.
  - `storage` (12160 KB = 11.87 MB): Partición permanente para almacenamiento de logs y archivos.
- [x] **Memoria Permanente NVS 100% Operativa:**
  Inicialización con autoreparación (`nvs_flash_init()`), registro de métricas persistentes (`boot_count` en Flash).
- [x] **Corrección de TWDT:**
  Reconfiguración mediante `esp_task_wdt_reconfigure()` eliminando el error de arranque de ESP-IDF v5.
- [x] **Precisión de ticks FreeRTOS a 1000 Hz:**
  `CONFIG_FREERTOS_HZ=1000` (resolución de 1ms) para evitar que `FRAME_GAP_MS=5` trunque a 0 ticks.
- [ ] `ppi_bridge.c` vacío — reservado para futuras funciones (ej. BLE log viewer)

---

## 9. Comandos útiles

```bash
# Entrar al entorno IDF
source ~/esp/esp-idf/export.sh
cd ~/esp/ppi_bridge

# Compilar
idf.py build

# Flashear
idf.py -p /dev/ttyACM0 flash

# Monitor de logs
idf.py -p /dev/ttyACM0 monitor

# Flashear y monitorear
idf.py -p /dev/ttyACM0 flash monitor

# Info del chip/flash
esptool.py --port /dev/ttyACM0 flash_id
```

---

## 10. Notas de campo

- El modo `UART_MODE_RS485_HALF_DUPLEX` automático fallaba en v3: DE quedaba asertado en reposo causando colisión con el PLC (0.05V medidos en bus con PLC conectado). Se resolvió en v4 usando optos PC817 + inversión de señales.
- FreeRTOS con `HZ=100` → tick mínimo = 10ms. `FRAME_GAP_MS=5` pasado a `pdMS_TO_TICKS()` equivale en la práctica a **10ms** (1 tick), no 5ms.
- Puerto en Linux: `/dev/ttyACM0` (CH343 / Micro/WIN) y `/dev/ttyACM1` (USB Serial/JTAG consola logs ESP32-S3)

---

## 11. Resultados de Pruebas de Campo (2026-09-26)

1. **Estado del Firmware y Memoria Permanente:**
   - Memoria Flash de 16 MB y NVS 100% validadas y activas. Cero errores de arranque.
   - Boot counter persistente en Flash operando.
   - Partición `storage` (11.87 MB) disponible para logs.

2. **Prueba de Escaneo Micro/WIN (Estaciones 1 a 126):**
   - **Resultado en PC->PLC:** Excelente. Las 126 tramas SD1 de sondeo (`10 DA 00 49 FCS 16`) llegaron con 6 bytes exactos sin fragmentación ni desbordamiento de buffer.
   - **Resultado en PLC->PC:** No se registró respuesta del autómata en el bus.

3. **Diagnóstico Físico y Decisión de Hardware:**
   - **Módulo PC817:** Los módulos comerciales de 4 canales suelen tener resistencias de entrada de $1\text{ k}\Omega$ y LEDs SMD en serie (y resistencias SMD 302 de $3\text{ k}\Omega$), requiriendo $\approx 3.2\text{V}$ para disparar el diodo interno. Con los 3.3V del ESP32-S3 la corriente $I_f$ cae a niveles marginales ($< 1\text{ mA}$), aumentando los tiempos de propagación a más de $40\ \mu\text{s}$ y deformando la señal cuadrada a 9600 baudios ($104\ \mu\text{s}$/bit).
   - **Conclusión de Aislamiento:** Conexión directa sin optos quema pines del ESP32 (riesgo validado físicamente en sesión previa). Se adopta el reemplazo definitivo por optoacopladores de alta velocidad **6N137**.

---

## 12. Especificación Técnica de Aislamiento con 6N137 (Definitivo)

### A. Justificación y Análisis de Idoneidad Técnica
1. **Velocidad de Respuesta:**
   - A 9600 baudios, el tiempo de 1 bit es de $104.16\ \mu\text{s}$.
   - El PC817 anterior exhibía tiempos de subida/bajada $t_r / t_f > 40\ \mu\text{s}$ (casi el 40% del ancho del pulso), redondeando los bordes y corrompiendo la paridad o el bit de stop.
   - El **6N137** conmuta en $< 75\text{ ns}$ (frecuencia hasta 10 MBd), por lo que la distorsión del bit es menor al $0.07\%$, garantizando margen suficiente incluso si se escala la velocidad PPI a 19.2 kbps o 187.5 kbps.
2. **Cálculo de Corrientes de Excitación de los LEDs ($I_F$):**
   - **Canales TX y DE/RE (desde ESP32-S3 a 3.3V):**
     $$I_F = \frac{V_{ESP} - V_F}{R} = \frac{3.3\text{V} - 1.4\text{V}}{330\ \Omega} \approx 5.76\text{ mA}$$
     *(Supera el umbral de disparo garantizado $I_{TH} \le 5\text{ mA}$ del 6N137 y no sobrecarga los GPIOs del ESP32).*
   - **Canal RX (desde MAX485 RO a 5V):**
     $$I_F = \frac{V_{RO} - V_F}{R} = \frac{5.0\text{V} - 1.4\text{V}}{470\ \Omega} \approx 7.66\text{ mA}$$
     *(Corriente ideal de saturación recomendada por el fabricante).*
3. **Protección Absoluta del ESP32-S3 mediante Colector Abierto:**
   - El pin 8 de U3 (RX) se alimenta a 5V (VBUS) para cumplir con el mínimo del comparador interno ($V_{CC} \ge 4.5\text{V}$).
   - Como la salida (Pin 6) es **Open-Collector**, no inyecta voltaje propio; solo conecta a GND o flota.
   - Al colocar el Pull-Up de $1\text{ k}\Omega$ a **+3.3V del ESP32**, la tensión máxima hacia GPIO2 es rigurosamente $3.3\text{V}$, eliminando cualquier riesgo de quemar otro pin.

---

### B. Tabla de Estados Lógicos e Inversión por Firmware

El 6N137 es inherentemente **inversor** (LED encendido $\rightarrow$ VO en LOW / $0\text{V}$).  
En `main.c` ya está configurado por hardware:
```c
uart_set_line_inverse(RS485_UART, UART_SIGNAL_TXD_INV | UART_SIGNAL_RXD_INV | UART_SIGNAL_RTS_INV);
```
Esta inversión en el periférico de silicio del ESP32-S3 se complementa con los optoacopladores:

| Canal | Estado Funcional | Nivel Interno ESP-IDF | Nivel Físico en GPIO (Invertido) | LED 6N137 | Salida VO del Opto (Pull-Up) | Estado en MAX485 / Bus RS485 |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **TX** | **Reposo (Mark / 1)** | HIGH (1) | **LOW (0V)** | Apagado | **HIGH (+5V_ISO)** | DI = HIGH $\rightarrow$ Bus en Reposo ($A > B$) |
| **TX** | **Start bit (0)** | LOW (0) | **HIGH (3.3V)** | Encendido | **LOW (0V)** | DI = LOW $\rightarrow$ Bus en Espacio ($B > A$) |
| **RTS** | **Modo Escucha (RX)** | LOW (0) | **HIGH (3.3V)** | Encendido | **LOW (0V)** | DE = 0, /RE = 0 $\rightarrow$ MAX485 en Recepción |
| **RTS** | **Transmitiendo (TX)**| HIGH (1) | **LOW (0V)** | Apagado | **HIGH (+5V_ISO)** | DE = 1, /RE = 1 $\rightarrow$ MAX485 en Transmisión |
| **RX** | **Dato del PLC = 1** | — | — | Encendido (RO=5V) | **LOW (0V)** $\rightarrow$ GPIO2 | Periférico UART invierte $\rightarrow$ Lee **1** |
| **RX** | **Dato del PLC = 0** | — | — | Apagado (RO=0V) | **HIGH (3.3V)** $\rightarrow$ GPIO2| Periférico UART invierte $\rightarrow$ Lee **0** |

> **Conclusión:** La concordancia lógica es del 100%. No se requiere modificar una sola línea de código en `main.c`.

---

### C. Pinout de los Componentes (DIP-8, Vista Superior)

**1. A2631 / HCPL-2631 (Doble canal, 10 MBd — usado para TX y RTS):**
```text
               ┌───[ A2631 ]───┐
     Ánodo 1 1 ──┤ [LED 1] [Out 1]├── 8  VCC (+5V_ISO)
    Cátodo 1 2 ──┤                ├── 7  VO1 (Salida TX -> DI MAX485)
  ⚠️ Cátodo 2 3 ──┤ [LED 2] [Out 2]├── 6  VO2 (Salida RTS -> DE/RE MAX485)
  ⚠️ Ánodo 2 4 ──┤                ├── 5  GND_ISO
               └───────────────┘
```
> ⚠️ **ATENCIÓN AL PINOUT DEL A2631:**
> - En el **Canal 1 (TX)**: Pin 1 = **Ánodo**, Pin 2 = **Cátodo**.
> - En el **Canal 2 (RTS)**: Pin 4 = **Ánodo**, Pin 3 = **Cátodo** (los terminales del LED 2 vienen invertidos por diseño del encapsulado).

**2. 6N137 (Simple canal, 10 MBd — usado para RX):**
```text
               ┌───[ 6N137 ]───┐
      (NC) 1 ──┤               ├── 8  VCC (+5V VBUS ESP)
     Ánodo 2 ──┤ [LED]  [Logic]├── 7  VE (Enable -> al Pin 8)
    Cátodo 3 ──┤        [Schmitt]├── 6  VO (Salida RX -> GPIO2 ESP)
      (NC) 4 ──┤        [Driver]├── 5  GND_ESP
               └───────────────┘
```
> **Reglas mandatarias:**
> 1. **Pin 7 (VE) del 6N137:** Puenteado al **Pin 8 (VCC)**.
> 2. **Capacitor de desacoplo:** 1× cerámico de $100\text{ nF}$ (104) entre Pin 8 y Pin 5 de cada integrado (A2631, 6N137 y MAX485).

---

### D. Esquema de Conexión Completo (A2631 + 6N137)

```text
======================= DOMINIO 1: ESP32-S3 =======================
 [ESP32-S3]
   GPIO 1 (TX)  ──────[ 330 Ω ]────> Pin 1 Ánodo 1 (A2631: TX)
   GND_ESP      ───────────────────> Pin 2 Cátodo 1 (A2631: TX)

   GPIO 5 (RTS) ──────[ 330 Ω ]────> Pin 4 Ánodo 2 (A2631: RTS)
   GND_ESP      ───────────────────> Pin 3 Cátodo 2 (A2631: RTS)

   GPIO 2 (RX)  <──────┬───────────── Pin 6 VO (6N137: RX)
                      [1 kΩ]
                        │
   +3.3V        ────────┴──────────── (Pull-up exclusivo RX hacia ESP)
   
   +5V (VBUS)   ────────┬──────────── Pin 8 (VCC 6N137) & Pin 7 (VE 6N137)
                        │            Pin 1 B0505S (+Vin)
                      [100nF]
                        │
   GND_ESP      ────────┴──────────── Pin 5 (GND 6N137)
                                      Pin 2 B0505S (-Vin)

=================== BARRERA DE AISLAMIENTO GALVÁNICO ===================
                    (Separación física en placa >= 4mm)

==================== DOMINIO 2: RS485 / PLC S7-200 ====================
 [Convertidor Aislado B0505S-1W]
   Pin 4 (-Vout) ──> GND_AISLADO
   Pin 6 (+Vout) ──> +5V_AISLADO

 [U1 - A2631 (TX y RTS/DE)]
   Pin 5 ──> GND_AISLADO
   Pin 8 ──> +5V_AISLADO (con 100nF a Pin 5)
   Pin 7 (VO1: TX)  ──┬──> MAX485 Pin 4 (DI)
                    [1 kΩ]
                      └──> +5V_AISLADO
   Pin 6 (VO2: RTS) ──┬──> MAX485 Pin 2 (/RE) y Pin 3 (DE) unidos
                    [1 kΩ]
                      └──> +5V_AISLADO

 [U2 - 6N137 (RX)]
   Pin 3 ──> GND_AISLADO
   Pin 2 ──[ 470 Ω ]<── MAX485 Pin 1 (RO)

 [MAX485 & Red RS485]
   Pin 5 (GND) ──> GND_AISLADO
   Pin 8 (VCC) ──> +5V_AISLADO (con 100nF a Pin 5)
   
   Pin 6 (A) ──┬──[ 4.7 kΩ Pull-Up ]──> +5V_AISLADO
               ├──[ 120 Ω Terminación opcional ]──┐
               └──> Borne A / Pin 8 DB9 (PLC PPI) │
                                                  │
   Pin 7 (B) ──┬──────────────────────────────────┘
               ├──[ 4.7 kΩ Pull-Down ]──> GND_AISLADO
               └──> Borne B / Pin 3 DB9 (PLC PPI)
```

---

### E. BOM Exhaustiva de Materiales

| Cant. | Componente | Encapsulado | Función y Destino |
|:---:|---|:---:|---|
| **1** | **A2631 / HCPL-2631** | DIP-8 | Optoacoplador doble 10 MBd (U1: Canal 1=TX, Canal 2=RTS) |
| **1** | **6N137** | DIP-8 | Optoacoplador simple 10 MBd (U2: RX) |
| **1** | **MAX485** | DIP-8 | Transceptor diferencial RS485 |
| **1** | **B0505S-1W** | SIP-4 | Fuente conmutada aislada galvánica 5V/5V 200mA |
| **3** | **Zócalos DIP-8** | DIP-8 | Para A2631, 6N137 y MAX485 |
| **2** | **Resistores 330 Ω** | $1/4\text{W}$ | Limitación corriente LEDs A2631 (TX y RTS) |
| **1** | **Resistor 470 Ω** | $1/4\text{W}$ | Limitación corriente LED 6N137 (RX desde RO) |
| **3** | **Resistores 1 kΩ** | $1/4\text{W}$ | Pull-Up de salidas VO (2× a +5V_ISO, 1× a +3.3V_ESP) |
| **2** | **Resistores 4.7 kΩ** | $1/4\text{W}$ | Failsafe del bus RS485 (Pull-Up en A, Pull-Down en B) |
| **1** | **Resistor 120 Ω** | $1/4\text{W}$ | Terminación diferencial del bus RS485 (con jumper) |
| **3** | **Capacitores 100 nF (104)**| Cerámico | Desacoplo HF para A2631, 6N137 y MAX485 |
| **2** | **Capacitores 10 µF** | $\ge 16\text{V}$ | Filtro rizado en entrada y salida del B0505S |
| **1** | **Bornera clema 3 pines** | 5.08 mm | Salida de bus físico: A, B y Blindaje |
| **1** | **Conector DB9 macho** | Chasis | Conexión directa a puerto PPI de S7-200 (Pin 3=B, 8=A, 5=GND_ISO) |

---

### F. Protocolo de Verificación con Multímetro (Pre-Flight Check)

Antes de energizar el ESP32 o conectar el PLC Siemens S7-200:

1. **Test de Aislamiento Galvánico (Multímetro en continuidad/resistencia $\text{M}\Omega$):**
   - Medir entre `GND_ESP` y `GND_AISLADO`. **Debe marcar circuito abierto (OL / infinito).**
   - Medir entre `+5V_ESP` y `+5V_AISLADO`. **Debe marcar circuito abierto (OL / infinito).**
2. **Test de Tensión en Reposo (Alimentando solo ESP32 por USB):**
   - Verificar $+5\text{V} \pm 0.25\text{V}$ en la salida del B0505S (lado aislado).
   - Verificar con el multímetro en `GPIO 2`: debe medir **$+3.3\text{V}$** (vía Pull-Up de U3). **Nunca debe medir 5V.**
   - Verificar entre líneas A y B del MAX485: la línea A debe estar ligeramente más alta que la línea B ($V_A - V_B \approx +0.1\text{V}$ a $+0.3\text{V}$) gracias a las resistencias failsafe de 4.7 kΩ.
3. **Comprobación de pines DE/RE en Reposo:**
   - En reposo, los pines 2 y 3 del MAX485 deben medir $\approx 0\text{V}$ (modo escucha/recepción activado, LED de U2 encendido jalando a GND).

---

## 13. Fase USB Host VCP + Enlace Inalámbrico (v6 - Módulo FT232R)

> **Fecha:** 2026-10-31  
> **Objetivo:** Conexión del ESP32-S3 al módulo FTDI FT232RL existente mediante USB Host y puente inalámbrico Bluetooth LE (BLE UART) hacia la laptop.

### A. Diagnóstico Físico y Eléctrico de VBUS en DevKits ESP32-S3
1. **Diodos de Bloqueo Inverso (D1 y D7 - 1N5819):**
   - En las placas de desarrollo ESP32-S3 (DevKitC-1 y similares), los puertos Type-C están diseñados como receptores de energía (Sink/Device).
   - Los diodos Schottky impiden que el voltaje de 5V de la placa salga por el conector Type-C hacia periféricos externos.
   - Consecuencia: Al conectar el módulo FTDI directamente al puerto USB OTG del ESP32, el módulo recibe **0V** y permanece apagado (`D+ (GPIO 20) = 0`).

2. **Solución Hardware Validada (Placa Adaptadora USB Tipo C Hembra a DIP):**
   - Para alimentar el módulo FTDI sin depender del conector con diodo de la placa:
     - **V (+5V USB):** Conectar al pin **`5V` (o `VCC`)** de la tarjeta de expansión.
     - **G (GND USB):** Conectar a **`GND`** de la tarjeta de expansión.
     - **D- (USB Data -):** Conectar al pin **`GPIO 19`** del ESP32-S3.
     - **D+ (USB Data +):** Conectar al pin **`GPIO 20`** del ESP32-S3.

### B. Estado del Firmware v6 (`main/main.cpp`)
- **Controlador USB Host VCP:** Utiliza los componentes oficiales de Espressif `usb_host_vcp` y `usb_host_ftdi_vcp` v2.
- **Configuración Serial:** 9600 baudios, 8E1 (8 bits, Paridad Par, 1 Stop bit) para el protocolo Siemens PPI.
- **Consola:** Redirigida a UART0 (`/dev/ttyACM0` - CH343) a 115200 baudios para diagnóstico sin interferir con USB Host.
- **LED NeoPixel (GPIO 48):**
  - Amarillo = Buscando FTDI / Esperando conexión USB.
  - Verde = FTDI enumerado y operativo.
  - Azul = Transmitiendo al PLC.
  - Rojo = Recibiendo datos del PLC.
- **Backup de versión GPIO:** El firmware previo basado en UART1 por pines físicos está respaldado en `main/main_v5_gpio_backup.c`.

### C. Enlace Inalámbrico BLE 100% Operativo (v6 Definitivo)
- **Pila Bluetooth:** Espressif NimBLE integrada en firmware ESP-IDF v5.3.1.
- **Perfil GATT:** Nordic UART Service (NUS) estándar:
  - Dispositivo anunciado: **`S7-200-PPI-BLE`** (MAC: `28:84:85:91:45:06`)
  - Servicio UUID: `6E400001-B5A3-F393-E0A9-E50E24DCCA9E`
  - Característica RX (Laptop -> PLC): `6E400002-B5A3-F393-E0A9-E50E24DCCA9E` (Write without response)
  - Característica TX (PLC -> Laptop): `6E400003-B5A3-F393-E0A9-E50E24DCCA9E` (Notify)
- **Código en ESP32:** [`main/main.cpp`](file:///home/gus05/esp/ppi_bridge/main/main.cpp).
- **Herramientas de Control Directo por Bluetooth en Linux:**
  - Control de Estado / RUN / STOP / Monitor E/S: [`/home/gus05/open-ppi-bridge/scripts/ble_plc_control.py`](file:///home/gus05/open-ppi-bridge/scripts/ble_plc_control.py)
    - `python3 ble_plc_control.py status`: Muestra estado operativo (RUN/STOP), selector físico de la CPU, y mapa visual de todas las entradas digitales (I0.0..I1.5) y salidas digitales (Q0.0..Q1.1).
    - `python3 ble_plc_control.py status --watch`: Monitor continuo en tiempo real (dashboard de E/S).
    - `python3 ble_plc_control.py run`: Pone la CPU en modo RUN mediante telegrama nativo S7comm `0x28` (`P_PROGRAM`).
    - `python3 ble_plc_control.py stop`: Detiene la CPU (STOP) mediante telegrama nativo S7comm `0x29` (`P_PROGRAM`).
  - Escáner de Estaciones Inalámbrico: [`/home/gus05/open-ppi-bridge/scripts/ble_scan_ppi.py`](file:///home/gus05/open-ppi-bridge/scripts/ble_scan_ppi.py)
    - `python3 ble_scan_ppi.py`: Barrido automático de estaciones en el bus RS485 por Bluetooth sin requerir puertos virtuales.
- **Puente Serial Virtual en Laptop (Linux PTY):**
  - Script: [`/home/gus05/open-ppi-bridge/scripts/ble_serial_bridge.py`](file:///home/gus05/open-ppi-bridge/scripts/ble_serial_bridge.py)
  - Crea el puerto `/tmp/ttyPPI` para vincular cualquier software serie clásico de Linux.
- **Integración Transparente con Windows 7 y Micro/WIN (Alias `win7`):**
  - Script maestro de arranque: [`/home/gus05/VMs/windows7/start-win7.sh`](file:///home/gus05/VMs/windows7/start-win7.sh)
  - **Detección inteligente de 3 niveles al ejecutar `win7`:**
    1. Si hay cable USB conectado con FTDI (`0403:6001`) $\rightarrow$ usa `/dev/ttyUSB0`.
    2. Si hay cable USB conectado con CH343 (`1a86:55d3`) $\rightarrow$ usa `/dev/ttyACM0`.
    3. Si **no hay cables USB** $\rightarrow$ activa automáticamente el enlace inalámbrico Bluetooth (`S7-200-PPI-BLE`), crea `/tmp/ttyPPI` y lo entrega a Windows 7 como hardware serial **`COM1`** a través de QEMU.
  - El proxy inteligente [`ppi_proxy.py`](file:///home/gus05/rs485_ft232rl/scripts/ppi_proxy.py) opera de forma automática entre el canal serie y QEMU, filtrando en tiempo real las solicitudes de 960B para proteger la CPU 214.
  - Al cerrar la VM de Windows 7, el script apaga el enlace BLE y limpia los archivos temporales automáticamente.
- **Código de Colores NeoPixel (GPIO 48):**
  - **Amarillo:** Esperando módulo FTDI en USB-C hembra.
  - **Cian:** FTDI listo y operativo, esperando cliente BLE.
  - **Verde:** FTDI y Laptop BLE conectados y listos.
  - **Azul (destello):** Tráfico enviado hacia el PLC (TX).
  - **Rojo (destello):** Respuesta recibida desde el PLC (RX).

---

### D. Política de Versiones y Despliegue (Estado Actual)
> [!IMPORTANT]
> **Fase de Validación Local (Pre-Despliegue a GitHub):**  
> Todo el desarrollo, scripts auxiliares (`ble_plc_control.py`, `ble_scan_ppi.py`, `ble_serial_bridge.py`), firmware v6 y modificaciones en `start-win7.sh` y `ppi_proxy.py` se mantienen **estrictamente locales en la máquina de desarrollo**.  
> **NO se realizará ningún `git push` a GitHub** hasta que se ejecute la prueba de campo final con el autómata físico Siemens S7-200 (CPU 214) conectado al módulo FTDI en el taller/oficina.

---

### E. Protocolo de Prueba de Campo en Oficina (Checklist con PLC S7-200)

Cuando estés en la oficina frente al PLC físico:

1. **Conexión Eléctrica:**
   - Conectar la placa ESP32-S3 a un cargador de 5V o banco de energía (o puerto USB de la laptop para alimentarla).
   - El módulo FTDI debe estar conectado a la placa hembra USB-C (`V` a 5V, `G` a GND, `D-` a GPIO19, `D+` a GPIO20).
   - El conector DB9 del módulo FTDI conectado al puerto PPI de la CPU 214 (Pin 3=B, Pin 8=A, Pin 5=GND).
   - **Verificación LED ESP32:** Debe ponerse en **Cian** (FTDI detectado y enumerado por USB Host).
2. **Selector Físico de la CPU:**
   - Asegurarse de que el switch de palanca de la CPU esté en el centro: **`TERM`** (permite control por software).
3. **Prueba 1: Escaneo Inalámbrico de Estación:**
   ```bash
   python3 /home/gus05/open-ppi-bridge/scripts/ble_scan_ppi.py --max-addr 8
   ```
   *Debe responder:* `[+] ¡ESTACIÓN ENCONTRADA! Dirección: 2`.
4. **Prueba 2: Lectura Integral de Estado y E/S:**
   ```bash
   python3 /home/gus05/open-ppi-bridge/scripts/ble_plc_control.py status
   ```
   *Debe mostrar:* Estado RUN/STOP, posición del switch, estado de entradas I0.0..I1.5 y salidas Q0.0..Q1.1.
5. **Prueba 3: Control Operativo RUN / STOP:**
   ```bash
   python3 /home/gus05/open-ppi-bridge/scripts/ble_plc_control.py stop
   python3 /home/gus05/open-ppi-bridge/scripts/ble_plc_control.py run
   ```
   *Verificar:* El LED frontal "RUN" del PLC Siemens se apaga en STOP y se enciende en RUN.
6. **Prueba 4: Conexión con STEP 7-Micro/WIN (Windows 7):**
   ```bash
   win7
   ```
   * En Micro/WIN: Doble clic en *Comunicación* $\rightarrow$ *Doble clic para actualizar*.
   * La CPU 214 debe aparecer en pantalla y permitir subir/descargar bloques de programa de forma 100% inalámbrica.

---

## 13. Validación en Campo (Oficina) — Superada con Éxito (2026-11-02)

* **Enlace físico:** ESP32-S3 alimentado a 5V con placa hembra USB-C y FTDI FT232RL enumerado (LED Cian).
* **Escaneo PPI:** Estación 2 detectada inmediatamente vía BLE.
* **Control RUN/STOP:** Comprobado físicamente con palanca en `TERM`.
* **Compatibilidad Micro/WIN:** Validada al 100% inalámbricamente a través del puente serial virtual BLE.
* **App Móvil HMI (Flutter):** Monitoreo continuo a 1.2s de entradas, salidas y potenciómetros analógicos funcionando en Android.
* **Repositorio GitHub sincronizado:** `open-ppi-bridge` actualizado en rama `main`.




