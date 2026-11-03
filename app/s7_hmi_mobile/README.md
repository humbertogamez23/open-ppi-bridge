# Siemens S7-200 Mobile HMI (Flutter + BLE)

Aplicación móvil Android para **Control, Diagnóstico y Monitoreo en Tiempo Real** de autómatas programables **Siemens SIMATIC S7-200 (CPU 214)** mediante conexión inalámbrica Bluetooth Low Energy (BLE) con el puente **ESP32-S3 (`open-ppi-bridge`)**.

---

## 🚀 Características Principales

* **Monitoreo de E/S Digitales en Tiempo Real:**
  - **14 Entradas Digitales:** Indicadores LED de alta visibilidad para `$I0.0 \dots I0.7$` y `$I1.0 \dots I1.5$`.
  - **10 Salidas Digitales:** Indicadores ámbar para `$Q0.0 \dots Q0.7$` y `$Q1.0 \dots Q1.1$`.
* **Control de Marcha/Parada:** Conmutación remota segura entre modos **RUN** y **STOP** con diálogo de confirmación industrial.
* **Potenciómetros Analógicos Integrados:** Barras de nivel en vivo para `$SMB28$` (Pot 0) y `$SMB29$` (Pot 1).
* **Modo Polling Continuo:** Refresco en segundo plano cada 400 ms.
* **Enlace Nórdic UART Service (NUS):** Comunicación directa con el ESP32-S3 usando tramas nativas PPI/S7comm.

---

## 🛠️ Requisitos de Compilación

1. **Flutter SDK:** Versión 3.0.0 o superior.
2. **Android SDK:** Con soporte para API 21 a API 34.
3. **Java:** OpenJDK 17.

---

## 📦 Cómo Compilar el APK

1. Entra a la carpeta de la app:
   ```bash
   cd open-ppi-bridge/app/s7_hmi_mobile
   ```

2. Descarga las dependencias:
   ```bash
   flutter pub get
   ```

3. Compila el paquete de distribución para Android:
   ```bash
   flutter build apk --release
   ```

4. El archivo instalable quedará generado en:
   `build/app/outputs/flutter-apk/app-release.apk`
