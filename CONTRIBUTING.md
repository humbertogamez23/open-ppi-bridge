# Guía de Contribución a open-ppi-bridge

¡Gracias por tu interés en contribuir a **open-ppi-bridge**! 🚀

Este proyecto busca democratizar la comunicación y el desarrollo sobre autómatas **Siemens SIMATIC S7-200**, pasarelas IIoT inalámbricas (ESP32-S3) e interfaces modernas de control (Flutter HMI).

---

## 🛠️ Formas de Contribuir

Puedes colaborar de muchas maneras:
1. **Reportes de Compatibilidad de Hardware:** Prueba las herramientas con diferentes modelos de CPU (CPU 212, 214, 215, 216, 221, 222, 224, 226) o diferentes versiones de firmware y comparte tus resultados.
2. **Reporte de Errores (Bugs):** Abre un Issue detallando trazas de logs, modelo de PLC y adaptador RS-485 utilizado.
3. **Mejoras en el Desensamblador/Ensamblador AWL (`scripts/s7_awl_asm.py`):** Agrega soporte para nuevas instrucciones y opcodes de Siemens S7-200.
4. **Mejoras en la App Móvil Flutter (`app/s7_hmi_mobile`):** Expande pantallas, añade widgets de instrumentación o mejora la gestión de conexiones BLE.
5. **Documentación:** Correcciones, traducciones o diagramas técnicos.

---

## 💻 Entorno de Desarrollo Local

### 1. Clonar el Repositorio
```bash
git clone https://github.com/humbertogamez23/open-ppi-bridge.git
cd open-ppi-bridge
```

### 2. Configurar Entorno Virtual de Python
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Ejecutar Pruebas sin Hardware Físico
Puedes validar cambios de protocolo o lógica de PLC sin tener un autómata físico conectado utilizando el simulador:
```bash
# Probar el simulador de ciclo de scan y lógica AWL
python3 scripts/simulador_awl.py

# Ejecutar suite de pruebas sintéticas
python3 scripts/test_ppi_suite.py

# Simulación de flasheo en modo dry-run
python3 scripts/flash_s7_200.py --dry-run --all
```

---

## ⚠️ Advertencia de Seguridad Industrial

Si estás probando herramientas de escritura (`plc_control.py`, `flash_s7_200.py`, o la app HMI) en un autómata físico conectado a maquinaria:
* **Desconecta o aísla siempre las salidas a actuadores críticos** (electroválvulas de gas, contactores de motores, resistencias calefactoras).
* Mantén accesible en todo momento un **pulsador de parada de emergencia electromecánica por corte físico de alimentación**.

---

## 🌿 Flujo de Trabajo con Git

1. Haz un fork del repositorio en GitHub.
2. Crea una rama descriptiva para tu cambio:
   ```bash
   git checkout -b feature/soporte-cpu224
   # o
   git checkout -b fix/timeout-ble-reconnect
   ```
3. Sigue el formato estándar de mensajes de commit ([Conventional Commits](https://www.conventionalcommits.org/)):
   * `feat: ...` para nuevas funcionalidades.
   * `fix: ...` para corrección de errores.
   * `docs: ...` para cambios en documentación.
   * `refactor: ...` para mejoras de código sin cambio de comportamiento.
4. Asegúrate de que el código no rompa compatibilidad con scripts existentes.
5. Envía tu **Pull Request** detallando los cambios y el hardware utilizado para pruebas.
