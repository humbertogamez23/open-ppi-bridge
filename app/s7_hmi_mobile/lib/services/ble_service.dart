import 'dart:async';
import 'dart:io';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';
import '../models/plc_state.dart';
import 'ppi_protocol.dart';

class AsyncQueue<T> {
  final List<T> _queue = [];
  final List<Completer<T>> _waiting = [];

  void add(T item) {
    if (_waiting.isNotEmpty) {
      _waiting.removeAt(0).complete(item);
    } else {
      _queue.add(item);
    }
  }

  Future<T> get({Duration? timeout}) {
    if (_queue.isNotEmpty) {
      return Future.value(_queue.removeAt(0));
    }
    final completer = Completer<T>();
    _waiting.add(completer);
    if (timeout != null) {
      return completer.future.timeout(timeout, onTimeout: () {
        _waiting.remove(completer);
        throw TimeoutException("Queue get timed out after $timeout");
      });
    }
    return completer.future;
  }

  void clear() {
    _queue.clear();
    for (var c in _waiting) {
      if (!c.isCompleted) {
        c.completeError(Exception("Queue cleared"));
      }
    }
    _waiting.clear();
  }

  bool get isEmpty => _queue.isEmpty;
}

class BleService {
  static const String targetDeviceName = "S7-200-PPI-BLE";
  static final Guid rxUuid = Guid("6e400002-b5a3-f393-e0a9-e50e24dcca9e");
  static final Guid txUuid = Guid("6e400003-b5a3-f393-e0a9-e50e24dcca9e");

  BluetoothDevice? connectedDevice;
  BluetoothCharacteristic? rxChar;
  BluetoothCharacteristic? txChar;

  final AsyncQueue<List<int>> _rxQueue = AsyncQueue<List<int>>();
  StreamSubscription? _txSubscription;

  final PlcState state;
  Timer? _pollTimer;
  bool _isRefreshing = false;
  bool _busBusy = false;

  BleService(this.state);

  Future<T> _syncBus<T>(Future<T> Function() action) async {
    while (_busBusy) {
      await Future.delayed(const Duration(milliseconds: 20));
    }
    _busBusy = true;
    try {
      return await action();
    } finally {
      _busBusy = false;
    }
  }

  String _formatHex(List<int> bytes) {
    if (bytes.length > 12) {
      return "${bytes.take(8).map((b) => b.toRadixString(16).padLeft(2, '0').toUpperCase()).join(' ')} ... (${bytes.length}B)";
    }
    return bytes.map((b) => b.toRadixString(16).padLeft(2, '0').toUpperCase()).join(' ');
  }

  Future<void> startScanAndConnect() async {
    state.addLog("[BLE] Iniciando escaneo...");
    state.updateConnection(connected: false, name: "Escaneando...");

    try {
      await FlutterBluePlus.startScan(timeout: const Duration(seconds: 8));

      FlutterBluePlus.scanResults.listen((results) async {
        for (ScanResult r in results) {
          String name = r.device.platformName.isNotEmpty
              ? r.device.platformName
              : r.advertisementData.advName;
          if (name == targetDeviceName || r.device.remoteId.str == "28:84:85:91:45:06") {
            state.addLog("[BLE] Encontrado: $name (${r.device.remoteId.str})");
            await FlutterBluePlus.stopScan();
            await connectToDevice(r.device, r.rssi);
            break;
          }
        }
      });
    } catch (e) {
      state.addLog("[-] Error en escaneo: $e");
      state.updateConnection(connected: false, name: "Error al escanear");
    }
  }

  Future<void> connectToDevice(BluetoothDevice device, int rssi) async {
    state.addLog("[BLE] Conectando a ${device.remoteId.str}...");
    state.updateConnection(connected: false, name: "Conectando...");
    try {
      await device.connect(autoConnect: false, timeout: const Duration(seconds: 12));
      connectedDevice = device;
      state.addLog("[✓] BLE Conectado físicamente.");

      // En Android, negociar MTU alto para no truncar tramas de >20 bytes
      if (Platform.isAndroid) {
        try {
          int mtu = await device.requestMtu(256);
          state.addLog("[✓] MTU negociado: $mtu bytes");
        } catch (e) {
          state.addLog("[i] MTU standard: $e");
        }
      }

      state.addLog("[BLE] Descubriendo servicios GATT...");
      List<BluetoothService> services = await device.discoverServices();
      for (var s in services) {
        for (var c in s.characteristics) {
          String uuidStr = c.uuid.str128.toLowerCase();
          if (uuidStr == "6e400002-b5a3-f393-e0a9-e50e24dcca9e") rxChar = c;
          if (uuidStr == "6e400003-b5a3-f393-e0a9-e50e24dcca9e") txChar = c;
        }
      }

      if (rxChar != null && txChar != null) {
        state.addLog("[✓] Canal NUS RX/TX listo.");
        await txChar!.setNotifyValue(true);
        _txSubscription?.cancel();
        _rxQueue.clear();

        _txSubscription = txChar!.onValueReceived.listen((data) {
          if (data.isNotEmpty) {
            _rxQueue.add(data);
          }
        });

        state.updateConnection(
          connected: true,
          name: device.platformName.isNotEmpty ? device.platformName : targetDeviceName,
          mac: device.remoteId.str,
          newRssi: rssi,
        );

        // Primer refresco de datos
        await Future.delayed(const Duration(milliseconds: 250));
        await refreshPlcData();
      } else {
        state.addLog("[-] Error: Servicio NUS no encontrado en el ESP32");
        state.updateConnection(connected: false, name: "Servicios no encontrados");
      }
    } catch (e) {
      state.addLog("[-] Error al conectar BLE: $e");
      state.updateConnection(connected: false, name: "Error al conectar");
    }
  }

