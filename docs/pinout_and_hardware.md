# Hardware Pinout, Wiring & Serial Interface Guide

This document describes the complete physical and electrical interface required to communicate with a **Siemens SIMATIC S7-200 (CPU 214 Rel 00.91 / CPU 22x)** PLC, either via:
1. **Wireless Bluetooth LE Bridge:** ESP32-S3 acting as a Native USB Host connected to a generic USB-to-RS485 adapter.
2. **Direct Wired USB-to-RS485:** Standard FTDI / CH340 / CP2102 adapter plugged directly into a Linux host.

---

## 1. Siemens S7-200 Port 0 / Port 1 Pinout (DB9 Female)

The RS-485 interface on the front face of the S7-200 PLC uses a standard DB9 female socket.

| S7-200 DB9 Pin | Signal Name | Adapter Pin (FTDI / MAX485) | Description |
| :---: | :---: | :---: | :--- |
| **Pin 3** | **RS-485 B (RxD/TxD+)** | **A+ / D+** | Non-inverting differential data signal |
| **Pin 8** | **RS-485 A (RxD/TxD-)** | **B- / D-** | Inverting differential data signal |
| **Pin 5** | **GND (Masa lógica)** | **GND** | Essential signal ground reference |
| *Pin 2* | *24V DC Return* | *Do not connect* | Internal logic ground (isolated) |
| *Pin 7* | *+24V DC Out* | *Do not connect* | Auxiliary power output (max 120 mA) |

> [!CAUTION]
> **Signal Ground (Pin 5) is Mandatory:**  
> Never leave Pin 5 disconnected. Without a common ground reference between the adapter/ESP32 and the PLC, common-mode voltage fluctuations will saturate the differential receiver, causing silent packet loss and framing errors.

> [!NOTE]
> **Siemens Inverted Nomenclature Note:**  
> Siemens S7-200 manuals label Pin 3 as "RS-485 B" (Data +) and Pin 8 as "RS-485 A" (Data -). Standard RS-485 transceivers (MAX485, SN75176) label Data+ as "A" and Data- as "B". Wire as listed in the table above:
> - **S7-200 Pin 3** $\rightarrow$ **Adapter A+**
> - **S7-200 Pin 8** $\rightarrow$ **Adapter B-**

---

## 2. Wireless BLE Bridge: ESP32-S3 (USB Host) Setup

