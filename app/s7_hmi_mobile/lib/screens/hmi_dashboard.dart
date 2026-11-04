import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../models/plc_state.dart';
import '../services/ble_service.dart';
import '../services/ppi_protocol.dart';
import '../widgets/led_indicator.dart';

class HmiDashboard extends StatelessWidget {
  final BleService bleService;

  const HmiDashboard({super.key, required this.bleService});

  void _confirmModeChange(BuildContext context, bool toRun) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF263238),
        title: Row(
          children: [
            Icon(
              toRun ? Icons.play_arrow_rounded : Icons.stop_rounded,
              color: toRun ? Colors.greenAccent : Colors.redAccent,
              size: 28,
            ),
            const SizedBox(width: 8),
            Text(
              toRun ? "Iniciar Marcha (RUN)" : "Parar CPU (STOP)",
              style: const TextStyle(color: Colors.white, fontSize: 18),
            ),
          ],
        ),
        content: Text(
          toRun
              ? "¿Desea conmutar la CPU Siemens S7-200 al modo de ejecución (RUN)? Las salidas comenzarán a operar."
              : "¿Está seguro de detener la CPU (STOP)? Todos los procesos y salidas quedarán deshabilitados.",
          style: const TextStyle(color: Color(0xFFCFD8DC), fontSize: 14),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text("CANCELAR", style: TextStyle(color: Colors.grey)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: toRun ? Colors.green[700] : Colors.red[700],
            ),
            onPressed: () async {
              Navigator.pop(ctx);
              bool ok = await bleService.setCpuMode(toRun);
              if (!context.mounted) return;
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(
                  content: Text(ok ? "Modo cambiado con éxito." : "Error enviando comando al PLC."),
                  backgroundColor: ok ? Colors.green[800] : Colors.red[800],
                ),
              );
            },
            child: Text(toRun ? "CONFIRMAR RUN" : "CONFIRMAR STOP", style: const TextStyle(color: Colors.white)),
          ),
        ],
      ),
    );
  }

  Widget _buildLogConsole(PlcState state) {
    return Container(
      margin: const EdgeInsets.only(top: 14),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFF0F141C),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: const Color(0xFF2D3748)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Row(
                children: [
                  Icon(Icons.terminal, color: Colors.cyanAccent, size: 16),
                  SizedBox(width: 6),
                  Text(
                    "DIAGNÓSTICO EN VIVO",
                    style: TextStyle(color: Colors.cyanAccent, fontSize: 11, fontWeight: FontWeight.bold, letterSpacing: 0.8),
                  ),
                ],
              ),
              InkWell(
                onTap: () => state.clearLogs(),
                child: const Padding(
                  padding: EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  child: Text("LIMPIAR", style: TextStyle(color: Colors.grey, fontSize: 10, fontWeight: FontWeight.bold)),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Container(
            height: 120,
            width: double.infinity,
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: Colors.black54,
              borderRadius: BorderRadius.circular(6),
            ),
            child: state.logs.isEmpty
                ? const Center(child: Text("Sin eventos registrados aún...", style: TextStyle(color: Colors.white30, fontSize: 11)))
                : ListView.builder(
                    itemCount: state.logs.length,
                    itemBuilder: (ctx, i) {
                      final line = state.logs[i];
                      Color col = Colors.white70;
                      if (line.contains("[-]")) col = Colors.redAccent;
                      if (line.contains("[✓]")) col = Colors.greenAccent;
                      if (line.contains("[TX]")) col = Colors.lightBlueAccent;
                      if (line.contains("[BLE]")) col = Colors.amberAccent;
                      return Padding(
                        padding: const EdgeInsets.symmetric(vertical: 1.5),
                        child: Text(
                          line,
                          style: TextStyle(color: col, fontSize: 10, fontFamily: 'monospace'),
                        ),
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final state = context.watch<PlcState>();

    return Scaffold(
      backgroundColor: const Color(0xFF101418),
      appBar: AppBar(
        backgroundColor: const Color(0xFF182026),
        elevation: 2,
        title: Row(
          children: [
            const Icon(Icons.developer_board_rounded, color: Colors.cyanAccent, size: 24),
            const SizedBox(width: 10),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text("SIEMENS S7-200 HMI", style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, letterSpacing: 1.1)),
                Text(
                  state.isConnected ? "${state.deviceName} (${state.deviceMac})" : state.deviceName,
                  style: TextStyle(fontSize: 11, color: state.isConnected ? Colors.greenAccent : Colors.grey),
                ),
              ],
            ),
          ],
        ),
        actions: [
          if (state.isConnected)
            IconButton(
              icon: const Icon(Icons.bluetooth_connected, color: Colors.greenAccent),
              onPressed: () => bleService.disconnect(),
              tooltip: "Desconectar",
            )
          else
            ElevatedButton.icon(
              style: ElevatedButton.styleFrom(backgroundColor: Colors.cyan[700], padding: const EdgeInsets.symmetric(horizontal: 12)),
              onPressed: () => bleService.startScanAndConnect(),
              icon: const Icon(Icons.bluetooth_searching, size: 16, color: Colors.white),
              label: const Text("CONECTAR", style: TextStyle(fontSize: 12, color: Colors.white)),
            ),
          const SizedBox(width: 8),
        ],
      ),
      body: !state.isConnected
          ? SingleChildScrollView(
              padding: const EdgeInsets.all(16.0),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const SizedBox(height: 30),
                  const Icon(Icons.bluetooth_disabled_rounded, size: 64, color: Colors.blueGrey),
                  const SizedBox(height: 16),
                  const Text("Puente S7-200-PPI-BLE no conectado", style: TextStyle(color: Colors.white70, fontSize: 16)),
                  const SizedBox(height: 8),
                  const Text("Asegúrate de tener encendido el ESP32-S3", style: TextStyle(color: Colors.grey, fontSize: 13)),
                  const SizedBox(height: 24),
                  ElevatedButton.icon(
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.cyan[700],
                      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
                    ),
                    onPressed: () => bleService.startScanAndConnect(),
                    icon: const Icon(Icons.search, color: Colors.white),
                    label: const Text("BUSCAR Y CONECTAR", style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
                  ),
                  const SizedBox(height: 20),
                  _buildLogConsole(state),
                ],
              ),
            )
          : SingleChildScrollView(
              padding: const EdgeInsets.all(14.0),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  // CARD 1: ESTADO CPU Y CONTROL DE MODO
                  Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: const Color(0xFF1E262C),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: const Color(0xFF2C3942)),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                const Text("MODO CPU (SIEMENS S7-200)", style: TextStyle(color: Color(0xFF90A4AE), fontSize: 11, fontWeight: FontWeight.bold, letterSpacing: 0.5)),
                                const SizedBox(height: 6),
                                Row(
                                  children: [
                                    Container(
                                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                                      decoration: BoxDecoration(
                                        color: state.cpuMode == "RUN" ? Colors.green[900]!.withValues(alpha: 0.4) : Colors.red[900]!.withValues(alpha: 0.4),
                                        borderRadius: BorderRadius.circular(6),
                                        border: Border.all(color: state.cpuMode == "RUN" ? Colors.greenAccent : Colors.redAccent),
                                      ),
                                      child: Text(
                                        state.cpuMode,
                                        style: TextStyle(
                                          color: state.cpuMode == "RUN" ? Colors.greenAccent : Colors.redAccent,
                                          fontWeight: FontWeight.bold,
                                          fontSize: 16,
                                        ),
                                      ),
                                    ),
                                    const SizedBox(width: 8),
                                    Text("Llave: ${state.keyPosition}", style: const TextStyle(color: Colors.white70, fontSize: 12)),
                                  ],
                                ),
                              ],
                            ),
                            // Botones RUN / STOP
                            Row(
                              children: [
                                ElevatedButton(
                                  style: ElevatedButton.styleFrom(
                                    backgroundColor: state.cpuMode == "RUN" ? Colors.green[800] : const Color(0xFF263238),
                                    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                                  ),
                                  onPressed: () => _confirmModeChange(context, true),
                                  child: const Text("RUN", style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
                                ),
                                const SizedBox(width: 8),
                                ElevatedButton(
                                  style: ElevatedButton.styleFrom(
                                    backgroundColor: state.cpuMode == "STOP" ? Colors.red[800] : const Color(0xFF263238),
                                    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                                  ),
                                  onPressed: () => _confirmModeChange(context, false),
                                  child: const Text("STOP", style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
                                ),
                              ],
                            ),
                          ],
                        ),
                        const SizedBox(height: 6),
                        Text(
                          state.cpuMode == "RUN"
                              ? "Scan activo de lógica ladder (Listo para comandos)"
                              : "Procesador en pausa técnica (Salidas deshabilitadas)",
                          style: const TextStyle(color: Colors.white54, fontSize: 11),
                        ),
                      ],
                    ),
                  ),

                  const SizedBox(height: 14),

                  // BANNER PROMINENTE: ESTADO DEL PROCESO Y QUEMADOR
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
                    decoration: BoxDecoration(
                      color: const Color(0xFF1E262C),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(
                        color: state.machineStatusColor.withValues(alpha: 0.8),
                        width: 1.5,
                      ),
                      boxShadow: [
                        BoxShadow(
                          color: state.machineStatusColor.withValues(alpha: 0.15),
                          blurRadius: 10,
                          offset: const Offset(0, 2),
                        ),
                      ],
                    ),
                    child: Row(
                      children: [
                        Container(
                          padding: const EdgeInsets.all(10),
                          decoration: BoxDecoration(
                            color: state.machineStatusColor.withValues(alpha: 0.15),
                            shape: BoxShape.circle,
                            border: Border.all(color: state.machineStatusColor.withValues(alpha: 0.4)),
                          ),
                          child: Icon(
                            state.machineStatusIcon,
                            color: state.machineStatusColor,
                            size: 26,
                          ),
                        ),
                        const SizedBox(width: 14),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                children: [
                                  const Text(
                                    "ESTADO DEL PROCESO / QUEMADOR",
                                    style: TextStyle(
                                      color: Color(0xFF90A4AE),
                                      fontSize: 10,
                                      fontWeight: FontWeight.bold,
                                      letterSpacing: 0.8,
                                    ),
                                  ),
                                  if (state.m0_1)
                                    Container(
                                      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                                      decoration: BoxDecoration(
                                        color: Colors.cyanAccent.withValues(alpha: 0.2),
                                        borderRadius: BorderRadius.circular(4),
                                      ),
                                      child: const Text(
                                        "POST-PURGA 30s",
                                        style: TextStyle(color: Colors.cyanAccent, fontSize: 9, fontWeight: FontWeight.bold),
                                      ),
                                    ),
                                ],
                              ),
                              const SizedBox(height: 4),
                              Text(
                                state.machineStatusTitle,
                                style: TextStyle(
                                  color: state.machineStatusColor,
                                  fontWeight: FontWeight.bold,
                                  fontSize: 16,
                                  letterSpacing: 0.5,
                                ),
                              ),
                              const SizedBox(height: 2),
                              Text(
                                state.machineStatusSubtitle,
                                style: const TextStyle(color: Colors.white70, fontSize: 11),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),

                  const SizedBox(height: 14),

                  // CARD 2: ENTRADAS DIGITALES (I)
                  Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: const Color(0xFF1E262C),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: const Color(0xFF2C3942)),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            const Text("ENTRADAS DIGITALES (I) - 14 Puntos", style: TextStyle(color: Colors.cyanAccent, fontSize: 12, fontWeight: FontWeight.bold)),
                            Text("Activas: ${state.inputs.where((b) => b).length} / 14", style: const TextStyle(color: Colors.grey, fontSize: 11)),
                          ],
                        ),
                        const SizedBox(height: 14),
                        // Fila Byte 0: I0.0 .. I0.7
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: List.generate(8, (i) => LedIndicator(label: "I0.$i", active: state.inputs[i])),
                        ),
                        const SizedBox(height: 14),
                        // Fila Byte 1: I1.0 .. I1.5
                        Row(
                          mainAxisAlignment: MainAxisAlignment.start,
                          children: List.generate(
                            6,
                            (i) => Padding(
                              padding: const EdgeInsets.only(right: 18.0),
                              child: LedIndicator(label: "I1.$i", active: state.inputs[8 + i]),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),

                  const SizedBox(height: 14),

                  // CARD 3: SALIDAS DIGITALES (Q)
                  Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: const Color(0xFF1E262C),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: const Color(0xFF2C3942)),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            const Text("SALIDAS DIGITALES (Q) - 10 Puntos", style: TextStyle(color: Colors.amberAccent, fontSize: 12, fontWeight: FontWeight.bold)),
                            Text("Activas: ${state.outputs.where((b) => b).length} / 10", style: const TextStyle(color: Colors.grey, fontSize: 11)),
                          ],
                        ),
                        const SizedBox(height: 14),
                        // Fila Byte 0: Q0.0 .. Q0.7
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: List.generate(
                            8,
                            (i) => LedIndicator(
                              label: "Q0.$i",
                              active: state.outputs[i],
                              activeColor: const Color(0xFFFFB300),
                            ),
                          ),
                        ),
                        const SizedBox(height: 14),
                        // Fila Byte 1: Q1.0 .. Q1.1
                        Row(
                          mainAxisAlignment: MainAxisAlignment.start,
                          children: List.generate(
                            2,
                            (i) => Padding(
                              padding: const EdgeInsets.only(right: 28.0),
                              child: LedIndicator(
                                label: "Q1.$i",
                                active: state.outputs[8 + i],
                                activeColor: const Color(0xFFFFB300),
                              ),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),

                  const SizedBox(height: 14),

                  // CARD 4: POTENCIÓMETROS ANALÓGICOS (SMB28, SMB29)
                  Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: const Color(0xFF1E262C),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: const Color(0xFF2C3942)),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text("POTENCIÓMETROS ANALÓGICOS INTERNOS", style: TextStyle(color: Colors.tealAccent, fontSize: 12, fontWeight: FontWeight.bold)),
                        const SizedBox(height: 12),
                        // Pot 0
                        Row(
                          children: [
                            const SizedBox(width: 70, child: Text("Pot 0 (SMB28)", style: TextStyle(color: Colors.white70, fontSize: 11))),
                            Expanded(
                              child: LinearProgressIndicator(
                                value: state.pot0 / 255.0,
                                backgroundColor: const Color(0xFF263238),
                                color: Colors.tealAccent,
                                minHeight: 8,
                                borderRadius: BorderRadius.circular(4),
                              ),
                            ),
                            const SizedBox(width: 12),
                            Text("${state.pot0} (${(state.pot0 * 100 ~/ 255)}%)", style: const TextStyle(color: Colors.tealAccent, fontSize: 12, fontFamily: 'monospace')),
                          ],
                        ),
                        const SizedBox(height: 12),
                        // Pot 1
                        Row(
                          children: [
                            const SizedBox(width: 70, child: Text("Pot 1 (SMB29)", style: TextStyle(color: Colors.white70, fontSize: 11))),
                            Expanded(
                              child: LinearProgressIndicator(
                                value: state.pot1 / 255.0,
                                backgroundColor: const Color(0xFF263238),
                                color: Colors.tealAccent,
                                minHeight: 8,
                                borderRadius: BorderRadius.circular(4),
                              ),
                            ),
                            const SizedBox(width: 12),
                            Text("${state.pot1} (${(state.pot1 * 100 ~/ 255)}%)", style: const TextStyle(color: Colors.tealAccent, fontSize: 12, fontFamily: 'monospace')),
                          ],
                        ),
                      ],
                    ),
                  ),

                  const SizedBox(height: 14),

                  // CARD 5: BOTONERA INDUSTRIAL DE CONTROL (MARCHA / PARO APP)
                  _PulsadorControlCard(bleService: bleService, state: state),

                  const SizedBox(height: 14),

                  // BARRA DE MONITOREO CONTINUO
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Row(
                        children: [
                          Switch(
                            value: state.isPolling,
                            activeThumbColor: Colors.cyanAccent,
                            onChanged: (val) => bleService.togglePolling(val),
                          ),
                          const Text("Monitor en vivo (1.2 s)", style: TextStyle(color: Colors.white70, fontSize: 13)),
                        ],
                      ),
                      IconButton(
                        icon: const Icon(Icons.refresh_rounded, color: Colors.cyanAccent),
                        onPressed: () => bleService.refreshPlcData(),
                        tooltip: "Lectura manual puntual",
                      ),
                    ],
                  ),

                  // TERMINAL DE DIAGNÓSTICO EN VIVO
                  _buildLogConsole(state),
                ],
              ),
            ),
    );
  }
}