  Future<void> disconnect() async {
    _pollingActive = false;
    _pollTimer?.cancel();
    state.setPolling(false);
    _txSubscription?.cancel();
    _txSubscription = null;
    if (connectedDevice != null) {
      await connectedDevice!.disconnect();
      connectedDevice = null;
    }
    _rxQueue.clear();
    state.addLog("[BLE] Desconectado.");
    state.updateConnection(connected: false, name: "Desconectado");
  }

  /// Envía una solicitud S7 al PLC y espera la respuesta completa (Sincronizado en el bus)
  Future<List<int>?> sendS7Request(List<int> pduBody, {Duration timeout = const Duration(milliseconds: 2000)}) async {
    if (rxChar == null) return null;
    return _syncBus(() => _sendS7RequestInternal(pduBody, timeout: timeout));
  }

  Future<List<int>?> _sendS7RequestInternal(List<int> pduBody, {Duration timeout = const Duration(milliseconds: 2000)}) async {
    if (rxChar == null) return null;

    List<int> sd2Frame = PpiProtocol.buildSd2Frame(pduBody);
    List<int> pollFrame = PpiProtocol.buildPollSd1();

    // 1. Enviar trama SD2 y esperar ACK (0xE5)
    bool ack = false;
    for (int retry = 0; retry < 3; retry++) {
      _rxQueue.clear();
      state.addLog("[TX] SD2 (${sd2Frame.length}B): ${_formatHex(sd2Frame)}");
      await rxChar!.write(sd2Frame, withoutResponse: true);

      // Esperar ACK con timeout holgado de 400ms (BLE roundtrip toma ~180-220ms)
      DateTime ackDeadline = DateTime.now().add(const Duration(milliseconds: 400));
      while (DateTime.now().isBefore(ackDeadline)) {
        try {
          List<int> chunk = await _rxQueue.get(timeout: const Duration(milliseconds: 200));
          state.addLog("[RX] (${chunk.length}B): ${_formatHex(chunk)}");
          if (chunk.contains(0xE5)) {
            ack = true;
            break;
          }
        } catch (_) {}
      }
      if (ack) break;
      await Future.delayed(const Duration(milliseconds: 50));
    }

    if (!ack) {
      state.addLog("[-] Sin ACK (0xE5) del PLC tras reintentos");
      return null;
    }

    // Pausa de 40ms para que la CPU 214 prepare los datos
    await Future.delayed(const Duration(milliseconds: 40));

    // 2. Sondeo periódico SD1 esperando la respuesta SD2
    DateTime deadline = DateTime.now().add(timeout);
    List<int> accum = [];

    while (DateTime.now().isBefore(deadline)) {
      await rxChar!.write(pollFrame, withoutResponse: true);

      DateTime pollChunkDeadline = DateTime.now().add(const Duration(milliseconds: 200));
      while (DateTime.now().isBefore(pollChunkDeadline)) {
        try {
          List<int> chunk = await _rxQueue.get(timeout: const Duration(milliseconds: 150));
          state.addLog("[RX] (${chunk.length}B): ${_formatHex(chunk)}");
          for (int b in chunk) {
            if (b == 0xE5 && accum.isEmpty) continue;
            accum.add(b);
          }
          if (accum.length >= 6 && accum[0] == 0x68 && accum.last == 0x16 && accum.length >= (accum[1] + 6)) {
            return accum;
          }
        } catch (_) {}
      }
      await Future.delayed(const Duration(milliseconds: 35));
    }

    state.addLog("[-] Timeout en respuesta SD2");
    return null;
  }

  /// Lee un área de memoria específica
  Future<List<int>?> readMemoryArea(int areaCode, int startByte, int count) async {
    List<int> pdu = PpiProtocol.buildReadMemoryPdu(areaCode: areaCode, startByte: startByte, count: count);
    List<int>? rawFrame = await sendS7Request(pdu);
    if (rawFrame == null) return null;
    return PpiProtocol.extractDataPayload(rawFrame, count);
  }

