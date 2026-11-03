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
                      children: [
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                const Text("ESTADO OPERATIVO", style: TextStyle(color: Color(0xFF90A4AE), fontSize: 11, fontWeight: FontWeight.bold)),
                                const SizedBox(height: 4),
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


class _PulsadorCard extends StatefulWidget {
  final BleService bleService;
  final PlcState state;

  const _PulsadorCard({required this.bleService, required this.state});

  @override
  State<_PulsadorCard> createState() => _PulsadorCardState();
}

class _PulsadorCardState extends State<_PulsadorCard> {
  bool _isPressed = false;
  bool _useMarker = false; // false = I0.0, true = M0.0

  int get targetArea => _useMarker ? PpiProtocol.areaM : PpiProtocol.areaI;
  String get targetLabel => _useMarker ? "M0.0 (Marca de memoria)" : "I0.0 (Entrada física)";

  Future<void> _sendPress(bool active) async {
    setState(() => _isPressed = active);
    await widget.bleService.writeBit(targetArea, 0, 0, active);
  }

  Future<void> _sendQuickPulse() async {
    setState(() => _isPressed = true);
    await widget.bleService.writeBit(targetArea, 0, 0, true);
    await Future.delayed(const Duration(milliseconds: 150));
    await widget.bleService.writeBit(targetArea, 0, 0, false);
    if (mounted) setState(() => _isPressed = false);
  }

  @override
  Widget build(BuildContext context) {
    bool isActuallyActive = _isPressed || (!_useMarker && widget.state.inputs[0]);

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF1E262C),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: isActuallyActive ? Colors.greenAccent : const Color(0xFF2C3942),
          width: isActuallyActive ? 2 : 1,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Row(
                children: [
                  Icon(
                    Icons.touch_app_rounded,
                    color: isActuallyActive ? Colors.greenAccent : Colors.cyanAccent,
                    size: 18,
                  ),
                  const SizedBox(width: 8),
                  Text(
                    "PULSADOR VIRTUAL",
                    style: TextStyle(
                      color: isActuallyActive ? Colors.greenAccent : Colors.cyanAccent,
                      fontSize: 12,
                      fontWeight: FontWeight.bold,
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
                    color: Colors.black38,
                    borderRadius: BorderRadius.circular(6),
                    border: Border.all(color: Colors.cyanAccent.withValues(alpha: 0.5)),
                  ),
                  child: Text(
                    _useMarker ? "Destino: M0.0" : "Destino: I0.0",
                    style: const TextStyle(color: Colors.cyanAccent, fontSize: 11, fontWeight: FontWeight.bold),
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            "Destino actual: $targetLabel",
            style: const TextStyle(color: Colors.grey, fontSize: 11),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                flex: 3,
                child: GestureDetector(
                  behavior: HitTestBehavior.opaque,
                  onTapDown: (_) => _sendPress(true),
                  onTapUp: (_) => _sendPress(false),
                  onTapCancel: () => _sendPress(false),
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 100),
                    padding: const EdgeInsets.symmetric(vertical: 14),
                    decoration: BoxDecoration(
                      gradient: LinearGradient(
                        colors: isActuallyActive
                            ? [Colors.green[600]!, Colors.green[800]!]
                            : [const Color(0xFF2E7D32), const Color(0xFF1B5E20)],
                      ),
                      borderRadius: BorderRadius.circular(10),
                      boxShadow: [
                        BoxShadow(
                          color: isActuallyActive ? Colors.greenAccent.withValues(alpha: 0.6) : Colors.black45,
                          blurRadius: isActuallyActive ? 12 : 4,
                          offset: const Offset(0, 2),
                        ),
                      ],
                    ),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(
                          isActuallyActive ? Icons.radio_button_checked_rounded : Icons.radio_button_off_rounded,
                          color: Colors.white,
                          size: 20,
                        ),
                        const SizedBox(width: 8),
                        Text(
                          isActuallyActive ? "ACTIVO (1)" : "MANTENER PRESIONADO",
                          style: const TextStyle(
                            color: Colors.white,
                            fontWeight: FontWeight.bold,
                            fontSize: 12,
                            letterSpacing: 0.8,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                flex: 2,
                child: ElevatedButton.icon(
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF263238),
                    padding: const EdgeInsets.symmetric(vertical: 14),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(10),
                      side: const BorderSide(color: Color(0xFF37474F)),
                    ),
                  ),
                  onPressed: _sendQuickPulse,
                  icon: const Icon(Icons.flash_on_rounded, color: Colors.amberAccent, size: 16),
                  label: const Text(
                    "PULSO",
                    style: TextStyle(color: Colors.amberAccent, fontWeight: FontWeight.bold, fontSize: 12),
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
