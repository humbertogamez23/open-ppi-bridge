import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'models/plc_state.dart';
import 'services/ble_service.dart';
import 'screens/hmi_dashboard.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  final plcState = PlcState();
  final bleService = BleService(plcState);

  runApp(S7HmiApp(plcState: plcState, bleService: bleService));
}

class S7HmiApp extends StatelessWidget {
  final PlcState plcState;
  final BleService bleService;

  const S7HmiApp({super.key, required this.plcState, required this.bleService});

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider.value(value: plcState),
        Provider.value(value: bleService),
      ],
      child: MaterialApp(
        title: 'Siemens S7-200 HMI',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          brightness: Brightness.dark,
          scaffoldBackgroundColor: const Color(0xFF101418),
          colorScheme: const ColorScheme.dark(
            primary: Colors.cyanAccent,
            secondary: Colors.amberAccent,
            surface: Color(0xFF1E262C),
          ),
          useMaterial3: true,
        ),
        home: HmiDashboard(bleService: bleService),
      ),
    );
  }
}
