import 'package:flutter/material.dart';

class PlcState extends ChangeNotifier {
  bool isConnected = false;
  String deviceName = "Desconectado";
  String deviceMac = "";
  int rssi = 0;

  // Estado operativo hardware CPU S7-200
  String cpuMode = "DESCONOCIDO"; // "RUN", "STOP", "ERROR"
  String keyPosition = "DESCONOCIDO"; // "RUN", "TERM", "STOP"

  // 14 Entradas Digitales (I0.0 .. I1.5)
  List<bool> inputs = List.generate(14, (_) => false);

  // 10 Salidas Digitales (Q0.0 .. Q1.1)
  List<bool> outputs = List.generate(10, (_) => false);

  // Marcas de control de proceso (MB0: M0.0 = Marcha, M0.1 = Post-purga)
  int mb0 = 0;
  bool get m0_0 => (mb0 & 0x01) != 0; // Marcha activa
  bool get m0_1 => (mb0 & 0x02) != 0; // Post-purga activa (T101 en curso)

  // Potenciómetros analógicos internos (SMB28, SMB29)
  int pot0 = 0;
  int pot1 = 0;

  bool isPolling = false;
  DateTime? lastUpdate;

  // Registro de depuración en vivo
  final List<String> logs = [];

  // --- Helpers de Estado de Proceso (Quemador y Secuencia Industrial) ---

  String get machineStatusTitle {
    if (!isConnected) return "DESCONECTADO";
    if (cpuMode == "STOP") return "CPU EN STOP";
    if (m0_1) return "POST-PURGA DE SEGURIDAD";
    if (outputs.length > 4 && outputs[4]) return "COMBUSTIÓN ACTIVA";
    if (outputs.length > 2 && outputs[0] && outputs[2]) return "EN RÉGIMEN (DELTA)";
    if (outputs.length > 1 && outputs[0] && outputs[1]) return "ARRANQUE (ESTRELLA)";
    if (outputs.isNotEmpty && outputs[0]) return "TRANSICIÓN MOTOR";
    if (m0_0) return "CICLO ACTIVO";
    return "DETENIDO / EN REPOSO";
  }

  String get machineStatusSubtitle {
    if (!isConnected) return "Sin enlace BLE con el puente S7-200";
    if (cpuMode == "STOP") return "Ciclo de scan detenido por software";
    if (m0_1) return "Quemador apagado | Ventilador barriendo gases (30 s)";
    if (outputs.length > 4 && outputs[4]) return "Quemador Honeywell encendido (Q0.4 activo)";
    if (outputs.length > 2 && outputs[0] && outputs[2]) return "Soplador en velocidad nominal Delta (Q0.0 + Q0.2)";
    if (outputs.length > 1 && outputs[0] && outputs[1]) return "Acelerando soplador en Estrella (Q0.0 + Q0.1)";
    if (outputs.isNotEmpty && outputs[0]) return "Pausa de transición Estrella -> Delta (T33)";
    return "Contactores y quemador desenergizados";
  }

  Color get machineStatusColor {
    if (!isConnected) return Colors.grey;
    if (cpuMode == "STOP") return Colors.redAccent;
    if (m0_1) return Colors.cyanAccent;
    if (outputs.length > 4 && outputs[4]) return const Color(0xFFFF9100); // Llama naranja
    if (outputs.length > 2 && outputs[0] && outputs[2]) return Colors.greenAccent;
    if (outputs.length > 1 && outputs[0] && outputs[1]) return Colors.amberAccent;
    return const Color(0xFF90A4AE); // Gris azulado en reposo
  }

  IconData get machineStatusIcon {
    if (!isConnected) return Icons.bluetooth_disabled_rounded;
    if (cpuMode == "STOP") return Icons.pause_circle_filled_rounded;
    if (m0_1) return Icons.air_rounded; // Ventilador purga
    if (outputs.length > 4 && outputs[4]) return Icons.local_fire_department_rounded; // Fuego
    if (outputs.length > 2 && outputs[0] && outputs[2]) return Icons.speed_rounded; // Delta
    if (outputs.length > 1 && outputs[0] && outputs[1]) return Icons.play_arrow_rounded; // Estrella
    return Icons.power_settings_new_rounded; // Detenido
  }

  void addLog(String msg) {
    final now = DateTime.now();
    final timeStr = "${now.hour.toString().padLeft(2, '0')}:${now.minute.toString().padLeft(2, '0')}:${now.second.toString().padLeft(2, '0')}";
    debugPrint("[HMI] $msg");
    logs.insert(0, "[$timeStr] $msg");
    if (logs.length > 60) logs.removeLast();
    notifyListeners();
  }

  void clearLogs() {
    logs.clear();
    notifyListeners();
  }

  void updateConnection({required bool connected, String? name, String? mac, int? newRssi}) {
    isConnected = connected;
    if (name != null) deviceName = name;
    if (mac != null) deviceMac = mac;
    if (newRssi != null) rssi = newRssi;
    notifyListeners();
  }

  void updateStatus({
    required String mode,
    required String key,
    required List<bool> newInputs,
    required List<bool> newOutputs,
    required int p0,
    required int p1,
    int newMb0 = 0,
  }) {
    cpuMode = mode;
    keyPosition = key;
    inputs = newInputs;
    outputs = newOutputs;
    pot0 = p0;
    pot1 = p1;
    mb0 = newMb0;
    lastUpdate = DateTime.now();
    notifyListeners();
  }

  void setPolling(bool val) {
    isPolling = val;
    notifyListeners();
  }
}
