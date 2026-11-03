import 'package:flutter_test/flutter_test.dart';
import 'package:s7_hmi_mobile/models/plc_state.dart';
import 'package:s7_hmi_mobile/services/ble_service.dart';
import 'package:s7_hmi_mobile/main.dart';

void main() {
  testWidgets('Carga inicial de Siemens S7 HMI', (WidgetTester tester) async {
    final state = PlcState();
    final ble = BleService(state);
    await tester.pumpWidget(S7HmiApp(plcState: state, bleService: ble));
    expect(find.text('SIEMENS S7-200 HMI'), findsOneWidget);
  });
}