  /// Escribe un bit individual en el PLC (I, Q, M, V)
  Future<bool> writeBit(int areaCode, int byteIndex, int bitIndex, bool value) async {
    state.addLog("[TX] Escribir bit $byteIndex.$bitIndex = ${value ? 1 : 0}");
    List<int> pdu = PpiProtocol.buildWriteBitPdu(
      areaCode: areaCode,
      startByte: byteIndex,
      bitIndex: bitIndex,
      value: value,
    );
    List<int>? rawFrame = await sendS7Request(pdu);
    bool ok = rawFrame != null;
    state.addLog(ok ? "[✓] Escritura confirmada por el PLC" : "[-] Falló escritura en PLC");
    if (!state.isPolling) {
      await refreshPlcData();
    }
    return ok;
  }

  /// Actualiza todo el estado del PLC (Entradas, Salidas, Modo, Potenciómetros)
  Future<void> refreshPlcData() async {
    if (!state.isConnected || _isRefreshing) return;
    _isRefreshing = true;

    try {
      // 1. Leer Modo y Llave (SMB0, SMB1)
      List<int>? smb = await readMemoryArea(PpiProtocol.areaSM, 0, 2);
      String mode = state.cpuMode;
      String key = state.keyPosition;
      if (smb != null && smb.isNotEmpty) {
        bool isRun = (smb[0] & 0x01) != 0;
        mode = isRun ? "RUN" : "STOP";
        bool switchRun = (smb[0] & 0x80) != 0;
        key = switchRun ? "RUN" : "TERM";
      }
      await Future.delayed(const Duration(milliseconds: 35));

      // 2. Leer Entradas (IB0, IB1) -> 14 entradas
      List<int>? inBytes = await readMemoryArea(PpiProtocol.areaI, 0, 2);
      List<bool> newInputs = List.from(state.inputs);
      if (inBytes != null && inBytes.length >= 2) {
        newInputs = List.generate(14, (_) => false);
        for (int bit = 0; bit < 8; bit++) {
          newInputs[bit] = ((inBytes[0] >> bit) & 1) == 1; // I0.0..I0.7
        }
        for (int bit = 0; bit < 6; bit++) {
          newInputs[8 + bit] = ((inBytes[1] >> bit) & 1) == 1; // I1.0..I1.5
        }
      }
      await Future.delayed(const Duration(milliseconds: 35));

      // 3. Leer Salidas (QB0, QB1) -> 10 salidas
      List<int>? outBytes = await readMemoryArea(PpiProtocol.areaQ, 0, 2);
      List<bool> newOutputs = List.from(state.outputs);
      if (outBytes != null && outBytes.length >= 2) {
        newOutputs = List.generate(10, (_) => false);
        for (int bit = 0; bit < 8; bit++) {
          newOutputs[bit] = ((outBytes[0] >> bit) & 1) == 1; // Q0.0..Q0.7
        }
        for (int bit = 0; bit < 2; bit++) {
          newOutputs[8 + bit] = ((outBytes[1] >> bit) & 1) == 1; // Q1.0..Q1.1
        }
      }
      await Future.delayed(const Duration(milliseconds: 35));

      // 4. Leer Potenciómetros (SMB28, SMB29)
      List<int>? pots = await readMemoryArea(PpiProtocol.areaSM, 28, 2);
      int p0 = pots != null && pots.isNotEmpty ? pots[0] : state.pot0;
      int p1 = pots != null && pots.length >= 2 ? pots[1] : state.pot1;

      state.updateStatus(
        mode: mode,
        key: key,
        newInputs: newInputs,
        newOutputs: newOutputs,
        p0: p0,
        p1: p1,
      );
      state.addLog("[✓] Refresco OK: Modo $mode, I0.1=${newInputs[1] ? 1 : 0}, Pot0=$p0, Pot1=$p1");
    } finally {
      _isRefreshing = false;
    }
  }

  /// Conmuta modo RUN / STOP
  Future<bool> setCpuMode(bool run) async {
    state.addLog("[TX] Conmutando CPU a ${run ? 'RUN' : 'STOP'}...");
    List<int> pdu = PpiProtocol.buildModeCommandPdu(run);
    List<int>? resp = await sendS7Request(pdu);
    await Future.delayed(const Duration(milliseconds: 250));
    await refreshPlcData();
    return resp != null;
  }

  bool _pollingActive = false;

  /// Activa o desactiva el sondeo continuo secuencial (con pausa limpia de 1.2s entre lecturas)
  void togglePolling(bool enable) {
    _pollingActive = enable;
    state.setPolling(enable);
    if (enable) {
      state.addLog("[i] Monitoreo en vivo activado (1.2 s)");
      _runPollingLoop();
    } else {
      state.addLog("[i] Monitoreo en vivo pausado");
    }
  }

  Future<void> _runPollingLoop() async {
    while (_pollingActive && state.isConnected) {
      await refreshPlcData();
      await Future.delayed(const Duration(milliseconds: 1200));
    }
  }
}