The ESP32-S3 firmware in [`firmware/esp32_s3`](file:///home/gus05/open-ppi-bridge/firmware/esp32_s3) uses the ESP32-S3's hardware USB OTG peripheral to operate in **USB Host mode**, talking directly to generic USB-to-RS485 dongles (FTDI FT232RL, CH340, CP2102) over the Virtual COM Port (VCP) driver.

```
┌──────────────────────────────────────┐          ┌───────────────────────┐          ┌─────────────────────────┐
│        ESP32-S3 (USB Host)           │          │ Generic USB-to-RS485  │          │  Siemens SIMATIC S7-200 │
│                                      │          │ (FTDI / CH340 Dongle) │          │     (DB9 Female Port)   │
│  [5V / VBUS]  ───────────────────────┼──────────┤ VCC (+5V)             │          │                         │
│  [GND]        ───────────────────────┼────┬─────┤ GND                   ├──────────┤ Pin 5 (Logic GND)       │
│  [GPIO 19]    ─── (USB D-) ──────────┼────┼─────┤ D- (White Wire)       │          │                         │
│  [GPIO 20]    ─── (USB D+) ──────────┼────┼─────┤ D+ (Green Wire)       │          │                         │
│                                      │    │     │ A+ / D+ ──────────────┼──────────┤ Pin 3 (RS-485 Data + / B│
│  [BLE Radio]  ◄··· Wireless NUS ···► │    │     │ B- / D- ──────────────┼──────────┤ Pin 8 (RS-485 Data - / A│
└──────────────────────────────────────┘    │     └───────────────────────┘          └─────────────────────────┘
                                            └─────────────────────────────────────────────────┘ (Mandatory Common GND)
```

### Physical Connection Options

#### A. Plug-and-Play USB-C OTG (No Soldering Required)
Many ESP32-S3 dual-port boards (such as the *ESP32-S3-DevKitC-1*) feature two USB-C connectors:
1. `UART` (CH343/CP2102 port for serial console and flashing).
2. `USB` (Native USB OTG connected directly to internal D-/D+ transceivers).

Simply attach a standard **USB-C Male to USB-A Female OTG adapter** to the `USB` port, and plug your commercial USB-to-RS485 dongle into it.

#### B. Header Pin Wiring (GPIO 19 / 20)
If wiring a female USB-A socket directly or using an expansion board:

| ESP32-S3 Pin | USB-A Female Socket Pin | Standard Wire Color | Purpose |
| :--- | :---: | :---: | :--- |
| **5V / VBUS / VIN** | **Pin 1 (VCC)** | Red | +5V DC power to the USB-RS485 dongle |
| **GPIO 19 (USB D-)**| **Pin 2 (D-)** | White | Native USB differential data minus |
| **GPIO 20 (USB D+)**| **Pin 3 (D+)** | Green | Native USB differential data plus |
| **GND** | **Pin 4 (GND)** | Black | Common Ground |

> [!TIP]
> **Expansion Boards:**  
> Using an ESP32 terminal expansion board (breakout board) makes bench testing easy by offering screw terminals for 5V, GND, GPIO 19, and GPIO 20. However, **an expansion board is NOT required**; you can connect jumper wires directly to the standard ESP32-S3 header pins or use a breadboard.

---

## 3. RS-485 Transceiver to S7-200 DB9 Wiring

Whether using the ESP32-S3 bridge or a direct USB-to-RS485 adapter on a PC:

| RS-485 Adapter Terminal | S7-200 DB9 Pin | Signal Name |
| :--- | :---: | :--- |
| **A+ (D+)** | **Pin 3** | RS-485 B (RxD/TxD+) |
| **B- (D-)** | **Pin 8** | RS-485 A (RxD/TxD-) |
| **GND** | **Pin 5** | Signal Ground Reference (Mandatory) |

---

## 4. Port Configuration & Parameters

The factory-default communications profile for S7-200 PLCs (Port 0):

* **Baudrate:** `9600 bps` (Default; some CPU 22x models can be configured to 19200 or 187500 bps)
* **Data Bits:** `8`
* **Parity:** `Even` (`E`)
* **Stop Bits:** `1`
* **Flow Control:** `None` (Half-Duplex RS-485)
* **Default PLC Address:** `2`
* **Default Master (PC) Address:** `0`

---

## 3. FTDI Latency Timer Configuration (Critical)

Standard USB-serial drivers buffer incoming bytes for up to 16 milliseconds before releasing them to user space. Because the S7-200 CPU 214 operates on strict PROFIBUS timing (requiring responses within 35 ms), the FTDI latency timer **must be set to 1 millisecond**.

### Setting Latency in Linux

Execute with root privileges:

```bash
# 1. Using setserial
sudo setserial /dev/ttyUSB0 low_latency

# 2. Directly via sysfs (FTDI specific)
echo 1 | sudo tee /sys/bus/usb-serial/devices/ttyUSB0/latency_timer

# Verify the setting:
cat /sys/bus/usb-serial/devices/ttyUSB0/latency_timer
# Output must be: 1
```

### FTDI Hardware Direction Control (TXDEN)
For generic FTDI FT232RL boards connected to an external MAX485 chip:
* Ensure `CBUS2` is configured as `TXDEN` using `ftdi_eeprom` or FT_Prog. This toggles the RS-485 transceiver driver-enable pin automatically on transmit, eliminating collisions.

---

## 4. Front Panel Mode Switch

The S7-200 features a three-position mechanical switch:

1. **RUN:** Executes the user program.
2. **TERM (Terminal):** Allows remote software (Micro/WIN or `plc_control.py`) to transition the PLC between RUN and STOP modes. **(Recommended default setting)**.
3. **STOP:** Halts program execution. **Mandatory during initial program block download.**
