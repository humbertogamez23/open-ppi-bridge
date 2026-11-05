---
name: Reporte de Error (Bug Report)
about: Reportar un comportamiento inesperado o fallo de comunicación
title: "[BUG]: "
labels: ["bug"]
assignees: ""
---

**Descripción del Error**
Una descripción clara y concisa de lo que ocurrió.

**Hardware Utilizado**
- **Modelo de PLC:** [Ej: Siemens S7-200 CPU 214 Rel 00.91]
- **Dirección PPI del PLC:** [Por defecto: 2]
- **Adaptador de Comunicación:** [Ej: FTDI FT232RL USB-RS485 / CH340 / ESP32-S3 BLE]
- **Sistema Operativo:** [Ej: Ubuntu 24.04 LTS / Debian 12 / Arch Linux]

**Pasos para Reproducir**
1. Ejecutar el comando `python3 scripts/...`
2. Parámetros enviados: `...`
3. Ver el error en terminal o desconexión.

**Comportamiento Esperado**
Descripción de lo que debería haber sucedido (ej. lectura exitosa de entradas o cambio de modo a RUN).

**Trazas de Log o Captura**
Pega aquí las trazas de consola relevantes o el contenido de `ble_bridge.log` / `proxy.log`:
```text
(pegar log aquí)
```

**Contexto Adicional**
Cualquier otro detalle sobre la instalación eléctrica, resistencias de terminación RS-485 o switches físicos de la CPU.
