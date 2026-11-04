import 'package:flutter/foundation.dart';

class PlcState extends ChangeNotifier {
  bool isConnected = false;
  String deviceName = "Desconectado";
  String deviceMac = "";
  int rssi = 0;

  // Estado operativo CPU
  String cpuMode = "DESCONOCIDO"; // "RUN", "STOP", "ERROR"
  String keyPosition = "DESCONOCIDO"; // "RUN", "TERM", "STOP"

  // 14 Entradas Digitales (I0.0 .. I1.5)
  List<bool> inputs = List.generate(14, (_) => false);

  // 10 Salidas Digitales (Q0.0 .. Q1.1)
  List<bool> outputs = List.generate(10, (_) => false);

  // Potenciómetros analógicos internos (SMB28, SMB29)
  int pot0 = 0;
  int pot1 = 0;

  bool isPolling = false;
  DateTime? lastUpdate;

  // Registro de depuración en vivo
  final List<String> logs = [];

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
  }) {
    cpuMode = mode;
    keyPosition = key;
    inputs = newInputs;
    outputs = newOutputs;
    pot0 = p0;
    pot1 = p1;
    lastUpdate = DateTime.now();
    notifyListeners();
  }

  void setPolling(bool val) {
    isPolling = val;
    notifyListeners();
  }
}
