---
name: Reporte de Compatibilidad de Hardware
about: Reportar resultados de pruebas con un modelo de PLC o adaptador específico
title: "[HARDWARE]: Pruebas en CPU "
labels: ["hardware-verified"]
assignees: ""
---

**Modelo de Autómata y Firmware**
- **CPU:** [Ej: CPU 212 / CPU 215 / CPU 222 / CPU 224 / CPU 226 / etc.]
- **Referencia Siemens:** [Ej: 6ES7 214-1AD23-0XB0]
- **Release de Firmware:** [Ej: Rel 01.10 / 02.00]

**Medio de Enlace**
- [ ] Adaptador USB-RS485 FTDI (FT232RL)
- [ ] Adaptador USB-RS485 CH340 / CP2102
- [ ] Módulo Inalámbrico ESP32-S3 BLE (`S7-200-PPI-BLE`)
- [ ] Otro: _____________

**Resultados de las Pruebas**
- [ ] Escaneo de bus (`scan_ppi.py`): [OK / Fallo]
- [ ] Cambio de modo RUN/STOP (`plc_control.py`): [OK / Fallo]
- [ ] Lectura de I/O (`read_io_ppi.py`): [OK / Fallo]
- [ ] Descarga con STEP 7-Micro/WIN vía `ppi_proxy.py`: [OK / Fallo / No probado]
- [ ] Flasheo directo nativo con `flash_s7_200.py`: [OK / Fallo / No probado]
- [ ] Conexión con app móvil Flutter (`s7_hmi_mobile`): [OK / Fallo / No probado]

**Notas y Observaciones**
Comenta si tuviste que ajustar baudrate, tiempos de respuesta o configuración de paridad.
