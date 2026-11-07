# 🖥️ Entorno Virtualizado Windows 7 / STEP 7-Micro/WIN (QEMU/KVM)

Este directorio contiene las herramientas para desplegar y ejecutar una máquina virtual optimizada de **Windows 7** en Linux (utilizando **QEMU y KVM**), diseñada específicamente para trabajar con **Siemens STEP 7-Micro/WIN v4.0 SP9** y comunicarse con autómatas **SIMATIC S7-200** (tanto vía cable USB-RS485 FTDI como de forma inalámbrica vía **Bluetooth LE**).

---

## 🌟 Características Principales

* **Filtro Inteligente Anti-960B Integrado (`ppi_proxy.py`):**
  Micro/WIN solicita transferencias en bloques de 960 bytes por defecto, lo que bloquea y cuelga de forma fatal a las CPU de la serie 21x (como la **CPU 214**). El lanzador activa automáticamente nuestro proxy intermediario en el puerto virtual **COM1**, reescribiendo las peticiones a fragmentos seguros de 240 bytes.
* **Soporte Cableado e Inalámbrico (BLE):**
  Funciona tanto con transceptores cableados FTDI FT232RL / CH343 como con el puente inalámbrico Bluetooth LE (`--ble`).
* **Mouse Fluido sin Bloqueo (`usb-tablet`):**
  El cursor entra y sale de la máquina virtual sin atrapar el ratón del sistema anfitrión.
* **Puente de Transferencia Web Integrado (`scripts/web_transfer.py`):**
  Servidor HTTP local accesible desde Windows 7 en `http://10.0.2.2:8000` para descargar o subir archivos de proyecto (`.mwp`) y programas (`.awl`) directamente a la carpeta `vm/shared/` del host.

---

## 📋 Requisitos Previos

1. **Sistema Operativo Host:** Linux x86_64 con soporte de virtualización por hardware (**KVM** habilitado en BIOS/UEFI).
2. **Imagen ISO de Windows 7:** Se recomienda **Windows 7 Professional de 32 bits** (x86), que ofrece la máxima estabilidad y compatibilidad con drivers de Siemens STEP 7-Micro/WIN v4.0 SP9.

---

## 🚀 Puesta en Marcha Rápida (1 Comando)

Para configurar todo el entorno desde cero (disco virtual, dependencias, permisos y arranque de instalación), ejecuta:

```bash
bash vm/setup_win7_vm.sh
```

O especificando directamente la ruta hacia tu imagen ISO:

```bash
bash vm/setup_win7_vm.sh /ruta/a/tu_windows7.iso
```

El asistente se encargará de:
1. Comprobar que QEMU y KVM estén instalados en tu distribución.
2. Configurar los permisos de usuario (`kvm`, `dialout`).
3. Crear el disco virtual dinámico de 30GB en `vm/disks/win7.qcow2`.
4. Iniciar la máquina virtual con el instalador de Windows 7 montado.

> **Durante la instalación:** Sigue el asistente gráfico habitual de Windows en la ventana de QEMU. Una vez instalado Windows 7 y tras llegar al escritorio, puedes apagar la máquina virtual.

---

## 🔄 Uso Diario (`run_win7_vm.sh`)

Una vez instalado Windows 7, arranca tu entorno con el script de producción:

### Conexión Cableada (USB-RS485 FTDI / CH343)
Conecta tu cable al puerto USB y ejecuta:
```bash
bash vm/run_win7_vm.sh
```
*El script detectará el puerto serie (ej. `/dev/ttyUSB0`), configurará la latencia a 1 ms, iniciará el proxy PPI y enlazará COM1 con `/tmp/qemu_serial.sock`.*

### Conexión Inalámbrica (Bluetooth LE al ESP32)
Para programar el PLC sin cables mediante el firmware del ESP32-S3:
```bash
bash vm/run_win7_vm.sh --ble
```

### Opciones Disponibles
```bash
bash vm/run_win7_vm.sh --help
```
* `--disk <ruta>`: Especifica una ruta personalizada para el disco `.qcow2`.
* `--ram <MB>`: Cantidad de memoria RAM asignada (por defecto: `2048`).
* `--smp <cores>`: Cantidad de núcleos asignados (por defecto: `2`).
* `--no-proxy`: Pasa el puerto serie directo sin el proxy intermediario.
* `--install <iso>`: Permite arrancar desde una ISO para reinstalaciones o mantenimiento.

---

## ⚙️ Configuración en STEP 7-Micro/WIN

Una vez dentro del escritorio de Windows 7 e instalado Micro/WIN:

1. Ve a **Ajustar interface PG/PC** (*Set PG/PC Interface*).
2. Selecciona el punto de acceso de la aplicación: `Micro/WIN -> PC/PPI cable (PPI)`.
3. Haz clic en **Propiedades**:
   * **Conexión local:** Selecciona `COM1`.
   * **Parámetros PPI:**
     * Velocidad de transferencia: `9600 bps` (o la configurada en tu CPU).
     * Dirección más alta: `31` o `126`.
     * **Modo Multi-Master:** `DESMARCADO` (Desactivado).
4. Guarda y ve a la ventana de **Comunicación** en Micro/WIN.
5. Haz doble clic en el icono **Doble clic para refrescar**:
   * Aparecerá tu estación PLC (ej. `Estación 2 - CPU 214` o `CPU 22x`).

---

## 📁 Transferencia de Archivos (Host &harr; VM)

No es necesario configurar carpetas compartidas complejas ni drivers de red adicionales:

1. El script inicia automáticamente el servidor local en `http://10.0.2.2:8000`.
2. En Windows 7, abre Internet Explorer o tu navegador y entra a:
   ```
   http://10.0.2.2:8000
   ```
3. Podrás:
   * **Descargar a Windows:** Cualquier archivo colocado en `vm/shared/` en el host (ej. instaladores, librerías, programas).
   * **Subir a Linux:** Exporta tu proyecto en Micro/WIN (**Archivo &rarr; Exportar &rarr; .awl**) y súbelo desde la página web para que esté disponible de inmediato en Linux para su análisis o auditoría con `ai_copilot.py`.