class _PulsadorControlCard extends StatefulWidget {
  final BleService bleService;
  final PlcState state;

  const _PulsadorControlCard({required this.bleService, required this.state});

  @override
  State<_PulsadorControlCard> createState() => _PulsadorControlCardState();
}

class _PulsadorControlCardState extends State<_PulsadorControlCard> {
  bool _startActive = false;
  bool _stopActive = false;
  bool _useMarker = false; // false = Memoria V (V200.0 / V200.1), true = Memoria M (M10.0 / M10.1)

  int get targetArea => _useMarker ? PpiProtocol.areaM : PpiProtocol.areaV;
  int get targetByte => _useMarker ? 10 : 200;
  String get targetAreaName => _useMarker ? "M (M10.x)" : "V (V200.x) [Recomendado]";
  String get startAddress => _useMarker ? "M10.0" : "V200.0";
  String get stopAddress => _useMarker ? "M10.1" : "V200.1";

  Future<void> _triggerStart() async {
    setState(() => _startActive = true);
    try {
      // Envia pulso seguro a la memoria (Byte = 1 activa bit .0)
      bool ok = await widget.bleService.writeByte(targetArea, targetByte, 0x01);
      await Future.delayed(const Duration(milliseconds: 300));
      // Reset a 0
      await widget.bleService.writeByte(targetArea, targetByte, 0x00);
      if (!ok && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text("[-] Error: El PLC no confirmó la orden de Marcha"),
            backgroundColor: Colors.redAccent,
          ),
        );
      }
    } catch (e) {
      widget.bleService.state.addLog("[-] Excepción Marcha: $e");
    } finally {
      if (mounted) setState(() => _startActive = false);
    }
  }

  Future<void> _triggerStop() async {
    setState(() => _stopActive = true);
    try {
      // Envia pulso seguro a la memoria (Byte = 2 activa bit .1)
      bool ok = await widget.bleService.writeByte(targetArea, targetByte, 0x02);
      await Future.delayed(const Duration(milliseconds: 300));
      // Reset a 0
      await widget.bleService.writeByte(targetArea, targetByte, 0x00);
      if (!ok && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text("[-] Error: El PLC no confirmó la orden de Parada"),
            backgroundColor: Colors.redAccent,
          ),
        );
      }
    } catch (e) {
      widget.bleService.state.addLog("[-] Excepción Parada: $e");
    } finally {
      if (mounted) setState(() => _stopActive = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF1E262C),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: _startActive
              ? Colors.greenAccent
              : (_stopActive ? Colors.redAccent : const Color(0xFF2C3942)),
          width: (_startActive || _stopActive) ? 2 : 1,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Row(
                children: [
                  Icon(Icons.touch_app_rounded, color: Colors.cyanAccent, size: 20),
                  SizedBox(width: 8),
                  Text(
                    "BOTONERA INDUSTRIAL DE CONTROL",
                    style: TextStyle(
                      color: Colors.cyanAccent,
                      fontSize: 12,
                      fontWeight: FontWeight.bold,
                      letterSpacing: 0.8,
                    ),
                  ),
                ],
              ),
              InkWell(
                onTap: () {
                  setState(() => _useMarker = !_useMarker);
                },
                borderRadius: BorderRadius.circular(6),
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: Colors.black45,
                    borderRadius: BorderRadius.circular(6),
                    border: Border.all(color: Colors.cyanAccent.withValues(alpha: 0.5)),
                  ),
                  child: Text(
                    targetAreaName,
                    style: const TextStyle(color: Colors.cyanAccent, fontSize: 10, fontWeight: FontWeight.bold),
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            "Marcha: $startAddress  |  Parada: $stopAddress (Auto-reset en ciclo de PLC)",
            style: const TextStyle(color: Colors.white54, fontSize: 11),
          ),
          const SizedBox(height: 14),
          Row(
            children: [
              // BOTÓN MARCHA (START)
              Expanded(
                child: GestureDetector(
                  behavior: HitTestBehavior.opaque,
                  onTap: _startActive ? null : _triggerStart,
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 120),
                    padding: const EdgeInsets.symmetric(vertical: 16),
                    decoration: BoxDecoration(
                      gradient: LinearGradient(
                        colors: _startActive
                            ? [Colors.green[500]!, Colors.green[700]!]
                            : [const Color(0xFF2E7D32), const Color(0xFF1B5E20)],
                      ),
                      borderRadius: BorderRadius.circular(10),
                      boxShadow: [
                        BoxShadow(
                          color: _startActive ? Colors.greenAccent.withValues(alpha: 0.6) : Colors.black45,
                          blurRadius: _startActive ? 14 : 4,
                          offset: const Offset(0, 2),
                        ),
                      ],
                    ),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(
                          _startActive ? Icons.check_circle_rounded : Icons.play_arrow_rounded,
                          color: Colors.white,
                          size: 26,
                        ),
                        const SizedBox(height: 4),
                        Text(
                          _startActive ? "MARCHA (1)" : "MARCHA",
                          style: const TextStyle(
                            color: Colors.white,
                            fontWeight: FontWeight.bold,
                            fontSize: 13,
                            letterSpacing: 1.0,
                          ),
                        ),
                        Text(
                          "Pulso $startAddress",
                          style: const TextStyle(color: Colors.white70, fontSize: 10),
                        ),
                      ],
                    ),
                  ),
                ),
              ),

              const SizedBox(width: 14),

              // BOTÓN PARADA (STOP)
              Expanded(
                child: GestureDetector(
                  behavior: HitTestBehavior.opaque,
                  onTap: _stopActive ? null : _triggerStop,
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 120),
                    padding: const EdgeInsets.symmetric(vertical: 16),
                    decoration: BoxDecoration(
                      gradient: LinearGradient(
                        colors: _stopActive
                            ? [Colors.red[500]!, Colors.red[800]!]
                            : [const Color(0xFFC62828), const Color(0xFF8E0000)],
                      ),
                      borderRadius: BorderRadius.circular(10),
                      boxShadow: [
                        BoxShadow(
                          color: _stopActive ? Colors.redAccent.withValues(alpha: 0.6) : Colors.black45,
                          blurRadius: _stopActive ? 14 : 4,
                          offset: const Offset(0, 2),
                        ),
                      ],
                    ),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(
                          _stopActive ? Icons.cancel_rounded : Icons.stop_rounded,
                          color: Colors.white,
                          size: 26,
                        ),
                        const SizedBox(height: 4),
                        Text(
                          _stopActive ? "PARADA (1)" : "PARADA",
                          style: const TextStyle(
                            color: Colors.white,
                            fontWeight: FontWeight.bold,
                            fontSize: 13,
                            letterSpacing: 1.0,
                          ),
                        ),
                        Text(
                          "Pulso $stopAddress (Post-Purga 30s)",
                          style: const TextStyle(color: Colors.white70, fontSize: 10),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
